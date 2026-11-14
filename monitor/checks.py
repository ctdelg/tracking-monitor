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
    prefix = f"/{market['tealium_profile']}/"
    if prefix not in urlparse(final).path:
        out.append(result("PAGE-01", "site_down", "fail", tid,
                          f"Redirected away from the market ({final}).", {"final_url": final}))
        return out
    out.append(result("PAGE-01", "site_down", "pass", tid, f"HTTP {status}", {"final_url": final}))

    pre, post = visit.get("pre"), visit.get("post")
    if not pre:
        out.append(result("PAGE-02", "site_down", "fail", tid, "No page evidence collected."))
        return out
    out.append(result("PAGE-02", "site_down", "pass" if pre.get("title") else "warn", tid,
                      pre.get("title") or "Empty page title"))

    # Tealium -----------------------------------------------------------------------------
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

    # Consent ---------------------------------------------------------------------------------
    out.append(result("CONS-01", "red", "pass" if pre.get("banner") else "fail", tid,
                      "Banner visible" if pre.get("banner") else "OneTrust banner not visible on first visit."))

    pre_hits = classify(pre.get("requests", []), platforms)
    violations = [h for h in pre_hits
                  if platforms.is_marketing(h["vendor"]) and not _is_denied_google_ping(h)]
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
    granted = [h for h in google_pre if (_gcs(h["url"]) or "G100") != "G100"]
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
    out.extend(_tag_checks(tid, seen, (baseline or {}).get("post"), platforms))

    # Click IDs -----------------------------------------------------------------------------
    out.extend(_click_id_checks(tid, visit.get("click_ids") or {}, post, post_hits,
                                (baseline or {}).get("post") or seen, platforms))
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

def check_tealium(market_code: str, tealium: dict, baseline: dict | None) -> list[dict]:
    """tealium = {"fetch": {...}, "parsed": {...}, "diff": {...}, "conversion": {...}}"""
    out = []
    t = "market"
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
            sev = "red" if lost else "yellow"
            outcome = "fail" if lost else ("warn" if gained else "pass")
            out.append(result(f"CONV-03:{name}", sev, outcome, t,
                              "; ".join(filter(None, [
                                  f"no longer fire: {', '.join(lost)}" if lost else "",
                                  f"newly fire: {', '.join(gained)}" if gained else ""])) or
                              f"Conversion tags unchanged ({', '.join(sorted(base, key=int))})",
                              {"baseline": sorted(base, key=int), "now": sorted(conv_fired, key=int)},
                              title=f"Conversion tag set for '{name}' unchanged"))
    return out
