"""Orchestration: collect evidence -> evaluate checks -> write results.

Files (all in the repo, kept forever):
    results/raw/<day>/<MKT>.json   raw evidence per market (tealium + browser parts)
    results/<day>.json             evaluated results for the day (dashboard input)
    results/index.json             one line per day and market (history)
    results/utag/<profile>/<day>.*  utag.js snapshots, only stored when utag.js changed
    baseline/<MKT>.json            confirmed expected tags
    baseline/_pending/<MKT>.json   proposed baseline waiting for confirmation
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION, __version__, checks, loadrules, rules, tealium
from .config import BASELINE_DIR, RESULTS_DIR, load_acks, load_markets, load_platforms, load_settings


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def raw_path(day: str, market: str) -> Path:
    return RESULTS_DIR / "raw" / day / f"{market}.json"


# --------------------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------------------

def collect_tealium(browser, market: dict, day: str) -> dict:
    settings = load_settings()
    templates = set(str(k) for k in settings.get("conversion_templates", {}))
    profile = market["tealium_profile"]
    snap_dir = RESULTS_DIR / "utag" / profile
    fetched = tealium.fetch_utag(profile)
    out = {"fetch": {k: v for k, v in fetched.items() if k != "body"}, "parsed": None,
           "diff": None, "conversion": None}
    if not fetched["body"]:
        return out
    parsed = tealium.parse_utag(fetched["body"])
    previous = tealium.latest_snapshot(snap_dir, day)
    diff = tealium.diff_utag(previous, parsed, templates)
    if previous is None or previous["sha256"] != parsed["sha256"]:
        tealium.save_snapshot(snap_dir, day, fetched["body"], parsed)
    out["parsed"] = {"publish_version": parsed["publish_version"], "sha256": parsed["sha256"],
                     "tags": parsed["tags"]}
    out["diff"] = diff

    events = market.get("conversion_events", [])
    conv = loadrules.evaluate(browser, fetched["body"], profile, events)
    for r in conv.get("results", []):
        ev = next((e for e in events if e["name"] == r["name"]), {})
        r["expected_tags"] = [str(t) for t in ev.get("expected_tags", [])]
        r["conversion_tags_fired"] = sorted(
            (t for t in r["fired"] if parsed["tags"].get(t, {}).get("tid") in templates), key=int)
    out["conversion"] = conv
    return out


def collect_browser(browser, market: dict, day: str, url_ids: list[str] | None = None) -> dict:
    from . import browser as br  # imported lazily: only needed in Playwright mode

    platforms = load_platforms()
    locale = market.get("locale", market["tealium_profile"])
    visits, journeys = [], []
    for entry in market["urls"]:
        if url_ids and entry["id"] not in url_ids:
            continue
        visits.append(br.visit_url(browser, market, entry, platforms, day, locale))
        br.politeness_pause()
        if visits[-1].get("blocked") and not url_ids:
            # Bot protection is all-or-nothing; record the rest as blocked without hammering the site.
            for rest in market["urls"][len(visits):]:
                visits.append({"id": rest["id"], "url": rest["url"], "type": rest.get("type"),
                               "blocked": True, "status": visits[-1]["status"], "skipped": True})
            break
    if not any(v.get("blocked") for v in visits):
        for j in market["journeys"]:
            journeys.append(br.run_journey(browser, market, j, platforms, day, locale))
    else:
        journeys = [{"id": j["id"], "name": j.get("name", j["id"]), "blocked": True, "steps": []}
                    for j in market["journeys"]]
    return {"source": "playwright", "collected_at": _now(), "visits": visits, "journeys": journeys}


def store_raw(day: str, market: str, *, tealium_part: dict | None = None,
              browser_part: dict | None = None) -> None:
    path = raw_path(day, market)
    raw = _read(path, {"market": market, "day": day})
    if tealium_part is not None:
        raw["tealium"] = tealium_part
    if browser_part is not None:
        raw["browser"] = browser_part
    _write(path, raw)


def ingest_browser_evidence(day: str, payload: dict) -> list[str]:
    """Merge evidence collected in the Claude built-in browser (collector.js) into raw files.

    payload = {"markets": {"DE": {"visits": [...], "journeys": [...]}, ...}}
    Visits use the same shape as Playwright visits (id, url, status, final_url, pre, post, click_ids).
    """
    done = []
    for code, part in payload["markets"].items():
        existing = (_read(raw_path(day, code), {}) or {}).get("browser") or {"visits": [], "journeys": []}
        by_id = {v["id"]: v for v in existing.get("visits", []) if not v.get("blocked")}
        for v in part.get("visits", []):
            v.setdefault("blocked", False)
            by_id[v["id"]] = v
        jby = {j["id"]: j for j in existing.get("journeys", []) if not j.get("blocked")}
        for j in part.get("journeys", []):
            jby[j["id"]] = j
        store_raw(day, code, browser_part={"source": "claude-browser", "collected_at": _now(),
                                           "visits": list(by_id.values()), "journeys": list(jby.values())})
        done.append(code)
    return done


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------

def load_baseline(market: str) -> dict | None:
    return _read(BASELINE_DIR / f"{market}.json")


def evaluate_day(day: str, only: list[str] | None = None) -> dict:
    markets_cfg = load_markets(only)
    platforms = load_platforms()
    acks = load_acks()
    out_markets = {}
    for code, m in markets_cfg.items():
        raw = _read(raw_path(day, code))
        if not raw:
            continue
        base = load_baseline(code) or {}
        results = []
        if raw.get("tealium"):
            results += checks.check_tealium(code, raw["tealium"], base)
        brw = raw.get("browser") or {}
        url_meta = {u["id"]: u for u in m["urls"]}
        for v in brw.get("visits", []):
            v.setdefault("url", url_meta.get(v["id"], {}).get("url"))
            results += checks.check_page(v, m, platforms, (base.get("urls") or {}).get(v["id"]))
        for j in brw.get("journeys", []):
            results += checks.check_journey(j, platforms, (base.get("journeys") or {}).get(j["id"]))
        applied = rules.apply_acks(code, results, acks, day)
        rating = rules.rate_market(results)
        checked = sum(1 for v in brw.get("visits", []) if not v.get("blocked"))
        rating["pages_checked"], rating["pages_configured"] = checked, len(m["urls"])
        rating["coverage"] = ("tealium_only" if checked == 0 else
                              "full" if checked >= len(m["urls"]) else "partial")
        out_markets[code] = {
            "name": m.get("name", code),
            "tealium_profile": m["tealium_profile"],
            "rating": rating,
            "status": rating["status"],
            "source": brw.get("source", "none"),
            "baseline_confirmed": (base or {}).get("confirmed_at"),
            "utag": {
                "publish_version": ((raw.get("tealium") or {}).get("parsed") or {}).get("publish_version"),
                "changed": bool(((raw.get("tealium") or {}).get("diff") or {}).get("changed")),
                "diff": (raw.get("tealium") or {}).get("diff"),
            },
            "pages": [{"id": u["id"], "url": u["url"], "type": u.get("type")} for u in m["urls"]],
            "checks": results,
            "acks_applied": [a for a in applied if a],
        }
    glob = rules.rate_global(out_markets)
    previous = _previous_day_results(day)
    for code, mk in out_markets.items():
        mk["red_since"] = _red_since(code, mk["status"], day)
        mk["new_failures"] = _new_failures(mk, (previous or {}).get("markets", {}).get(code))
    doc = {
        "schema_version": SCHEMA_VERSION,
        "monitor_version": __version__,
        "day": day,
        "generated_at": _now(),
        "global": glob,
        "markets": out_markets,
    }
    _write(RESULTS_DIR / f"{day}.json", doc)
    _update_index(doc)
    return doc


def _previous_day_results(day: str) -> dict | None:
    days = sorted(p.stem for p in RESULTS_DIR.glob("????-??-??.json") if p.stem < day)
    return _read(RESULTS_DIR / f"{days[-1]}.json") if days else None


def _new_failures(mk: dict, prev: dict | None) -> list[str]:
    key = lambda c: f"{c['id']}|{c['target']}"  # noqa: E731
    now = {key(c) for c in mk["checks"] if c["result"] == "fail"}
    before = {key(c) for c in (prev or {}).get("checks", []) if c["result"] == "fail"}
    return sorted(now - before)


def _red_since(code: str, status: str, day: str) -> str | None:
    if status != "red":
        return None
    index = _read(RESULTS_DIR / "index.json", {"days": {}})
    since = day
    for d in sorted(index["days"], reverse=True):
        if d >= day:
            continue
        if index["days"][d].get(code, {}).get("status") == "red":
            since = d
        else:
            break
    return since


def _update_index(doc: dict) -> None:
    path = RESULTS_DIR / "index.json"
    index = _read(path, {"days": {}})
    index["days"][doc["day"]] = {
        "_global": {"status": doc["global"]["status"], "incidents": len(doc["global"]["incidents"])},
        **{code: {"status": m["status"], "red": m["rating"]["red_count"],
                  "yellow": m["rating"]["yellow_count"], "site_down": len(m["rating"]["site_down"]),
                  "coverage": m["rating"]["coverage"], "publish": m["utag"]["changed"]}
           for code, m in doc["markets"].items()},
    }
    index["days"] = dict(sorted(index["days"].items()))
    _write(path, index)


# --------------------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------------------

def propose_baseline(day: str, market: str, url_ids: list[str] | None = None) -> dict:
    """Build a baseline proposal from a day's raw evidence -> baseline/_pending/<MKT>.json."""
    platforms = load_platforms()
    raw = _read(raw_path(day, market))
    if not raw:
        raise SystemExit(f"No raw evidence for {market} on {day}. Run a collection first.")
    current = load_baseline(market) or {}
    prop = {"market": market, "proposed_from": day, "urls": dict(current.get("urls", {})),
            "journeys": dict(current.get("journeys", {})), "conversion": dict(current.get("conversion", {}))}
    for v in (raw.get("browser") or {}).get("visits", []):
        if v.get("blocked") or not v.get("post") or (url_ids and v["id"] not in url_ids):
            continue
        prop["urls"][v["id"]] = {
            "post": checks.vendor_summary(checks.classify(v["post"]["requests"], platforms)),
        }
    for j in (raw.get("browser") or {}).get("journeys", []):
        if j.get("blocked") or not j.get("steps"):
            continue
        prop["journeys"][j["id"]] = {"steps": [
            checks.vendor_summary(checks.classify((s.get("snapshot") or {}).get("requests", []), platforms))
            for s in j["steps"]]}
    if not url_ids:
        for r in ((raw.get("tealium") or {}).get("conversion") or {}).get("results", []):
            prop["conversion"][r["name"]] = r.get("conversion_tags_fired", [])
    _write(BASELINE_DIR / "_pending" / f"{market}.json", prop)
    return prop


def confirm_baseline(market: str, by: str) -> dict:
    pending = BASELINE_DIR / "_pending" / f"{market}.json"
    prop = _read(pending)
    if not prop:
        raise SystemExit(f"No pending baseline for {market}.")
    prop["confirmed_at"] = _now()
    prop["confirmed_by"] = by
    _write(BASELINE_DIR / f"{market}.json", prop)
    pending.unlink()
    return prop


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
