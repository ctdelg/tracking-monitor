"""Check catalogue (spec §4). Turns collected evidence into check results.

Evidence is the same regardless of how it was collected (Playwright or the
Claude built-in browser), so every check here works for both.

Check result:
    {"id", "title", "severity": red|yellow|site_down|info, "result": pass|fail|warn|skip,
     "target": url id / journey id / "market", "detail": str, "evidence": {...}}
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .config import Platforms

TITLES = {
    "PAGE-01": "Page reachable (HTTP 2xx, no unexpected redirect)",
    "PAGE-02": "Page renders",
    "BOT-01": "Page accessible to the monitor (not blocked by bot protection)",
    "TEAL-01": "Tealium utag.js loads",
    "TEAL-02": "Correct Tealium profile / environment",
    "TEAL-03": "Tealium data layer populated",
    "TEAL-04": "Tealium publish detected (utag.js changed)",
    "TEAL-05": "utag.js reachable on the Tealium CDN",
    "CONS-01": "Consent banner shown on first visit",
    "CONS-02": "No marketing tags or cookies before consent",
    "CONS-03": "Google Consent Mode defaults to denied",
    "CONS-04": "Consent stored after 'Accept all'",
    "CONS-05": "No other third-party requests before consent",
    "PAGE-03": "Landing page loads without redirect",
    "TAG": "Expected tag fires after consent",
    "TAG-ID": "Tag fires with the expected account ID",
    "TAG-NEW": "New tag not in baseline",
    "TAG-BASELINE": "Tag baseline for this page",
    "CLID-01": "gclid stored in _gcl_aw",
    "CLID-02": "msclkid stored in _uetmsclkid",
    "CLID-03": "fbclid stored in _fbc",
    "CLID-04": "gclid passed on Floodlight / Google Ads hits",
    "JRNY-01": "Journey step reachable",
    "JRNY-04": "Click IDs still present at the end of the journey",
    "CONV-01": "Conversion tags would fire for the conversion event (load rules)",
    "CONV-03": "Conversion tag set unchanged vs. baseline",
}

CLICK_ID_CHECKS = {
    "gclid": ("CLID-01", {"google_ads", "floodlight"}),
    "msclkid": ("CLID-02", {"microsoft_uet"}),
    "fbclid": ("CLID-03", {"meta"}),
}


def result(check_id, severity, outcome, target, detail="", evidence=None, title=None):
    return {
        "id": check_id,
        "title": title or TITLES.get(check_id.split(":")[0], check_id),
        "severity": severity,
        "result": outcome,
        "target": target,
        "detail": detail,
        "evidence": evidence or {},
    }


# --------------------------------------------------------------------------------------
# Request classification
# --------------------------------------------------------------------------------------

def _registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def classify(requests: list[dict], platforms: Platforms) -> list[dict]:
    """Map raw requests to tracking hits: [{"vendor", "account", "url"}]."""
    hits = []
    for r in requests:
        url = r.get("url", "")
        if not url.startswith("http"):
            continue
        m = platforms.match(url)
        if m:
            hits.append({"vendor": m[0], "account": m[1], "url": url})
            continue
        host = urlparse(url).hostname or ""
        rtype = (r.get("type") or "").lower()
        rtype = {"img": "image", "xmlhttprequest": "xhr", "sendbeacon": "beacon"}.get(rtype, rtype)
        if platforms.is_ignored_host(host) or rtype not in platforms.discovery_types:
            continue
        hits.append({"vendor": f"other:{_registrable(host)}", "account": None, "url": url})
    return hits


def vendor_summary(hits: list[dict]) -> dict:
    """{vendor: sorted list of account ids} - the shape stored in baselines."""
    out: dict[str, set] = {}
    for h in hits:
        out.setdefault(h["vendor"], set())
        if h["account"]:
            out[h["vendor"]].add(h["account"])
    return {k: sorted(v) for k, v in sorted(out.items())}


def _gcs(url: str) -> str | None:
    m = re.search(r"[?&;]gcs=(G1[0-9]{2})", url)
    return m.group(1) if m else None


def _is_denied_google_ping(hit: dict) -> bool:
    """Consent Mode 'advanced' sends cookieless pings before consent with gcs=G100."""
    return hit["vendor"] in {"ga4", "floodlight", "google_ads"} and _gcs(hit["url"]) == "G100"


# --------------------------------------------------------------------------------------
# Page-level checks
# --------------------------------------------------------------------------------------

def check_page(visit: dict, market: dict, platforms: Platforms, baseline: dict | None) -> list[dict]:
    """All checks for one URL visit.

    visit = {"id", "url", "type", "status", "final_url", "error",
             "pre": snapshot | None, "post": snapshot | None, "click_ids": {"gclid": "..."}}
    baseline = {"pre": {...}, "post": {vendor: [accounts]}} or None
    """
    tid = visit["id"]
    out = []
    status = visit.get("status")

    # Access / reachability -------------------------------------------------------------
    if visit.get("blocked"):
        out.append(result("BOT-01", "system", "fail", tid,
                          f"HTTP {status}: the monitor was blocked by bot protection. "
                          "No tracking verdict possible for this page.",
                          {"status": status}))
        return out
    if visit.get("error") or not status or status >= 400:
        out.append(result("PAGE-01", "site_down", "fail", tid,
                          f"Page not reachable (status {status}, {visit.get('error') or 'no error text'}).",
                          {"status": status, "final_url": visit.get("final_url")}))
        return out
    final = visit.get("final_url") or visit["url"]
    site = urlparse(market_site(market))
    prefix = site.path or "/"
    if urlparse(final).hostname != site.hostname or not urlparse(final).path.startswith(prefix):
        out.append(result("PAGE-01", "site_down", "fail", tid,
                          f"Redirected away from the market ({final}).", {"final_url": final}))
        return out
    out.append(result("PAGE-01", "site_down", "pass", tid, f"HTTP {status}", {"final_url": final}))
    want_path, got_path = urlparse(visit["url"]).path.rstrip("/"), urlparse(final).path.rstrip("/")
    if want_path != got_path:
        to_home = got_path in (prefix.rstrip("/"), "")
        out.append(result("PAGE-03", "yellow" if to_home else "info", "warn", tid,
                          (f"Paid landing page redirects to the market homepage ({final}) - the campaign "
                           "probably points to an expired page." if to_home else
                           f"Redirects to {final}. Update the campaign final URL to avoid the extra hop."),
                          {"requested": visit["url"], "final_url": final}))

    pre, post = visit.get("pre"), visit.get("post")
    if not pre:
        out.append(result("PAGE-02", "site_down", "fail", tid, "No page evidence collected."))
        return out
    out.append(result("PAGE-02", "site_down", "pass" if pre.get("title") else "warn", tid,
                      pre.get("title") or "Empty page title"))

    if not market.get("tealium_profile"):
        out.extend(_gtm_page_checks(tid, market, pre, visit.get("post")))
    else:
        r = _tealium_page_checks(tid, market, pre)
        out.extend(r)
        if any(c["id"] == "TEAL-01" and c["result"] == "fail" for c in r):
            return out
    return out + _consent_and_tag_checks(visit, market, platforms, baseline, tid, pre)


def market_site(market: dict) -> str:
    """Base URL of a market's site: sage.com/<profile>/ by default, or `site` in markets.yaml."""
    return market.get("site") or f"https://www.sage.com/{market['tealium_profile']}/"


