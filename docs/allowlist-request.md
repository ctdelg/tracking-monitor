# Request: Bot-protection allowlist for the EU Tracking Monitor

**To:** sage.com Web Platform / Web Security team (cc: MarTech)
**From:** Marius Kübler, Paid Media DE
**Date:** 2026-11-14
**Priority:** Medium – needed for go-live of a daily monitoring job

---

## Summary
We are building an automated **tracking monitor** for paid media in **DE, AT, FR, ES and PT**. Every working day it opens a defined set of sage.com landing pages in a headless browser. It checks that Tealium, the OneTrust consent banner and the advertising and analytics tags work correctly.

Today, sage.com's bot protection answers these requests with **HTTP 403** on all five market homepages, including from the Sage corporate network. We are asking for a **targeted exception for this monitor only**. We do not want to work around the bot protection.

## Why we need it
- Paid media spend in the five markets depends on working conversion tracking.
- In August 2026 a Tealium change stopped the DE Floodlight conversion tag (tag 98) from firing for ecom trial/buy forms. It went unnoticed for weeks.
- A daily outside-in check would have flagged it within 24 hours.

## What the monitor does (and does not do)
| | |
|---|---|
| **Pages** | ~20–50 URLs per market (paid landing pages, product pages, form and checkout entry pages). See the attached list once finalised. |
| **Frequency** | Once per working day (Mon–Fri) at about 05:00 UTC. Manual re-runs are occasional. |
| **Volume** | About 250–500 page loads per day across all markets. Each URL is opened twice (before and after consent), plus a few multi-step journeys. |
| **Concurrency** | At most 2 parallel browser sessions, with a delay between page loads. |
| **Forms / checkout** | **Never submitted.** No leads, orders or account sign-ups are created. |
| **Tracking data** | Outgoing tracking requests (GA4, Floodlight, Google Ads, Meta, LinkedIn, Microsoft …) are **intercepted and blocked**, except on one URL per market. Those few visits are clearly marked (see below) so they can be filtered. |
| **Origin** | GitHub Actions hosted runners (Microsoft Azure IP ranges, mainly US). A self-hosted runner or EU egress may follow later. |

## Requested change (any one option is fine)
1. **Secret header (preferred):** The monitor sends a header such as `X-Sage-Monitor-Token: <secret>`. The bot-protection rule skips the challenge or block for requests with the correct value. We would store the secret in GitHub Actions secrets, and it can be rotated anytime.
2. **User-Agent token:** Allowlist requests whose User-Agent contains `SageTrackingMonitor/1.0` (less secure, because it can be copied).
3. **IP allowlist:** Not practical for GitHub-hosted runners because their IPs change. Only an option if we move to a fixed-IP runner.

The exception should only cover **www.sage.com** paths under `/de-de/`, `/de-at/`, `/fr-fr/`, `/es-es/`, `/pt-pt/` (and the checkout paths below them). It does not need to cover APIs or login areas.

## Identification of monitor traffic
- User-Agent suffix: `SageTrackingMonitor/1.0 (+contact: <your Sage email>)`
- On live-sample visits: `utm_source=tracking-monitor&utm_medium=monitoring` and click IDs prefixed with `TEST_MON_`
- MarTech can exclude this traffic in GA4 and Floodlight reporting using these markers.

## Questions for you
1. Which bot-protection product is in front of www.sage.com, and which allowlisting method do you support?
2. Who owns the rule, and what is the lead time?
3. Are there rate limits or time windows we should respect?

## Contact
Marius Kübler – Paid Media DE. After handover the tool will be operated by [UK colleague – name to be added].

Thank you!
