"""Playwright evidence collection (headless Chromium).

Per URL: fresh browser context -> load page with synthetic click IDs -> snapshot
before consent -> click "Accept all" -> snapshot after consent.

Tracking hits are captured from Playwright's request log and then aborted
("capture and block"), except for URLs marked live_sample: true.

If sage.com answers with 403 (bot protection), the visit is marked "blocked".
That is a system status, not a tracking failure. The monitor never tries to
disguise itself; access must be granted via the allowlist header
(env MONITOR_AUTH_HEADER, see docs/HANDOVER.md).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from playwright.sync_api import Browser, BrowserContext, Page

from . import USER_AGENT_SUFFIX
from .config import Platforms

COLLECTOR_JS = (Path(__file__).parent / "collector.js").read_text(encoding="utf-8")
NAV_TIMEOUT_MS = 45_000
SETTLE_MS = 5_000
POST_CONSENT_MS = 8_000


def click_ids(day: str) -> dict:
    token = f"TEST_MON_{day.replace('-', '')}"
    return {"gclid": token, "msclkid": token, "fbclid": token}


def with_params(url: str, params: dict) -> str:
    parts = urlsplit(url)
    q = parts.query + ("&" if parts.query else "") + urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


def _auth_header() -> dict:
    """Optional allowlist header for sage.com, from env 'Header-Name: value'."""
    raw = os.environ.get("MONITOR_AUTH_HEADER", "").strip()
    if ":" not in raw:
        return {}
    name, value = raw.split(":", 1)
    return {name.strip(): value.strip()}


class Recorder:
    """Records every request; aborts tracking hits unless live mode."""

    def __init__(self, platforms: Platforms, live: bool):
        self.platforms = platforms
        self.live = live
        self.requests: list[dict] = []
        self.auth = _auth_header()

    def handle(self, route):
        req = route.request
        url = req.url
        self.requests.append({"url": url, "type": req.resource_type})
        host = urlparse(url).hostname or ""
        is_hit = self.platforms.match(url) is not None or (
            not self.platforms.is_ignored_host(host)
            and req.resource_type in self.platforms.discovery_types
            and not host.endswith("sage.com"))
        if is_hit and not self.live:
            route.abort()
            return
        if self.auth and host.endswith("sage.com"):
            route.continue_(headers={**req.headers, **self.auth})
            return
        route.continue_()

    def take(self) -> list[dict]:
        out, self.requests = self.requests, []
        return out


_DEFAULT_UA: str | None = None


def _default_ua(browser: Browser) -> str:
    """The browser's own, unmodified user agent (we only append our identifier)."""
    global _DEFAULT_UA
    if _DEFAULT_UA is None:
        tmp = browser.new_context()
        _DEFAULT_UA = tmp.new_page().evaluate("() => navigator.userAgent")
        tmp.close()
    return _DEFAULT_UA


def new_context(browser: Browser, locale: str) -> BrowserContext:
    ua = _default_ua(browser)
    ctx = browser.new_context(locale=locale, user_agent=f"{ua} {USER_AGENT_SUFFIX}",
                              viewport={"width": 1366, "height": 900})
    ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    return ctx


def _snapshot(page: Page, requests: list[dict]) -> dict:
    page.evaluate(COLLECTOR_JS)
    snap = page.evaluate("() => window.__tm.snapshot()")
    snap["requests"] = requests  # Playwright log is authoritative (includes aborted hits)
    return snap


def _is_blocked(status: int | None, page: Page) -> bool:
    if status in (403, 429):
        return True
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        title = ""
    return any(k in title for k in ("access denied", "attention required", "just a moment"))


def visit_url(browser: Browser, market: dict, entry: dict, platforms: Platforms, day: str,
              locale: str) -> dict:
    ids = click_ids(day)
    params = {**ids, "utm_source": "tracking-monitor", "utm_medium": "monitoring"}
    url = with_params(entry["url"], params)
    rec = Recorder(platforms, live=bool(entry.get("live_sample")))
    visit = {"id": entry["id"], "url": entry["url"], "type": entry.get("type", "page"),
             "click_ids": ids, "live_sample": rec.live, "status": None, "final_url": None,
             "error": None, "blocked": False, "pre": None, "post": None}
    ctx = new_context(browser, locale)
    try:
        ctx.route("**/*", rec.handle)
        page = ctx.new_page()
        resp = page.goto(url, wait_until="load")
        visit["status"] = resp.status if resp else None
        visit["final_url"] = page.url
        if _is_blocked(visit["status"], page):
            visit["blocked"] = True
            return visit
        page.wait_for_timeout(SETTLE_MS)
        visit["pre"] = _snapshot(page, rec.take())
        btn = page.locator("#onetrust-accept-btn-handler")
        accepted = False
        if btn.count():
            try:
                btn.first.click(timeout=5000)
                accepted = True
            except Exception:  # noqa: BLE001
                accepted = False
        page.wait_for_timeout(POST_CONSENT_MS)
        visit["post"] = _snapshot(page, rec.take())
        visit["post"]["accepted"] = accepted
    except Exception as e:  # noqa: BLE001
        visit["error"] = str(e)[:500]
    finally:
        ctx.close()
    return visit


def run_journey(browser: Browser, market: dict, journey: dict, platforms: Platforms, day: str,
                locale: str) -> dict:
    """Multi-step journey after consent. Steps: goto / click / expect_url. Never submits."""
    ids = click_ids(day)
    rec = Recorder(platforms, live=False)
    out = {"id": journey["id"], "name": journey.get("name", journey["id"]), "click_ids": ids,
           "steps": [], "blocked": False}
    ctx = new_context(browser, locale)
    try:
        ctx.route("**/*", rec.handle)
        page = ctx.new_page()
        first = True
        for step in journey["steps"]:
            entry = {"step": step, "error": None, "snapshot": None, "status": None}
            try:
                if "goto" in step:
                    target = step["goto"]
                    if first:
                        target = with_params(target, {**ids, "utm_source": "tracking-monitor",
                                                      "utm_medium": "monitoring"})
                    resp = page.goto(target, wait_until="load")
                    entry["status"] = resp.status if resp else None
                    if _is_blocked(entry["status"], page):
                        out["blocked"] = True
                        break
                    if first:
                        page.wait_for_timeout(SETTLE_MS)
                        btn = page.locator("#onetrust-accept-btn-handler")
                        if btn.count():
                            btn.first.click(timeout=5000)
                    first = False
                elif "click" in step:
                    page.locator(step["click"]).first.click(timeout=15_000)
                    page.wait_for_load_state("load")
                if "expect_url" in step and step["expect_url"] not in page.url:
                    raise RuntimeError(f"expected URL containing {step['expect_url']}, got {page.url}")
                page.wait_for_timeout(POST_CONSENT_MS)
                entry["snapshot"] = _snapshot(page, rec.take())
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)[:300]
                out["steps"].append(entry)
                break
            out["steps"].append(entry)
    finally:
        ctx.close()
    return out


def politeness_pause():
    time.sleep(1.5)