def _gtm_page_checks(tid: str, market: dict, pre: dict, post: dict | None) -> list[dict]:
    """Sites run by Google Tag Manager instead of Tealium (e.g. sagedpw.at)."""
    want = (market.get("tag_manager") or {}).get("container")
    loaded = sorted(set((pre.get("gtm") or {}).get("containers", []) + ((post or {}).get("gtm") or {}).get("containers", [])))
    if want and want in loaded:
        return [result("GTM-01", "site_down", "pass", tid, f"{want} loaded", title="Google Tag Manager container loads")]
    return [result("GTM-01", "site_down", "fail", tid,
                   f"Expected GTM container {want} did not load after consent (loaded: {', '.join(loaded) or 'none'}).",
                   {"loaded": loaded}, title="Google Tag Manager container loads")]


def _tealium_page_checks(tid: str, market: dict, pre: dict) -> list[dict]:
    out = []
    utag = pre.get("utag") or {}
    if not utag.get("present"):
        out.append(result("TEAL-01", "site_down", "fail", tid,
                          "utag.js did not initialise on the page.", {"scripts": utag.get("scripts")}))
        return out
    out.append(result("TEAL-01", "site_down", "pass", tid, utag.get("version") or ""))
    want = f"sage/{market['tealium_profile']}/"
    env_ok = "/prod/" in (utag.get("path") or "/prod/")
    if utag.get("utid", "").startswith(want) and env_ok:
        out.append(result("TEAL-02", "red", "pass", tid, utag.get("utid")))
    else:
        out.append(result("TEAL-02", "red", "fail", tid,
                          f"Expected profile {market['tealium_profile']}/prod, page loads {utag.get('utid')} ({utag.get('path')}).",
                          {"utid": utag.get("utid"), "path": utag.get("path")}))
    missing = [k for k in ("page_type", "language", "country") if not utag.get(k)]
    out.append(result("TEAL-03", "yellow", "warn" if missing else "pass", tid,
                      f"Missing data layer values: {', '.join(missing)}" if missing else
                      f"{utag.get('data_keys')} data layer values"))
    return out


