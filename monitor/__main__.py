"""Command line interface.

    python -m monitor run [--market DE FR] [--no-browser]      collect + evaluate + report
    python -m monitor collect [--market ..] [--url ID ..] [--no-browser]
    python -m monitor ingest evidence.json [--day YYYY-MM-DD]   evidence from the Claude browser
    python -m monitor evaluate [--day ..]
    python -m monitor baseline propose --market DE [--url ID ..] [--day ..]
    python -m monitor baseline confirm --market DE --by "Name"
    python -m monitor report [--day ..]                         static HTML (fallback dashboard)
    python -m monitor dashboard [--day ..] --out FILE           dashboard page for the Claude artifact
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
                print(f"[{code}] Tealium CDN + load rules ...", flush=True)
                pipeline.store_raw(args.day, code, tealium_part=pipeline.collect_tealium(browser, m, args.day))
                if not args.no_browser:
                    print(f"[{code}] browser checks ({len(m['urls'])} URLs, {len(m['journeys'])} journeys) ...",
                          flush=True)
                    part = pipeline.collect_browser(browser, m, args.day, args.url)
                    blocked = sum(1 for v in part["visits"] if v.get("blocked"))
                    if blocked:
                        print(f"[{code}]   {blocked} page(s) blocked by bot protection", flush=True)
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
    p = sub.add_parser("baseline"); common(p, market=False)
    p.add_argument("action", choices=["propose", "confirm"])
    p.add_argument("--market", required=True)
    p.add_argument("--url", nargs="*")
    p.add_argument("--by", default="unknown")

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
    elif args.cmd == "baseline":
        code = args.market.upper()
        if args.action == "propose":
            prop = pipeline.propose_baseline(args.day, code, args.url)
            print(f"Proposed baseline for {code}: {len(prop['urls'])} page(s), "
                  f"{len(prop['journeys'])} journey(s), conversion events: {list(prop['conversion'])}")
            print("Review baseline/_pending/%s.json, then: python -m monitor baseline confirm --market %s --by NAME"
                  % (code, code))
        else:
            pipeline.confirm_baseline(code, args.by)
            print(f"Baseline for {code} confirmed by {args.by}.")


if __name__ == "__main__":
    sys.exit(main())
