"""Rating logic (spec §6): check results -> market status -> global status."""

from __future__ import annotations

from datetime import date

GLOBAL_THRESHOLD = 3  # same check failing in >= 3 markets = global incident

STATUS_ORDER = {"green": 0, "yellow": 1, "red": 2}


def _base_id(check_id: str) -> str:
    return check_id.split(":")[0]


def ack_matches(ack: dict, market: str, check: dict, today: str) -> bool:
    if ack.get("expires") and ack["expires"] < today:
        return False
    if ack.get("market") not in (market, "*"):
        return False
    if ack.get("check") not in (check["id"], _base_id(check["id"]), "*"):
        return False
    return ack.get("target", "*") in ("*", check["target"], check["target"].split("#")[0])


def apply_acks(market: str, checks: list[dict], acks: list[dict], today: str) -> list[dict]:
    applied = []
    for c in checks:
        if c["result"] not in ("fail", "warn"):
            continue
        for a in acks:
            if ack_matches(a, market, c, today):
                c["acknowledged"] = {"by": a.get("by"), "note": a.get("note"), "since": a.get("created"),
                                     "expires": a.get("expires"), "ack_id": a.get("id")}
                applied.append(a.get("id"))
                break
    return applied


def rate_market(checks: list[dict]) -> dict:
    """Market colour from its check results (acknowledged findings are ignored)."""
    active = [c for c in checks if c["result"] in ("fail", "warn") and not c.get("acknowledged")]
    red = [c for c in active if c["severity"] == "red" and c["result"] == "fail"]
    yellow = [c for c in active if (c["severity"] == "yellow")
              or (c["severity"] == "red" and c["result"] == "warn")]
    site_down = sorted({c["target"] for c in active if c["severity"] == "site_down" and c["result"] == "fail"})
    blocked = sorted({c["target"] for c in checks if c["id"] == "BOT-01" and c["result"] == "fail"})
    page_targets = {c["target"] for c in checks if c["target"] != "market"}
    status = "red" if red else "yellow" if yellow else "green"
    coverage = "full"
    if not page_targets or (blocked and len(blocked) >= len(page_targets)):
        coverage = "tealium_only"   # every page blocked -> only CDN / load-rule checks ran
    elif blocked:
        coverage = "partial"
    return {
        "status": status,
        "red_count": len(red),
        "yellow_count": len(yellow),
        "site_down": site_down,
        "blocked_pages": blocked,
        "coverage": coverage,
        "acknowledged_count": sum(1 for c in checks if c.get("acknowledged")),
    }


def rate_global(markets: dict) -> dict:
    """markets: {code: {"checks": [...], "rating": {...}}}"""
    failing: dict[str, set] = {}
    for code, m in markets.items():
        for c in m["checks"]:
            if c["result"] == "fail" and c["severity"] in ("red", "site_down") and not c.get("acknowledged"):
                failing.setdefault(c["id"] if c["id"].startswith(("TAG:", "CONV-")) else _base_id(c["id"]), set()).add(code)
    incidents = [
        {"check": cid, "markets": sorted(codes),
         "note": "Same check fails in several markets - likely a shared cause "
                 "(shared Tealium template/extension, OneTrust configuration or vendor outage)."}
        for cid, codes in sorted(failing.items()) if len(codes) >= GLOBAL_THRESHOLD
    ]
    worst = max((m["rating"]["status"] for m in markets.values()),
                key=lambda s: STATUS_ORDER[s], default="green")
    blocked_everywhere = bool(markets) and all(m["rating"]["coverage"] == "tealium_only" for m in markets.values())
    return {
        "status": "red" if incidents else worst,
        "incidents": incidents,
        "system_notice": ("No page-level evidence for any market today: browser checks were blocked by "
                          "sage.com bot protection (allowlisting pending) or not run. Only Tealium CDN and "
                          "load-rule checks are included."
                          if blocked_everywhere else None),
    }


def today_iso() -> str:
    return date.today().isoformat()