def _consent_and_tag_checks(visit, market, platforms, baseline, tid, pre) -> list[dict]:
    out = []
    post = visit.get("post")
    tool = {"usercentrics": "Usercentrics", "onetrust": "OneTrust"}.get(pre.get("consent_tool") or "", "Consent")
    # Consent ---------------------------------------------------------------------------------
    out.append(result("CONS-01", "red", "pass" if pre.get("banner") else "fail", tid,
                      f"{tool} banner visible" if pre.get("banner") else f"{tool} banner not visible on first visit."))

    pre_hits = classify(pre.get("requests", []), platforms)
    violations = [h for h in pre_hits
                  if h["vendor"] in platforms.vendors and platforms.is_marketing(h["vendor"])
                  and not _is_denied_google_ping(h)]
    unknown_pre = sorted({h["vendor"].split(":", 1)[1] for h in pre_hits if h["vendor"].startswith("other:")})
    out.append(result("CONS-05", "yellow", "warn" if unknown_pre else "pass", tid,
                      "Third-party requests before consent (not an ad tag, review with the privacy team): "
                      + ", ".join(unknown_pre) if unknown_pre else "No other third-party requests before consent",
                      {"hosts": unknown_pre}))
    bad_cookies = sorted(set(pre.get("cookies", {})) & platforms.marketing_cookies)
    if violations or bad_cookies:
        names = sorted({platforms.display_name(h["vendor"]) for h in violations})
        out.append(result("CONS-02", "red", "fail", tid,
                          "Before consent: " + "; ".join(filter(None, [
                              f"tags fired ({', '.join(names)})" if names else "",
                              f"cookies set ({', '.join(bad_cookies)})" if bad_cookies else ""])),
                          {"hits": [h["url"][:300] for h in violations][:10], "cookies": bad_cookies}))
    else:
        out.append(result("CONS-02", "red", "pass", tid, "No marketing tags or cookies before consent"))

    google_pre = [h for h in pre_hits if h["vendor"] in {"ga4", "floodlight", "google_ads"}]
    # A Google hit before consent is only fine as a Consent Mode ping with gcs=G100 (denied).
    # Hits without any consent signal (no Consent Mode at all) count as granted.
    granted = [h for h in google_pre if _gcs(h["url"]) != "G100"]
    out.append(result("CONS-03", "red", "fail" if granted else "pass", tid,
                      f"{len(granted)} Google hit(s) before consent without denied consent state"
                      if granted else "Consent Mode default denied (or no Google hits before consent)",
                      {"hits": [h["url"][:300] for h in granted][:5]}))

    if not post:
        out.append(result("CONS-04", "red", "fail", tid, "No evidence after accepting consent."))
        return out
    groups = post.get("consent_groups") or ""
    all_granted = bool(groups) and ":0" not in groups
    if not post.get("accepted", True):
        out.append(result("CONS-04", "red", "fail", tid, "'Accept all' button not found."))
    else:
        out.append(result("CONS-04", "red", "pass" if all_granted else "fail", tid,
                          f"Consent groups: {groups}" if groups else "OptanonConsent cookie missing"))

    # Tags after consent (baseline-driven) ---------------------------------------------------
    post_hits = classify(post.get("requests", []), platforms)
    seen = vendor_summary(post_hits)
    b = baseline or {}
    expected = b.get("post")
    if expected is None and b.get("status") in ("learning", "new"):
        n = b.get("days", 0)
        out.append(result("TAG-BASELINE", "info", "warn", tid,
                          f"Learning which tags belong on this page ({n} of 3 run days). Tags are recorded; "
                          "from the 3rd day a missing tag is reported.", {"seen": seen}))
    else:
        out.extend(_tag_checks(tid, seen, expected, platforms))
    core = b.get("core") or {}
    for vendor, info in sorted(core.items()):
        if vendor in seen or (expected and vendor in expected):
            continue
        out.append(result(f"TAG:{vendor}", platforms.severity(vendor), "fail", tid,
                          f"{platforms.display_name(vendor)} did not fire here, although it fires on "
                          f"{info['pages']} of {info['of']} pages of this market.",
                          {"market_pages_with_tag": info}, title=f"{platforms.display_name(vendor)} fires like on the market's other pages"))

    # Click IDs -----------------------------------------------------------------------------
    expected_vendors = {**seen, **(b.get("learned") or {}), **(expected or {}), **{v: [] for v in core}}
    out.extend(_click_id_checks(tid, visit.get("click_ids") or {}, post, post_hits, expected_vendors, platforms))
    return out


