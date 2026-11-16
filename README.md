# EU Tracking Monitor

Every working day, this tool checks that **paid media tracking works** on the websites our campaigns
send traffic to in **Germany (DE), Austria (AT), France (FR), Spain (ES) and Portugal (PT)**. It works
from the outside, like a visitor. No access to Tealium, Google Tag Manager or the ad platforms is needed.
The result is a traffic light per market on a dashboard, with a plain-English explanation of anything
that is wrong.

## Why it exists

Google Ads, Microsoft Ads, Meta, LinkedIn and the other platforms only bid well if they get our
conversions (demo requests, trials, downloads, purchases). When tracking breaks, campaigns keep spending
but the platforms stop learning. Usually somebody only notices weeks later, when the numbers drop.

A real example: on 24 August 2026 a change in Tealium stopped the main German Floodlight conversion tag
(tag 98) from firing for web-shop trials and purchases. Nobody noticed for weeks. This monitor would
have shown Germany as red the next morning, and a test in `tests/` proves it.

## The traffic light

| Status | What it means | Typical examples |
|---|---|---|
| 🔴 **Red** | Paid media measurement is broken. Act today. | A conversion tag would not fire when a form is sent. The click ID from an ad (gclid / msclkid) is lost. Tags fire before the visitor has agreed to cookies. |
| 🟡 **Yellow** | Something secondary is wrong, or something needs a look. | A Meta or LinkedIn pixel is missing. A landing page redirects to the homepage. Someone changed the tag setup in a way that touches conversion tags. |
| 🟢 **Green** | Everything that was checked works. | |
| ⚫ **Site down** | A page or the tag manager could not be loaded. Shown separately from the colour. | A landing page returns "not found". |
| 🔴 **Global incident** | The same problem appears in 3 or more markets at once. | Points to a shared cause, such as the cookie banner or a shared tag template. |

A finding that someone is already handling can be **acknowledged** on the dashboard (for example
"MarTech ticket raised"). It then stops counting towards the colour until the chosen date.

## What exactly is checked

The monitor answers these questions for every market:

| # | Question | How the monitor finds out |
|---|---|---|
| 1 | **Do the landing pages load?** | It opens every paid landing page from the campaign reports and notes errors and redirects (for example an expired page that sends visitors to the homepage). |
| 2 | **Does the tag manager load?** | It checks that Tealium (sage.com) or Google Tag Manager (sagedpw.at) loads, and that it is the right setup for the market. |
| 3 | **Does the cookie banner work?** | Before the visitor agrees, **no** advertising tag may fire and no advertising cookie may be set. After "Accept all", the consent must be stored. |
| 4 | **Do all ad and analytics tags fire?** | After "Accept all" it records which platforms receive a page view: Floodlight, Google Ads, GA4, Microsoft UET, Meta, LinkedIn, TikTok and others. It compares this with the agreed list for that page (the "baseline"). |
| 5 | **Is the click ID kept?** | It arrives with a test click ID (`gclid`, `msclkid`, `fbclid`, all starting with `TEST_MON_`) and checks that it is stored and passed on to the ad tags. |
| 6 | **Do conversions fire?** | It reads the live tag rules and replays a form submission or web-shop trial/purchase "in a sandbox", without sending anything. Then it checks which conversion tags would fire. This is the check that would have caught the tag-98 break. |
| 7 | **Do the lead forms work?** | It finds every demo, product tour, download, quote and contact form behind the CTAs on each landing page. It checks that each form is active and that sending it would reach Floodlight and the other platforms (UET, LinkedIn, Meta, TikTok …). |
| 8 | **Does the journey work?** | It follows the path a visitor takes, for example landing page → product tour page or landing page → contact form. It checks that the click ID and the tags survive along the way. It stops before anything is sent. |
| 9 | **Did someone change the tag setup?** | Every day it compares the published Tealium and Google Tag Manager setup with the day before. Changes are listed on the dashboard. If a conversion tag was touched, the market turns yellow. |

### What the monitor never does

- It **never sends a form**, starts a checkout or creates a lead, order or account.
- It **blocks its own tracking hits**, so it does not add fake visits or conversions to GA4, Floodlight or
  the ad platforms. The only exception is one marked sample page per market, used to confirm that the platforms
  really receive data. Those visits carry `utm_source=tracking-monitor` and click IDs starting with
  `TEST_MON_`, so they can be filtered out.
- It never tries to get around the website's bot protection. Where a site blocks it, the monitor reports
  "blocked" and waits for an official exception (see "Current status").

## How a daily run works

1. **05:00 UTC, Monday to Friday:** a scheduled job on GitHub runs the checks above for all five markets.
   It saves the results in this repository.
2. **About 06:45:** a Claude routine reads the results. It writes a short explanation of what is wrong, why
   it is likely wrong and who should fix it, then updates the dashboard.
3. **During the day:** the team looks at red first, then at new yellow findings, and acknowledges what
   is already being handled.

The checks and the colours are decided by fixed rules in the code (`monitor/`), not by AI. Claude only
explains the results. The checker would also run without Claude, for example on a server or in a future
web app.

## Markets and sites

