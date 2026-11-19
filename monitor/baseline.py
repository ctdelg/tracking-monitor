"""Self-learning tag baselines ("what should fire here?").

Nobody has a complete list of which tags belong on which page, so the monitor takes the current
state as the baseline and reports every change from then on:

- Pages and journey steps: a page is LEARNING for its first 3 successful run days. Every vendor
  seen after consent in those runs is added (a tag that only loads sometimes is not lost). After
  the 3rd day the page is CONFIRMED and a missing vendor is reported.
- Pages where tags fire before consent (e.g. ciel.com without a cookie banner) are not learned:
  their after-consent picture is meaningless until the banner works.
- Market rule: a red/yellow vendor (Floodlight, Google Ads, GA4, UET, Meta, LinkedIn ...) that
  fires on most pages of a market is expected on every page of that market, so a tag that is
  missing on a few pages from day one (e.g. UET on the DE payroll/HR pages) is reported instead of
  being frozen as "normal".
- Lead forms, conversion events and GTM conversion tags are deterministic (no browser timing),
  so they are adopted on first sight and compared from then on.

`baseline/<MKT>.json` holds the state. `python -m monitor baseline reset --market X [--url id]`
re-learns after an intended change.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse
from datetime import datetime, timezone

from . import checks
from .config import BASELINE_DIR, Platforms

LEARN_DAYS = 3
CORE_SHARE = 0.6        # vendor on >= 60% of a market's confirmed/learning pages ...
CORE_MIN_PAGES = 3      # ... and on at least 3 pages -> expected everywhere in that market


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(market: str) -> dict:
    p = BASELINE_DIR / f"{market}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"market": market}


def save(market: str, base: dict) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINE_DIR / f"{market}.json").write_text(json.dumps(base, indent=1, ensure_ascii=False), encoding="utf-8")


def _merge(into: dict, seen: dict) -> None:
    for vendor, accounts in seen.items():
        into[vendor] = sorted(set(into.get(vendor, [])) | set(accounts))


def _learn_entry(entry: dict | None, seen: dict, day: str) -> dict:
    entry = dict(entry or {"post": {}, "days": [], "status": "learning", "since": day})
    if entry.get("status") == "confirmed":
        return entry
    entry.setdefault("days", [])
    entry.setdefault("post", {})
    if day not in entry["days"]:
        entry["days"] = sorted(entry["days"] + [day])
    _merge(entry["post"], seen)
    if len(entry["days"]) >= LEARN_DAYS:
        entry["status"], entry["confirmed_at"] = "confirmed", day
    return entry


def _consent_broken(visit: dict, platforms: Platforms) -> bool:
    pre = visit.get("pre") or {}
    hits = checks.classify(pre.get("requests", []), platforms)
    return any(h["vendor"] in platforms.vendors and platforms.is_marketing(h["vendor"])
               and not checks._is_denied_google_ping(h) for h in hits)


def learn(day: str, market: str, raw: dict, platforms: Platforms, main_host: str | None = None) -> dict:
    """Update the market's baseline with today's evidence. Returns the updated baseline.

    main_host: the market's own site. Pages on another site of the market (e.g. www.ciel.com in FR)
    are tagged with their host and get their own market rule.
    """
    base = load(market)
    urls = base.setdefault("urls", {})
    brw = raw.get("browser") or {}
    for v in brw.get("visits", []):
        if v.get("blocked") or not v.get("post") or _consent_broken(v, platforms):
            continue
        seen = checks.vendor_summary(checks.classify(v["post"].get("requests", []), platforms))
        urls[v["id"]] = _learn_entry(urls.get(v["id"]), seen, day)
        host = urlparse(v.get("url") or "").hostname
        if host and main_host and host != main_host:
            urls[v["id"]]["site"] = host
        else:
            urls[v["id"]].pop("site", None)
    journeys = base.setdefault("journeys", {})
    for j in brw.get("journeys", []):
        steps = j.get("steps") or []
        if j.get("blocked") or not steps or any(s.get("error") for s in steps):
            continue
        e = journeys.get(j["id"]) or {"steps": [{} for _ in steps], "days": [], "status": "learning", "since": day}
        if e.get("status") != "confirmed":
            while len(e["steps"]) < len(steps):
                e["steps"].append({})
            for i, s in enumerate(steps):
                _merge(e["steps"][i], checks.vendor_summary(checks.classify((s.get("snapshot") or {}).get("requests", []), platforms)))
            if day not in e["days"]:
                e["days"] = sorted(e["days"] + [day])
            if len(e["days"]) >= LEARN_DAYS:
                e["status"], e["confirmed_at"] = "confirmed", day
        journeys[j["id"]] = e

    # Deterministic parts: adopt on first sight.
    conv = base.setdefault("conversion", {})
    for r in ((raw.get("tealium") or {}).get("conversion") or {}).get("results", []):
        now = r.get("conversion_tags_fired", [])
        before = conv.get(r["name"])
        if before is None:
            conv[r["name"]] = now
        elif set(now) > set(before):
            # only tags added, none lost: a fix (e.g. a tag that was broken fires again) -> adopt it today
            conv[r["name"]] = sorted(now, key=int)
            base.setdefault("conversion_fixed", {})[r["name"]] = {
                "day": day, "gained": sorted(set(now) - set(before), key=int)}
    fb = base.setdefault("forms", {})
    for gid, g in ((raw.get("forms") or {}).get("gates") or {}).items():
        c = g.get("conversion") or {}
        if c.get("evaluated") and gid not in fb:
            fb[gid] = {"tags": c.get("conversion_tags_fired", []), "vendors": c.get("vendors_fired", []), "since": day}
    if raw.get("gtm") and "gtm_conversion_tags" not in base:
        base["gtm_conversion_tags"] = raw["gtm"].get("conversion_tags", {})

    _set_core(base, platforms)
    base["updated_at"] = _now()
    save(market, base)
    return base


def _set_core(base: dict, platforms: Platforms) -> None:
    base["market_core"] = market_core(base, platforms)
    other = sorted({e["site"] for e in (base.get("urls") or {}).values() if e.get("site")})
    if other:
        base["market_core_sites"] = {s: market_core(base, platforms, s) for s in other}
    else:
        base.pop("market_core_sites", None)


def market_core(base: dict, platforms: Platforms, site: str | None = None) -> dict:
    """{vendor: pages it fires on} for important vendors expected on every page of the market.

    Computed per site: the market's own site (site=None) and each other site separately.
    """
    pages = [e for e in (base.get("urls") or {}).values()
             if e.get("post") is not None and e.get("site") == site]
    if len(pages) < CORE_MIN_PAGES:
        return {}
    counts: dict[str, int] = {}
    for e in pages:
        for vendor in e["post"]:
            if vendor in platforms.vendors and platforms.severity(vendor) in ("red", "yellow"):
                counts[vendor] = counts.get(vendor, 0) + 1
    return {v: {"pages": n, "of": len(pages)} for v, n in counts.items()
            if n >= CORE_MIN_PAGES and n / len(pages) >= CORE_SHARE}


def page_expectation(base: dict, page_id: str, site: str | None = None) -> dict | None:
    """What check_page compares against: {"post": {...}, "status": ..., "core": {...}} or None if unknown.

    site: the page's host if it is not on the market's own site; the market rule of that site applies.
    """
    core = ((base.get("market_core_sites") or {}).get(site) or {}) if site else (base.get("market_core") or {})
    e = (base.get("urls") or {}).get(page_id)
    if not e:
        return {"post": None, "status": "new", "core": core}
    return {"post": e.get("post") if e.get("status") == "confirmed" else None, "status": e.get("status"),
            "days": len(e.get("days", [])), "learned": e.get("post"), "core": core}


def adopt_history(market: str, raws: list[tuple[str, dict]], platforms: Platforms,
                  keep_ids: set[str] | None = None, main_host: str | None = None) -> dict:
    """Take everything seen so far as the baseline right away (used once when switching to as-is baselines)."""
    base = {"market": market}
    save(market, base)
    for day, raw in sorted(raws):
        base = learn(day, market, raw, platforms, main_host)
    for e in list((base.get("urls") or {}).values()) + list((base.get("journeys") or {}).values()):
        if e.get("status") != "confirmed":
            e["status"], e["confirmed_at"], e["adopted"] = "confirmed", raws[-1][0] if raws else None, "as-is baseline"
    if keep_ids is not None:   # pages that left the URL list are not part of the baseline
        base["urls"] = {k: v for k, v in (base.get("urls") or {}).items() if k in keep_ids}
        base["journeys"] = {k: v for k, v in (base.get("journeys") or {}).items() if k in keep_ids}
    _set_core(base, platforms)
    base["confirmed_at"] = _now()
    base["confirmed_by"] = "as-is baseline (Paid Media decision, 2026-11-17)"
    save(market, base)
    return base


def reset(market: str, page_ids: list[str] | None = None) -> dict:
    """Forget learned tags so they are learned again (after an intended tag change)."""
    base = load(market)
    if page_ids:
        for pid in page_ids:
            (base.get("urls") or {}).pop(pid, None)
            (base.get("journeys") or {}).pop(pid, None)
    else:
        base = {"market": market}
    save(market, base)
    return base