def _tag_checks(target: str, seen: dict, expected: dict | None, platforms: Platforms) -> list[dict]:
    out = []
    if expected is None:
        out.append(result("TAG-BASELINE", "yellow", "warn", target,
                          "No confirmed baseline yet - tags recorded but not compared.",
                          {"seen": seen}))
        return out
    for vendor, accounts in expected.items():
        name = platforms.display_name(vendor)
        sev = platforms.severity(vendor)
        cid = f"TAG:{vendor}"
        if vendor not in seen:
            out.append(result(cid, sev, "fail", target, f"{name} did not fire after consent.",
                              {"expected_accounts": accounts}, title=f"{name} fires after consent"))
            continue
        missing_ids = sorted(set(accounts) - set(seen[vendor]))
        if missing_ids:
            out.append(result(cid, sev, "fail", target,
                              f"{name} fired, but not for account(s) {', '.join(missing_ids)} "
                              f"(seen: {', '.join(seen[vendor]) or 'none'}).",
                              {"expected": accounts, "seen": seen[vendor]},
                              title=f"{name} fires with the expected account ID"))
        else:
            out.append(result(cid, sev, "pass", target, ", ".join(seen[vendor]),
                              title=f"{name} fires after consent"))
    new = sorted(set(seen) - set(expected))
    if new:
        out.append(result("TAG-NEW", "info", "warn", target,
                          "Not in baseline: " + ", ".join(platforms.display_name(v) for v in new),
                          {"vendors": {v: seen[v] for v in new}}))
    return out


def _click_id_checks(target, click_ids, post, post_hits, expected_vendors, platforms) -> list[dict]:
    out = []
    cookies = (post or {}).get("cookies", {})
    for param, (cid, vendors) in CLICK_ID_CHECKS.items():
        value = click_ids.get(param)
        if not value or not (vendors & set(expected_vendors or {})):
            continue  # vendor not used on this page -> check not applicable
        cfg = platforms.click_id_cookies.get(param, {})
        cookie = cfg.get("cookie")
        sev = cfg.get("severity", "red")
        ok = cookie in cookies and value in cookies[cookie]
        out.append(result(cid, sev, "pass" if ok else "fail", target,
                          f"{cookie} contains the test {param}" if ok else
                          f"{cookie} missing or does not contain the test {param}.",
                          {"cookie": cookie, "value": cookies.get(cookie)}))
    gclid = click_ids.get("gclid")
    google = [h for h in post_hits if h["vendor"] in {"floodlight", "google_ads"}]
    if gclid and google:
        with_id = [h for h in google if gclid in h["url"]]
        out.append(result("CLID-04", "red", "pass" if with_id else "fail", target,
                          f"{len(with_id)}/{len(google)} Google Ads/Floodlight hits carry the gclid"
                          if with_id else "No Floodlight / Google Ads hit carries the gclid (gclaw/gclid).",
                          {"sample": google[0]["url"][:300]}))
    return out


# --------------------------------------------------------------------------------------
# Journeys
# --------------------------------------------------------------------------------------

