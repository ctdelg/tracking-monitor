"""Offline load-rule evaluation (check CONV-01).

Runs the real utag.js in an isolated headless browser page that has NO network
access: every request is aborted, and the page itself is served locally. Then
it replays a conversion event payload through Tealium's own extension and
load-rule code and reports which tags would load. No request ever reaches
sage.com or any vendor, so this cannot be blocked and creates no data.
"""

from __future__ import annotations

from urllib.parse import quote

from playwright.sync_api import Browser

SANDBOX_HTML = "<!doctype html><html><head><title>sandbox</title></head><body></body></html>"

# All consent groups granted, so consent-based load rules evaluate as for an opted-in user.
CONSENT_COOKIE = ("isGpcEnabled=0&datestamp=&version=202609.2.0&isIABGlobal=false&hosts=&"
                  "interactionCount=1&isAnonUser=1&landingPath=NotLandingPage&"
                  "groups=" + quote("C0001:1,C0002:1,C0003:1,C0004:1"))

EVAL_JS = """
(args) => {
  const out = {ok: !!(window.utag && utag.loader && utag.loader.loadrules), results: []};
  if (!out.ok) return out;
  for (const ev of args.events) {
    const b = Object.assign({}, utag.data || {}, {'ut.event': 'link'}, ev.payload);
    const errors = [];
    try { utag.handler.RE('link', b, 'blr'); } catch (e) { errors.push('blr: ' + e.message); }
    const cond = {};
    for (const k in utag.cond) cond[k] = false;
    try { utag.loader.loadrules(b, cond); } catch (e) { errors.push('loadrules: ' + e.message); }
    const savedCond = utag.cond, savedCfg = utag.loader.cfg;
    let cfg = {};
    try { utag.cond = cond; utag.loader.initcfg(); cfg = utag.loader.cfg; }
    catch (e) { errors.push('initcfg: ' + e.message); }
    finally { utag.cond = savedCond; utag.loader.cfg = savedCfg; }
    const fired = Object.keys(cfg).filter(id => cfg[id].load && cfg[id].send);
    out.results.push({
      name: ev.name,
      fired: fired,
      true_rules: Object.keys(cond).filter(k => cond[k]),
      derived: Object.fromEntries(Object.entries(b).filter(([k]) => !(k in ev.payload) && /lead|conversion|form|gate|action|event/i.test(k)).slice(0, 40)),
      errors: errors,
    });
  }
  return out;
}
"""


def evaluate(browser: Browser, utag_body: str, profile: str, events: list[dict],
             path_hint: str | None = None) -> dict:
    """Evaluate conversion events against a utag.js body.

    events: [{"name": "ecom_try", "payload": {...}}]
    Returns {"ok": bool, "results": [{"name", "fired": [tag ids], "true_rules", "errors"}]}.
    """
    page_url = f"https://www.sage.com/{profile}/{path_hint or 'tracking-monitor-sandbox/'}"
    ctx = browser.new_context()
    try:
        ctx.add_cookies([
            {"name": "OptanonConsent", "value": CONSENT_COOKIE, "url": "https://www.sage.com/"},
            {"name": "OptanonAlertBoxClosed", "value": "2026-01-01T00:00:00.000Z", "url": "https://www.sage.com/"},
        ])

        def handle(route):
            if route.request.url == page_url:
                route.fulfill(status=200, content_type="text/html", body=SANDBOX_HTML)
            else:
                route.abort()  # strict sandbox: nothing leaves the machine

        ctx.route("**/*", handle)
        page = ctx.new_page()
        page.goto(page_url)
        # Globals that sage.com pages define before utag.js loads.
        page.evaluate("""() => {
            window.utag_data = window.utag_data || {};
            window.getCookie = window.getCookie || function (n) {
                const m = document.cookie.match('(^|;\\\\s*)' + n + '=([^;]*)');
                return m ? decodeURIComponent(m[2]) : undefined;
            };
        }""")
        page.add_script_tag(content=utag_body)
        page.wait_for_timeout(500)
        # utag.loader.GET defines the extensions and tag config; on a live page it runs on
        # DOM ready. In the sandbox we call it explicitly if it has not run yet.
        page.evaluate("() => { if (window.utag && typeof utag.loader.initcfg !== 'function' && utag.loader.GET) { try { utag.loader.GET(); } catch (e) {} } }")
        return page.evaluate(EVAL_JS, {"events": events})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "results": []}
    finally:
        ctx.close()
