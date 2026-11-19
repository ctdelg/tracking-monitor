"""Command line interface.

    python -m monitor run [--market DE FR] [--no-browser]      collect + evaluate + report
    python -m monitor collect [--market ..] [--url ID ..] [--no-browser]
    python -m monitor ingest evidence.json [--day YYYY-MM-DD]   evidence from the Claude browser
    python -m monitor evaluate [--day ..]
    python -m monitor baseline show --market DE                  learned tags, learning status, market rule
    python -m monitor baseline reset --market DE [--url ID ..]   re-learn after an intended tag change
    python -m monitor baseline adopt --market DE                 take everything seen so far as baseline now
    python -m monitor report [--day ..]                         static HTML (fallback dashboard)
    python -m monitor dashboard [--day ..] --out FILE           dashboard page for the Claude artifact
    python -m monitor forms import inventory.json --market DE    lead form inventory from forms_inventory.js
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import pipeline
from .config import RESULTS_DIR, load_markets


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def cmd_collect(args) -> None:
    from playwright.sync_api import sync_playwright

    markets = load_markets(args.market)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for code, m in markets.items():
                forms_part = None
                if m.get("tealium_profile"):
                    print(f"[{code}] Tealium CDN + load rules ...", flush=True)
                    teal = pipeline.collect_tealium(browser, m, args.day)
                    pipeline.store_raw(args.day, code, tealium_part=teal)
                    print(f"[{code}] lead forms ...", flush=True)
                    forms_part = pipeline.collect_forms(browser, m, teal.get("_body"))
                    pipeline.store_raw(args.day, code, forms_part=forms_part)
                    extra = {}
                    for prof in m.get("extra_tealium_profiles") or []:
                        print(f"[{code}] Tealium profile {prof} ...", flush=True)
                        events = (m.get("profile_conversion_events") or {}).get(prof, m["conversion_events"])
                        extra[prof] = pipeline.collect_tealium(
                            browser, {**m, "tealium_profile": prof, "conversion_events": events}, args.day)
                    if extra:
                        pipeline.store_raw(args.day, code, tealium_extra=extra)
                else:
                    print(f"[{code}] Google Tag Manager container ...", flush=True)
                    # tealium/forms parts are cleared so nothing from an earlier sage.com setup lingers
                    pipeline.store_raw(args.day, code, gtm_part=pipeline.collect_gtm(m, args.day),
                                       tealium_part={}, forms_part={})
                if not args.no_browser:
                    print(f"[{code}] browser checks ({len(m['urls'])} URLs, {len(m['journeys'])} journeys) ...",
                          flush=True)
                    part = pipeline.collect_browser(browser, m, args.day, args.url, forms_part)
                    blocked = sum(1 for v in part["visits"] if v.get("blocked"))
                    if blocked:
                        print(f"[{code}]   {blocked} page(s) blocked by bot protection", flush=True)
                    pipeline.update_form_inventory(code, part["visits"], args.day)
                    pipeline.store_raw(args.day, code, browser_part=part)
        finally:
            browser.close()


def cmd_evaluate(args) -> dict:
    doc = pipeline.evaluate_day(args.day, args.market)
    g = doc["global"]
    print(f"Global: {g['status'].upper()}" + (f" - {len(g['incidents'])} incident(s)" if g["incidents"] else ""))
    if g.get("system_notice"):
        print(f"  NOTE: {g['system_notice']}")
    for code, m in doc["markets"].items():
        r = m["rating"]
        print(f"  {code}: {m['status'].upper():6} red={r['red_count']} yellow={r['yellow_count']} "
              f"site_down={len(r['site_down'])} coverage={r['coverage']}")
    return doc


def cmd_report(args) -> None:
    from . import report
    path = report.write_static(args.day)
    print(f"Report written: {path}")


def cmd_dashboard(args) -> None:
    from . import report
    path = report.write_dashboard(args.day, args.out)
    print(f"Dashboard written: {path}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="monitor", description="EU Outside-In Tracking Monitor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, market=True):
        p.add_argument("--day", default=_today(), help="run day (UTC), default today")
        if market:
            p.add_argument("--market", nargs="*", help="market codes, default all")

    p = sub.add_parser("run"); common(p)
    p.add_argument("--no-browser", action="store_true", help="only Tealium CDN + load-rule checks")
    p.add_argument("--url", nargs="*", help="only these URL ids")
    p = sub.add_parser("collect"); common(p)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--url", nargs="*")
    p = sub.add_parser("ingest"); common(p, market=False)
    p.add_argument("file")
    p = sub.add_parser("evaluate"); common(p)
    p = sub.add_parser("report"); common(p, market=False)
    p = sub.add_parser("dashboard"); common(p, market=False)
    p.add_argument("--out", required=True)
    p = sub.add_parser("forms"); common(p, market=False)
    p.add_argument("action", choices=["import"])
    p.add_argument("file")
    p.add_argument("--market", required=True)
    p = sub.add_parser("baseline"); common(p, market=False)
    p.add_argument("action", choices=["show", "reset", "adopt"])
    p.add_argument("--market", required=True)
    p.add_argument("--url", nargs="*")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        cmd_collect(args)
        args.market = args.market
        cmd_evaluate(args)
        cmd_report(args)
    elif args.cmd == "collect":
        cmd_collect(args)
    elif args.cmd == "ingest":
        payload = json.loads(open(args.file, encoding="utf-8").read())
        done = pipeline.ingest_browser_evidence(args.day, payload)
        print(f"Ingested browser evidence for: {', '.join(done)}")
    elif args.cmd == "evaluate":
        cmd_evaluate(args)
    elif args.cmd == "report":
        cmd_report(args)
    elif args.cmd == "dashboard":
        cmd_dashboard(args)
    elif args.cmd == "forms":
        import html
        from . import forms
        data = json.loads(open(args.file, encoding="utf-8").read())
        code = args.market.upper()
        for page_id, idxs in data["P"].items():
            gates = [{"id": data["G"][i][0], "ctas": [html.unescape(c) for c in data["G"][i][1]],
                      "embedded": bool(data["G"][i][2])} for i in idxs]
            forms.update_inventory(code, page_id, gates, args.day)
        inv = forms.load_inventory(code)
        print(f"{code}: {len(inv['pages'])} page(s) with forms, {len(forms.gates_in_inventory(inv))} distinct form(s)")
    elif args.cmd == "baseline":
        from . import baseline
        from .config import load_platforms
        code = args.market.upper()
        if args.action == "reset":
            baseline.reset(code, args.url)
            print(f"{code}: baseline reset for {', '.join(args.url) if args.url else 'all pages'} - it is learned again over the next 3 run days.")
        elif args.action == "adopt":
            raws = [(p.parent.name, json.loads(p.read_text(encoding="utf-8")))
                    for p in sorted(RESULTS_DIR.glob(f"raw/*/{code}.json"))]
            m = load_markets([code])[code]
            keep = {u["id"] for u in m["urls"]} | {j["id"] for j in m["journeys"]}
            b = baseline.adopt_history(code, raws, load_platforms(), keep, pipeline._main_host(m))
            print(f"{code}: as-is baseline adopted from {len(raws)} run day(s): {len(b.get('urls', {}))} page(s), "
                  f"{len(b.get('journeys', {}))} journey(s), {len(b.get('forms', {}))} form(s); "
                  f"market rule: {', '.join(b.get('market_core', {})) or 'not enough pages yet'}")
        else:
            b = baseline.load(code)
            for pid, e in sorted((b.get("urls") or {}).items()):
                print(f"{pid:55} {e.get('status'):10} {len(e.get('days', []))}d  {', '.join(sorted(e.get('post', {})))}")
            print("market rule (expected on every page):", b.get("market_core") or "-")

if __name__ == "__main__":
    sys.exit(main())