def check_journey(journey: dict, platforms: Platforms, baseline: dict | None) -> list[dict]:
    """journey = {"id", "steps": [{"url", "status", "error", "snapshot"}], "click_ids"}"""
    jid = journey["id"]
    out = []
    steps = journey.get("steps", [])
    if journey.get("blocked"):
        return [result("BOT-01", "system", "fail", jid, "Journey blocked by bot protection.")]
    for i, step in enumerate(steps):
        target = f"{jid}#{i + 1}"
        if step.get("error") or not step.get("snapshot"):
            out.append(result("JRNY-01", "site_down", "fail", target,
                              f"Step {i + 1} failed: {step.get('error') or 'no evidence'}"))
            return out
        out.append(result("JRNY-01", "site_down", "pass", target, step["snapshot"].get("url", "")))
        hits = classify(step["snapshot"].get("requests", []), platforms)
        if (baseline or {}).get("status", "confirmed") != "confirmed":
            continue  # still learning this journey's tags
        exp = ((baseline or {}).get("steps") or [None] * len(steps))
        exp_step = exp[i] if i < len(exp) else None
        out.extend(_tag_checks(target, vendor_summary(hits), exp_step, platforms))
    last = steps[-1]["snapshot"] if steps else None
    cookies = (last or {}).get("cookies", {})
    for param, value in (journey.get("click_ids") or {}).items():
        cfg = platforms.click_id_cookies.get(param)
        if not cfg:
            continue
        vendors = CLICK_ID_CHECKS[param][1]
        expected_any = set()
        for s in ((baseline or {}).get("steps") or []):
            expected_any |= set(s or {})
        if not (vendors & expected_any):
            continue
        ok = value in cookies.get(cfg["cookie"], "")
        out.append(result("JRNY-04", cfg.get("severity", "red"), "pass" if ok else "fail",
                          f"{jid}#{len(steps)}",
                          f"{param} still in {cfg['cookie']} at the last step" if ok else
                          f"{param} lost before the last step ({cfg['cookie']} missing).",
                          title=f"{param} survives the journey"))
    return out


# --------------------------------------------------------------------------------------
# Tealium / conversion (market level)
# --------------------------------------------------------------------------------------