| Market | Website | Tag manager | Cookie banner | Landing pages | Lead forms |
|---|---|---|---|---|---|
| DE | www.sage.com/de-de/ | Tealium | OneTrust | 116 (paid media report) + 10 product tour pages | 136 forms on 99 pages |
| AT | **www.sagedpw.at** (Sage DPW, HR software only) | Google Tag Manager | Usercentrics | 6 (paid search report) + 2 form journeys | Infopaket and contact form pages |
| FR | www.sage.com/fr-fr/ | Tealium | OneTrust | 24 (first proposal from the sitemap) | not yet inventoried |
| ES | www.sage.com/es-es/ | Tealium | OneTrust | 22 (first proposal from the sitemap) | not yet inventoried |
| PT | www.sage.com/pt-pt/ | Tealium | OneTrust | 20 (first proposal from the sitemap) | not yet inventoried |

## Current status (16 Nov 2026)

**What already runs fully automated every day**
- **AT** (www.sagedpw.at): all checks, including page visits and form journeys. The site has no bot protection.
- **DE, FR, ES, PT** (www.sage.com): tag rule checks, conversion replays, lead form checks and change detection.

**What is still blocked: page visits on www.sage.com**
- sage.com's bot protection blocks the automated browser (it answers "403 Forbidden", even from the Sage
  network). Until there is an exception, these pages show as "blocked". That is a system status, not a
  tracking error. Page checks are collected by hand in the Claude desktop browser for a few sample pages.
- **The exception still has to be requested.** The request is drafted in `docs/allowlist-request.md` and
  **has not been sent yet**. Next step: send it to the sage.com web / security team (cc MarTech).

**Other open items**
- [ ] Send the allowlist request (`docs/allowlist-request.md`). Once granted, add the agreed header as the GitHub
      secret `MONITOR_AUTH_HEADER`.
- [ ] Confirm the tag baselines for DE and AT, then for FR, ES and PT. Until a baseline is confirmed, that
      market shows yellow.
- [ ] DE: clarify whether Microsoft UET should fire on the payroll and HR landing pages (it currently does not).
- [ ] AT: clarify whether the missing Google Ads remarketing, UET, LinkedIn and Meta tags on sagedpw.at are intended.
- [ ] FR, ES, PT: replace the sitemap proposals with the paid media landing page reports, then inventory their forms.
- [ ] Phase 2: email alerts for new red and yellow findings.

## Where to look

- **Dashboard:** the "EU Tracking Monitor" artifact in Claude (link from the operator). It shows the
  traffic lights, each finding with its explanation, the pages, the tag setup changes and the history.
- **Results in this repository:** `results/<day>.json` (all details) and `report/index.html` (a simple version
  of the dashboard, also attached to every GitHub run).

## Short glossary

| Term | Meaning |
|---|---|
| **Tag** | A small piece of code on the website that tells an ad or analytics platform that something happened (a page view, a form sent). |
| **Tag manager** | The tool that decides which tags run when: Tealium on sage.com, Google Tag Manager on sagedpw.at. |
| **Floodlight** | Google's conversion tags (Campaign Manager 360). Google Ads and SA360 bid on them. |
| **Click ID** (gclid, msclkid, fbclid) | The ID an ad click adds to the URL. Without it, a later conversion cannot be credited to the ad. |
| **Consent** | The visitor's choice in the cookie banner. Advertising tags may only run after "Accept". |
| **Baseline** | The agreed list of tags that should fire on a page or form. The monitor reports differences from it. |
| **Acknowledge** | Mark a finding as "being handled" so it stops affecting the colour for a while. |

---

## For maintainers

### Quick start (local)

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m monitor run --no-browser        # tag rules, conversion replays, forms, change detection
python -m monitor run --market AT         # full run for one market
python -m unittest discover tests         # regression tests incl. the tag-98 replay
```

Day-to-day changes ("add this URL to FR", "why is DE red?", "confirm the AT baseline") are easiest with the
Claude skill in `.claude/skills/tracking-monitor/`, which loads automatically in this repository.

### Repository map

| Path | What |
|---|---|
| `config/markets.yaml` | Markets, sites, landing pages, journeys, conversion events. Edit this to change what is checked. |
| `config/platforms.yaml` | How each platform's hits are recognised, and how serious a missing hit is |
| `config/forms/<MKT>.json` | Which lead forms (demo, product tour, download …) sit on which page |
| `config/acks.json` | Acknowledged findings (mirrored from the dashboard) |
| `baseline/` | Confirmed expected tags per page, form and conversion event; `_pending/` holds proposals |
| `monitor/` | The checker (`checks.py` holds the check catalogue) |
| `results/` | Daily results, history, Tealium and GTM snapshots, Claude's explanations |
| `.github/workflows/daily.yml` | Scheduled run plus a manual "Run workflow" button |
| `routine/daily-prompt.md` | Prompt for the daily Claude routine |
| `docs/` | Handover guide, troubleshooting, allowlist request, specification, problem statement |

See `docs/HANDOVER.md` to set it up in another account, `docs/spec.md` for the full specification and
`docs/problem.md` for the original problem statement.
