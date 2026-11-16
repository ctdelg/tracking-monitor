# Request: Bot-protection exception for the EU Tracking Monitor

| | |
|---|---|
| **Status** | DRAFT – not sent yet |
| **To** | Sage IT / web security team responsible for the bot protection on www.sage.com (cc: MarTech) |
| **From** | Marius Kübler, Paid Media DE |
| **Priority** | Medium – needed to switch on the daily page checks for DE, FR, ES and PT |

---

## Summary
Paid Media runs an automated **tracking monitor** for our European markets. Every working day it opens the
landing pages our paid campaigns link to and checks that the cookie banner, Tealium and the advertising and
analytics tags work. It does this the way a visitor would, in a headless browser.

On **www.sage.com** the bot protection answers these page loads with **HTTP 403**, even from the Sage
network. After a burst of requests it also answers **HTTP 429** (rate limit). We are asking for a **targeted
exception for this monitor only**. We do not want to work around the bot protection.

The Austrian market is not affected: its campaigns link to www.sagedpw.at, which the monitor can already check.

## Why we need it
- Paid media spend depends on conversion tracking. When it breaks, campaigns keep spending but the ad
  platforms stop learning.
- In August 2026 a Tealium change stopped the main German Floodlight conversion tag from firing for web-shop
  trials and purchases. It went unnoticed for weeks.
- The monitor already checks the tag rules every day without touching www.sage.com. It cannot check what
  really happens on the pages (cookie banner, tags, click IDs, product tour pages) until it is allowed in.

## What the monitor does (and does not do)
| | |
|---|---|
| **Site and paths** | www.sage.com, only under `/de-de/`, `/fr-fr/`, `/es-es/` and `/pt-pt/` |
| **Pages** | About 200 pages in total: 116 paid landing pages and 10 product tour pages in DE, plus about 20–25 landing pages each in FR, ES and PT |
| **Frequency** | Once per working day (Mon–Fri), starting about 05:00 UTC. Occasional manual re-runs. |
| **Volume** | About 200 page loads per run, plus a few short click paths (landing page → form page). Each page is loaded once. In addition, light `HEAD` requests check that product tour pages and download files behind forms still exist. |
| **Pace** | One browser session at a time, pages loaded one after another with a pause between them. A full run takes about 20–30 minutes. |
| **Forms / checkout** | **Never submitted.** No leads, orders or accounts are created. |
| **Tracking data** | The monitor blocks its own requests to GA4, Floodlight, Google Ads, Meta, LinkedIn, Microsoft and other platforms. The exception is one marked page per market (see below), so there is no impact on reporting. |
| **Origin** | GitHub Actions hosted runners (Microsoft Azure IP ranges, changing IPs, mainly US). A fixed-IP or EU runner may follow later. |

## Requested change (any one option is fine)
1. **Secret header (preferred):** The monitor sends a header such as `X-Sage-Monitor-Token: <secret>`. The
   bot-protection rule lets requests with the correct value through without a challenge or block, and without
   the burst rate limit. We would keep the secret in GitHub's encrypted secrets and can rotate it at any time.
2. **User-Agent token:** Let through requests whose User-Agent contains `SageTrackingMonitor/1.0`. This is
   simpler, but less safe because anyone could copy it.
3. **IP allowlist:** Only possible if we move to a runner with a fixed IP address. Today's GitHub runners change IPs.

The exception only needs to cover page loads under the four paths above. It does not need to cover APIs,
login areas or the shop backend.

## How to recognise the monitor's traffic
- User-Agent: the normal Chromium User-Agent plus `SageTrackingMonitor/1.0`
- Landing page URLs carry `utm_source=tracking-monitor&utm_medium=monitoring`
- Test click IDs start with `TEST_MON_` (for example `gclid=TEST_MON_20261117`)
- MarTech can use these markers to exclude the few live-sample visits from GA4 and Floodlight reporting.

## Questions for you
1. Which bot-protection product is in front of www.sage.com, and which of the options above does it support?
2. Who owns the rule, and how long does a change usually take?
3. Are there time windows or a request rate we should keep to?

## Contact
Marius Kübler – Paid Media DE (<your Sage email>). After handover the monitor will be run by
[UK colleague – name to be added].

Thank you!