def check_forms(market: dict, forms_part: dict, baseline: dict | None) -> list[dict]:
    """Lead form checks (see monitor/forms.py). forms_part = raw["forms"]."""
    from .forms import lead_type

    out = []
    script = forms_part.get("event_script") or {}
    if not script.get("ok"):
        out.append(result("FORM-00", "red", "warn", "market",
                          f"Form tracking script could not be read: {script.get('error')}"))
    elif script.get("missing"):
        out.append(result("FORM-00", "red", "fail", "market",
                          "The Gated Content submit script no longer sends: " + ", ".join(script["missing"])
                          + ". No lead form on the site would fire its conversion tags.",
                          {"missing": script["missing"]}))
    else:
        out.append(result("FORM-00", "red", "pass", "market",
                          "Submit script sends utag.link with action and gate_content_name"))

    required = market.get("form_conversion_required", True)
    base_forms = (baseline or {}).get("forms") or {}
    for gid, g in sorted((forms_part.get("gates") or {}).items(), key=lambda kv: kv[1].get("gate_name") or kv[0]):
        target = f"form:{g.get('gate_name') or gid[:8]}"
        ev = {"gate_id": gid, "pages": g.get("pages"), "ctas": g.get("ctas"), "gate_type": g.get("gate_type"),
              "gate_content_name": g.get("last_content_name")}
        if not g.get("ok"):
            out.append(result("FORM-01", "red", "fail", target,
                              f"Form configuration not available ({g.get('error')}). The CTA opens nothing.", ev))
            continue
        if g.get("inactive"):
            out.append(result("FORM-01", "red", "fail", target,
                              "The form is switched off (gateInactive) but CTAs still point to it.", ev))
            continue
        out.append(result("FORM-01", "red", "pass", target,
                          f"{g.get('gate_type')} form, used on {len(g.get('pages') or [])} page(s)", ev))

        missing_on = g.get("missing_on") or []
        if missing_on:
            out.append(result("FORM-05", "red", "fail", target,
                              f"CTA '{(g.get('ctas') or ['?'])[0]}' links to this form, but the form is not on "
                              f"the page: {', '.join(missing_on)}. Clicking it does nothing.", ev,
                              title="CTA opens its form"))

        name = g.get("last_content_name") or ""
        lt = lead_type(name)
        if not name or not lt:
            out.append(result("FORM-02", "yellow", "fail", target,
                              f"gate_content_name '{name or '(empty)'}' has no lead type code (_DEM_, _TOO_, _CON_, "
                              "_PDF_ ...). Tealium cannot classify the lead, so lead-type based tags will not fire.", ev,
                              title="Lead type can be derived from the form name"))
        else:
            # Leading/trailing spaces break Tealium rules that anchor on the start of the name
            # (e.g. DE rule 331 for Floodlight tag 389); different-but-valid naming styles are fine.
            clean = name == name.strip()
            out.append(result("FORM-02", "yellow", "pass" if clean else "warn", target,
                              f"{name.strip()} -> {lt}" + ("" if clean else
                              " - the name has a leading or trailing space, so rules that check the start of the "
                              "name (for example Floodlight tags that need a specific code) will not match"),
                              title="Lead type can be derived from the form name"))

        conv = g.get("conversion") or {}
        if not conv.get("evaluated"):
            out.append(result("FORM-03", "red", "warn", target,
                              f"Submit could not be replayed through Tealium: {conv.get('error') or 'not evaluated'}",
                              title="Conversion tags fire on submit"))
        else:
            fired = conv.get("conversion_tags_fired") or []
            vend = conv.get("vendors_fired") or []
            if fired:
                out.append(result("FORM-03", "red", "pass", target,
                                  f"On submit these conversion tags would fire: {', '.join(fired)}"
                                  + (f" (platforms: {', '.join(vend)})" if vend else ""),
                                  {**ev, "fired": fired, "vendors": vend}, title="Conversion tags fire on submit"))
            else:
                out.append(result("FORM-03", "red" if required else "yellow", "fail", target,
                                  "On submit no Floodlight / Google Ads conversion tag would fire "
                                  f"(gate_content_name {name or '(empty)'}).",
                                  {**ev, "fired_all": conv.get("fired")}, title="Conversion tags fire on submit"))
            bf = base_forms.get(gid)
            if isinstance(bf, dict) and bf.get("vendors") is not None:
                lost_v = sorted(set(bf["vendors"]) - set(vend))
                if lost_v:
                    from .config import load_platforms
                    p = load_platforms()
                    sev = "red" if any(p.severity(v) == "red" for v in lost_v) else "yellow"
                    out.append(result("FORM-07", sev, "fail", target,
                                      "On submit these platforms no longer receive the event: "
                                      + ", ".join(p.display_name(v) for v in lost_v),
                                      {"baseline": bf["vendors"], "now": vend},
                                      title="Platforms receiving the form submit unchanged (LinkedIn, Meta, UET ...)"))
                else:
                    out.append(result("FORM-07", "yellow", "pass", target, ", ".join(vend),
                                      title="Platforms receiving the form submit unchanged (LinkedIn, Meta, UET ...)"))
            if gid in base_forms:
                base = set(bf["tags"] if isinstance(bf, dict) else bf)
                now = set(fired)
                lost, gained = sorted(base - now, key=int), sorted(now - base, key=int)
                if lost or gained:
                    out.append(result("FORM-06", "red" if lost else "yellow", "fail" if lost else "warn", target,
                                      "; ".join(filter(None, [
                                          f"no longer fire: {', '.join(lost)}" if lost else "",
                                          f"newly fire: {', '.join(gained)}" if gained else ""])),
                                      {"baseline": sorted(base, key=int), "now": sorted(now, key=int)},
                                      title="Form conversion tags unchanged vs. baseline"))

        status = g.get("target_status")
        if g.get("gate_type") in ("redirect", "download") and status is not None:
            what = "Product tour / redirect target" if g["gate_type"] == "redirect" else "Download file"
            url = g.get("redirect_url") or g.get("download_url")
            out.append(result("FORM-04", "red", "pass" if 200 <= int(status) < 400 else "fail", target,
                              f"{what} {url} answers HTTP {status}" if 200 <= int(status) < 400 else
                              f"{what} {url} is broken (HTTP {status}). Leads get no content after submitting.",
                              {"url": url, "status": status}, title="Content behind the form is reachable"))
    return out


