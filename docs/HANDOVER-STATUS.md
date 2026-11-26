# Handover status – EU Tracking Monitor

Status as of 2026-11-26. Owner today: Marius Kübler. Future operator: Carolina Torres.
The step-by-step set-up guide is in [HANDOVER.md](HANDOVER.md). This page says where we are and what is left.

## Where we are

| Area | Status |
|---|---|
| Checker (Python, `monitor/`) | Built and tested (9 regression tests pass). Covers DE, AT, FR, ES and PT. |
| Market configuration | DE 116 paid landing pages and 136 lead forms. FR 34 URLs and 49 forms. ES 11 and PT 6 URLs. AT 6 pages and 2 form journeys on www.sagedpw.at. |
| GitHub Actions | **Working since 2026-11-26.** Runs Mon–Fri at 04:17 UTC and commits its results. Before that, every scheduled run failed at the commit step (fixed). |
| Baselines | Adopted automatically from the current state (17 Nov 2026). New pages learn for 3 run days. Nothing to confirm by hand. |
| Bot protection on www.sage.com | Automated page loads from GitHub get HTTP 403 / 429. The allowlist request (`docs/allowlist-request.md`) is **not sent yet**. Until it is granted, the daily run checks only Tealium and load rules for DE, FR, ES and PT. AT (www.sagedpw.at) is fully checked. Marius has run page checks by hand on sample pages (16, 18, 19, 23 Nov). |
| Dashboard | Published as a Claude artifact in **Marius'** account. Carolina publishes her own copy on her first routine run. |
| Daily Claude routine | Prompt ready (`routine/daily-prompt.md`). **Not set up yet.** Until it is, nobody writes the daily explanation and the dashboard is not updated. |
| Email alerts | **Not built yet** (Phase 2). |
| Repository access | `github.com/kbnho/tracking-monitor`, private, in Marius' personal account. **Carolina is not a collaborator yet.** |

### Current findings (sample-page runs up to 23 Nov)
- **DE:** tag 98 (Floodlight form submit for web-shop trials and purchases) is **fixed** by a Tealium publish on 19 Nov. **Microsoft UET** sends no page view since 18 Nov: bat.js loads but never initialises (Sage Active, and on 23 Nov also Intacct). Owner: MarTech.
- **FR, ES:** web-shop purchases do not fire Floodlight (FR tag 129, ES tag 36). Same rule change as the DE fix would solve it. Owner: MarTech.
- **AT:** form conversion `sage_012` needs a button ID in the GTM trigger. AT has no Floodlight / Google Ads conversion tags.
- **FR (www.ciel.com):** no cookie banner.
- **PT:** green.

## What Marius does before handing over

1. **Add Carolina to the repository** with Write access (Settings → Collaborators). Better: transfer it to a Sage GitHub organisation or to her account, so it does not depend on a personal account.
2. **Walk Carolina through the dashboard and one finding** (DE tag 98: broken in August, found by the monitor, fixed on 19 Nov).
3. **Agree the email set-up** with Carolina and, if needed, IT (see "Email alerts" below).

## What Carolina does

### Once
1. Accept the GitHub invitation.
2. **Send the allowlist request** (`docs/allowlist-request.md`) to the sage.com IT / web security team, cc MarTech.
   When they agree a header, add it in GitHub: Settings → Secrets and variables → Actions → New secret `MONITOR_AUTH_HEADER` (format `Header-Name: secret-value`).
3. **Check what her Claude account offers.** This decides how the daily routine runs:
   - **A (preferred):** Claude Code cloud routines with a GitHub connection. Runs even when the laptop is off.
   - **B:** Claude desktop app with scheduled tasks. The laptop must be on at 06:45.
   - **C:** neither. GitHub Actions still runs every day; use the static report attached to each run and ask Claude for explanations when needed.
4. **Set up the routine** (A or B): Mon–Fri 06:45 Europe/London, prompt = everything below the line in `routine/daily-prompt.md`.
5. **Run the routine once by hand.** It publishes the dashboard as an artifact in her account. Paste that URL into `routine/daily-prompt.md` and into the routine prompt, so later runs update the same page.
6. **Share the dashboard** with Marius, the market managers and MarTech. People who should acknowledge findings need at least "Contributor" access.

