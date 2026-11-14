# Problem: Automated Outside-In Tracking Check (EU)

## 1. Background
- Paid media (search, social, display) for Sage in **DE, AT, FR, ES, PT** depends on working conversion tracking. The stack is Tealium iQ, OneTrust, Floodlight/Campaign Manager, GA4 and Google Ads, plus Meta, LinkedIn and Microsoft where relevant.
- The paid media team has **no access** to the Tealium or Google tag configuration. The MarTech team owns it and gives our requests low priority.
- Today, tracking errors are only noticed **reactively**, usually when conversions drop. Example from DE: a Tealium publish on 2026-08-24 stopped Floodlight tag 98 from firing on ecom trial/buy form submits. This went unnoticed for weeks.

## 2. Goal
A **daily, automated check** that tests from the outside, like a real visitor in a browser, whether tracking works on all relevant paid media URLs in the five markets. It produces a **traffic-light status per market and overall**.

## 3. Requirements

### 3.1 Functional
- **URL inventory per market:** a maintainable list of relevant URLs (paid landing pages, product pages, form/trial pages, checkout entry). Each URL has a type and expected tags.
- **Outside-in checks per URL**, for example:
  - Page is reachable (HTTP status, redirects, no 404)
  - Tealium `utag.js` loads (correct profile/environment, version/publish date)
  - Consent banner (OneTrust) is present
  - Tags are blocked before consent and active after consent
  - Expected pageview and remarketing tags fire (GA4, Floodlight pageview, Google Ads, other pixels)
  - Click IDs (gclid, msclkid, UTM parameters) survive into the form or checkout (cookies such as `_gcl_aw`)
  - Optional/later: conversion events (form submit, trial start) via a test environment, simulation or offline load-rule evaluation
  - **Change detection:** diff of the current `utag.js` against the previous day. New or changed tags and load rules are reported even if nothing is broken yet.
- **Rating / traffic light:**
  - 🟢 **Green:** all checks for a market pass
  - 🟡 **Yellow:** minor issues on individual pages, for example an optional pixel is missing or change detection raised a warning
  - 🔴 **Red:** severe issues, for example a conversion tag does not fire, `utag.js` is missing, consent is broken or a landing page is down
  - **Overall status:** also rated across markets. An error in all markets points to a global cause, such as a shared Tealium template or OneTrust.
- **Report / dashboard:** updated daily. It shows:
  - an overview with a traffic light per market
  - a drill-down per URL and check
  - a plain-language error description, including the likely cause
  - a history, so it is clear how long something has been red
  - optional notifications on yellow or red (e.g. email or Teams)

### 3.2 Non-functional
- **Fully automated, daily**, with no manual steps.
- **Transferable:** the solution must be importable into, and activatable in, a **colleague's Claude company account**. It must run without the builder's machine, accounts or local paths.
- **Platform-independent / portable:** the core logic (checks, rating, report) must not only run in Claude. In theory it must also run as a standalone web app or in a comparable environment, for example:
  - a server or cloud function with a scheduler
  - a CI pipeline such as GitHub Actions or Azure DevOps
  - internal dashboard hosting

  Claude is one possible runtime, not a hard dependency.
- **Maintainable by non-developers:** URLs, expected tags and thresholds live in a simple configuration file.
- **Robust and reproducible:** the same inputs give the same result. Retries and timeouts prevent false alarms from flaky runs.
- **Compliance:**
  - Consent is accepted in the test browser for testing only.
  - No real form data or leads are submitted.
  - Production conversions are not distorted.
- **Documentation and demo** for the handover: how it works, how to configure it, how to read the traffic lights, and troubleshooting.

## 4. Possible approaches (for discussion)
| Approach | Description | Pros | Cons |
|---|---|---|---|
| A. Claude agent only | A scheduled Claude task opens the URLs in a browser daily and rates them | quick to build, flexible | costly per run, less deterministic, browser access in cloud runs unclear, not portable |
| B. Script + scheduler | A headless browser script (e.g. Playwright) inspects network requests and builds an HTML dashboard | deterministic, cheap, portable | needs a runtime and hosting; not directly transferable into a Claude account |
| **C. Hybrid (preferred)** | A deterministic check script writes JSON results. A scheduled Claude task interprets deviations, writes the plain-language report and updates a dashboard (e.g. a Claude artifact). It is packaged as a skill/plugin for handover. The same script can run without Claude in a web app or CI | reproducible checks plus AI diagnosis, easy to hand over, portable | somewhat more initial effort |
| D. Commercial tool | ObservePoint, Trackingplan or similar | ready-made, robust | licence cost, procurement, no Claude integration |

## 5. Open questions
1. **URL inventory:** Who provides the relevant URLs per market? Are there Google Ads/SA360/Meta final-URL exports we can pull automatically?
2. **Platforms:** Which tags are "critical" (red) and which are "optional" (yellow) per market? Are Meta, LinkedIn and Microsoft Ads relevant?
3. **Conversion checks:** Are pageview, consent and click-ID persistence enough? Or do conversion events need checking (test form, test environment, offline load-rule evaluation)?
4. **Tealium setup:** Does each market have its own profile (`de-de`, `de-at`, `fr-fr`, `es-es`, `pt-pt`) or a shared template? This matters for the global vs. local rating.
5. **Colleague's runtime:**
   - Which Claude features does the company account have (Claude Code desktop scheduled tasks, cloud routines, artifacts, connectors)?
   - Does the check run on her machine, which must be switched on, or in the cloud?
   - May Python/Node be installed?
   - Is there a GitHub repo?
6. **Report channel:** Is a dashboard (artifact) enough, or is a daily email/Teams message needed too? To whom?
7. **Time and frequency:** What time each day? Immediate alert on red?
8. **History:** How long should results be kept (trend, "red since")?

> The open questions above were resolved in the interview of 2026-11-14. The decisions are recorded in `spec.md`.

## 6. Success criteria
- A break like the tag-98 issue would have shown up **within 24 hours**, as red or at least as yellow with a change notice.
- After the handover the colleague can run the check **on her own**, maintain URLs and read the report.
- The false-alarm rate is low enough that red is taken seriously.