def _trigger_reachable(paths: list, snaps: list[dict]) -> tuple[bool | None, str]:
    """Can a visitor set off this click-based GTM trigger on the checked pages?

    Returns (True/False, explanation), or (None, ...) when the trigger is not click-based
    (then it cannot be judged from the page alone).
    """
    reasons = []
    judged = False
    for conds in paths:
        if not any(c["var"] == "__e" and c["value"] == "gtm.click" for c in conds):
            continue
        judged = True
        ok_all, why = True, []
        for c in conds:
            if c["fn"] != "_cn" or c["var"] not in ("ID", "Click ID", "URL", "Click URL"):
                continue
            val = str(c["value"])
            if c["var"] in ("ID", "Click ID"):
                hits = [s["id"] for sn in snaps for s in sn.get("submit_controls", []) if val in s.get("id", "")]
                buttons = [s for sn in snaps for s in sn.get("submit_controls", [])]
                if not hits:
                    ok_all = False
                    why.append(f"no form button has an ID containing '{val}'"
                               + (f" (buttons found: {', '.join(repr(b['text']) + ' id=' + (b['id'] or 'none') for b in buttons[:4])})" if buttons else " (no form buttons on the checked pages)"))
            else:
                hits = [h for sn in snaps for h in sn.get("doc_links", []) if val in h]
                if not hits:
                    ok_all = False
                    why.append(f"no link to '{val}' on the checked pages")
        if ok_all:
            return True, "trigger element present"
        reasons += why
    if not judged:
        return None, "not a click trigger"
    return False, "; ".join(reasons)


def check_gtm(market: dict, part: dict, baseline: dict | None, browser_part: dict | None = None) -> list[dict]:
    """Google Tag Manager container checks for non-Tealium sites (AT: sagedpw.at)."""
    out, t = [], "market"
    c = part.get("container")
    f = part.get("fetch") or {}
    if not part.get("parsed"):
        return [result("GTM-05", "site_down", "fail", t,
                       f"GTM container {c} not readable ({f.get('status')}: {f.get('error')}).",
                       title="GTM container published and readable")]
    out.append(result("GTM-05", "site_down", "pass", t,
                      f"{c} version {part['parsed']['version']} ({len(part['parsed']['tags'])} tags)",
                      title="GTM container published and readable"))
    d = part.get("diff") or {}
    if d.get("changed"):
        n_conv = sum(1 for i in d["items"] if i["conversion_relevant"])
        out.append(result("GTM-04", "yellow" if d.get("conversion_relevant") else "info", "warn", t,
                          f"New GTM publish v{d.get('from_version')} -> v{d.get('to_version')}: "
                          f"{len(d['items'])} tag change(s), {n_conv} conversion-relevant.",
                          {"items": d["items"][:50]}, title="GTM publish detected"))
    else:
        out.append(result("GTM-04", "info", "pass", t, "No publish since the last run", title="GTM publish detected"))
    now = part.get("conversion_tags") or {}
    if not any(v.startswith("Floodlight") or v.startswith("Google Ads conversion") for v in now.values()):
        out.append(result("GTM-06", "red", "fail", t,
                          "The container has no live Floodlight or Google Ads conversion tag.",
                          {"conversion_tags": now}, title="Conversion tags live in the container"))
    base = (baseline or {}).get("gtm_conversion_tags")
    if base is not None:
        lost = {k: v for k, v in base.items() if k not in now}
        if lost:
            out.append(result("GTM-06", "red", "fail", t,
                              "Conversion tags removed or paused since the baseline: " + "; ".join(lost.values()),
                              {"baseline": base, "now": now}, title="Conversion tags live in the container"))
        else:
            out.append(result("GTM-06", "red", "pass", t, "; ".join(now.values()),
                              title="Conversion tags live in the container"))
    elif now:
        out.append(result("GTM-06", "red", "pass", t, "; ".join(now.values()),
                          title="Conversion tags live in the container"))

    # GTM-07: can visitors actually set off each conversion trigger on the checked pages?
    snaps = []
    for v in (browser_part or {}).get("visits", []):
        if v.get("pre") and "submit_controls" in v["pre"]:
            snaps.append(v["pre"])
    for j in (browser_part or {}).get("journeys", []):
        snaps += [s["snapshot"] for s in j.get("steps", []) if s.get("snapshot") and "submit_controls" in s["snapshot"]]
    if snaps:
        for label, paths in sorted((part.get("triggers") or {}).items()):
            ok, why = _trigger_reachable(paths, snaps)
            if ok is None:
                continue
            only_links = not ok and "no form button" not in why
            sev = "yellow" if only_links else "red"
            text = ("a visitor can trigger it on the checked pages" if ok else
                    f"cannot fire from the paid landing pages or form pages - {why}. The link may exist elsewhere on the site."
                    if only_links else
                    f"can never fire on form submit - {why}. The GTM trigger and the website no longer match.")
            if label in (market.get("tag_manager") or {}).get("lead_form_conversions", []):
                # mirror the lead-form conversion into the cross-market conversion table
                out.append(result("CONV-01:gated_contact", "red", "pass" if ok else "fail", "market",
                                  f"Lead form submit: Floodlight {label} " + ("would fire." if ok else f"would NOT fire - {why}."),
                                  {"trigger": paths}, title="Conversion tags fire for lead forms (GTM trigger)"))
            if label in (market.get("tag_manager") or {}).get("lead_form_conversions", []):
                for ev in (market.get("tag_manager") or {}).get("not_offered", []):
                    out.append(result(f"CONV-01:{ev}", "info", "skip", "market",
                                      f"'{ev}' is not offered in this market - not checked."))
            out.append(result("GTM-07", sev, "pass" if ok else "fail", f"conversion:{label}",
                              f"Floodlight {label}: " + text,
                              {"trigger": paths, "pages_checked": len(snaps)},
                              title="Conversion trigger can fire on the site"))
    return out