### Every working day (about 10 minutes)
- 04:17 UTC GitHub runs the checks. 06:45 the routine writes the explanation and updates the dashboard. Ready before 08:00.
- Look at **red** first, then **new yellow**.
- Red: forward Claude's diagnosis to the owner it names (usually MarTech) and acknowledge the finding with the ticket reference.
- Yellow because of a Tealium publish: check with MarTech that a changed conversion tag was intended.
- "Blocked" or system notices are not tracking problems. They usually mean the allowlist header is missing or expired.

### When something changes
In Claude Code inside the repository, in plain English: "Add <URL> to FR as landing page", "Remove fr-xyz from FR", "Run the check now for DE", "Why is AT yellow?", "Re-learn the baseline for FR" (only after an intended tag change).

## What to watch out for

- **Without the allowlist, the daily run is only half useful for DE, FR, ES and PT.** It still catches Tealium rule changes (like tag 98), but not what happens on the page (cookie banner, click IDs, tags firing, UET).
- **Do not work around the bot protection** (other IP addresses, faked browsers). The request asks for an official exception.
- **The rules engine decides colours, Claude only explains them.** If a colour looks wrong, fix the configuration, not the diagnosis text. Never re-learn a baseline just to make a finding go away; acknowledge it instead.
- **Acknowledgements expire.** A finding comes back on the date chosen. Use 7 or 14 days, not "forever".
- **Check the GitHub Actions tab once a week.** A red run there means no fresh results. GitHub emails the repository owner when a scheduled run fails.
- **GitHub may start schedules late.** If the routine finds no result for today, it says so and shows the last run.
- **The checker never submits forms or checkouts** and blocks its own tracking hits, so it does not pollute reporting.
- **Do not put the allowlist header or other secrets into files or prompts.** Only in GitHub secrets.

## Email alerts (Phase 2) – what is needed

Goal: an email to the right people when a market turns red or gets a new yellow that nobody has acknowledged.

Nothing is built yet. Three things are needed:
1. **Decide the sending channel** (with IT if needed):

   | Option | How | Needs | Comment |
   |---|---|---|---|
   | 1. Claude routine sends it | Step 6 of the routine prompt uses an Outlook / Microsoft 365 connector in Carolina's Claude account | The connector must be available and allowed for unattended use | Easiest if the connector exists. Emails come from Carolina's mailbox. Only works if the routine runs. |
   | 2. Power Automate flow | GitHub Actions calls a Power Automate HTTP trigger after the run; the flow sends the email from Outlook | Power Automate with the HTTP trigger (premium connector licence) | Fits the Sage Microsoft 365 set-up. Independent of Claude. |
   | 3. SMTP from GitHub Actions | The workflow sends the email itself with a service mailbox | A service mailbox with SMTP sending allowed by IT (often switched off in Microsoft 365) | Most technical; depends on IT approval. |

   **Recommendation:** option 1 if Carolina's Claude account has an Outlook connector, otherwise option 2.
2. **Define who gets what**, in `config/markets.yaml` under `settings.email`: recipients per market (market manager, MarTech), plus a summary recipient (Carolina). Default rule: only new red or new yellow, not acknowledged, at most one email per market per day, with a link to the dashboard.
3. **Build and test it** (about half a day with Claude Code): the email text, the trigger logic based on `new_failures` and acknowledgements, and one test email to Carolina before switching on for everyone.

## Open items checklist

- [x] GitHub Actions runs green and commits results (fixed 2026-11-26).
- [x] Baselines in place for all markets (adopted 17 Nov, new pages learn automatically).
- [ ] Marius: add Carolina to the repository (or transfer it).
- [ ] Carolina: send the allowlist request; add `MONITOR_AUTH_HEADER` when granted.
- [ ] Carolina: check Claude account (variant A / B / C), set up the routine, publish and share her dashboard.
- [ ] Market owners: review URL lists, add paid-only landing pages.
- [ ] Carolina + IT: choose the email channel; then build and test email alerts.
- [ ] MarTech: fix DE Microsoft UET, FR tag 129 and ES tag 36 load rules, AT GTM trigger `sage_012`, cookie banner on www.ciel.com.