def check_tealium(market_code: str, tealium: dict, baseline: dict | None, target: str = "market") -> list[dict]:
    """tealium = {"fetch": {...}, "parsed": {...}, "diff": {...}, "conversion": {...}}"""
    out = []
    t = target
    f = tealium.get("fetch", {})
    if not f.get("status") or f["status"] >= 400:
        out.append(result("TEAL-05", "site_down", "fail", t,
                          f"utag.js not reachable on the CDN ({f.get('status')}: {f.get('error')}).",
                          {"url": f.get("url")}))
        return out
    out.append(result("TEAL-05", "site_down", "pass", t,
                      f"Publish {tealium['parsed'].get('publish_version')} ({len(tealium['parsed']['tags'])} tags)"))

    d = tealium.get("diff") or {}
    if d.get("changed"):
        sev = "yellow" if d.get("conversion_relevant") else "info"
        n_conv = sum(1 for i in d["items"] if i["conversion_relevant"])
        out.append(result("TEAL-04", sev, "warn", t,
                          f"New Tealium publish {d.get('from_version')} -> {d.get('to_version')}: "
                          f"{len(d['items'])} change(s), {n_conv} conversion-relevant.",
                          {"items": d["items"][:50]}))
    else:
        out.append(result("TEAL-04", "info", "pass", t, "No publish since the last run"))

    conv = tealium.get("conversion") or {}
    if not conv.get("ok"):
        out.append(result("CONV-01", "red", "warn", t,
                          f"Load-rule evaluation could not run: {conv.get('error')}"))
        return out
    exp_events = (baseline or {}).get("conversion") or {}
    for r in conv["results"]:
        name = r["name"]
        fired = set(r["fired"])
        expected = set(r.get("expected_tags") or [])
        cid = f"CONV-01:{name}"
        if r.get("not_offered"):
            out.append(result(cid, "info", "skip", t, f"'{name}' is not offered in this market - not checked.",
                              title=f"Conversion tags fire for '{name}' (load rules)"))
            continue
        if expected:
            missing = sorted(expected - fired, key=int)
            out.append(result(cid, "red", "fail" if missing else "pass", t,
                              f"Event '{name}': tag(s) {', '.join(missing)} would NOT fire."
                              if missing else f"Event '{name}': tag(s) {', '.join(sorted(expected, key=int))} fire.",
                              {"fired": sorted(fired, key=int), "true_rules": r.get("true_rules", [])[:80],
                               "errors": r.get("errors")},
                              title=f"Conversion tags fire for '{name}' (load rules)"))
        conv_fired = set(r.get("conversion_tags_fired") or [])
        if name in exp_events:
            base = set(exp_events[name])
            lost, gained = sorted(base - conv_fired, key=int), sorted(conv_fired - base, key=int)
            # tags only gained = a fix, not a risk: green right away
            sev = "red" if lost else "info"
            outcome = "fail" if lost else "pass"
            fixed = ((baseline or {}).get("conversion_fixed") or {}).get(name)
            out.append(result(f"CONV-03:{name}", sev, outcome, t,
                              "; ".join(filter(None, [
                                  f"no longer fire: {', '.join(lost)}" if lost else "",
                                  f"fixed - newly fire: {', '.join(gained)}" if gained else ""])) or
                              (f"Fixed on {fixed['day']}: tag(s) {', '.join(fixed['gained'])} fire again; "
                               f"now {', '.join(sorted(base, key=int))}" if fixed else
                               f"Conversion tags unchanged ({', '.join(sorted(base, key=int))})"),
                              {"baseline": sorted(base, key=int), "now": sorted(conv_fired, key=int)},
                              title=f"Conversion tag set for '{name}' unchanged"))
    return out
