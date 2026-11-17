# Handover status – EU Tracking Monitor

Status as of 2026-11-17. Owner today: Marius Kübler. Future operator: Carolina Torres.
The step-by-step set-up guide is in [HANDOVER.md](HANDOVER.md). This page says where we are and what is left.

## Where we are

| Area | Status |
|---|---|
| Checker (Python, `monitor/`) | Built and tested. Runs locally for all five markets (DE, AT, FR, ES, PT). |
| Market configuration | DE 116 paid landing pages and 136 lead forms. FR 34 URLs and 49 forms. AT 6 pages and 2 form journeys on www.sagedpw.at. ES and PT have smaller lists. |
| Findings | DE tag 98 (Floodlight form submit) does not fire for web-shop trials and purchases. FR tag 129 has the same rule. The same purchase check fails in DE, FR and ES. AT has no active Floodlight / Google Ads conversion tags. |
| GitHub repository | `github.com/kbnho/tracking-monitor`, private, in Marius' personal account. Workflow "Daily tracking check" is active but **has never run in GitHub yet**. All results so far were produced on Marius' laptop. |
| Dashboard | Published as a Claude artifact in **Marius'** account. Carolina will publish her own copy on her first routine run. |
| Bot protection on www.sage.com | Automated page loads get HTTP 403 / 429. The allowlist request (`docs/allowlist-request.md`) is drafted but **not sent**. Until it is granted, the daily run only checks Tealium and load rules for sage.com markets. AT (www.sagedpw.at) is fully checked. |
| Baselines | Proposals for all five markets are in `baseline/_pending/`. **None is confirmed yet**, so pages show yellow ("baseline pending"). |
| Daily Claude routine | Prompt is ready (`routine/daily-prompt.md`). Not set up yet. |
| Email alerts | **Not built yet.** Only planned (Phase 2). |

## What Marius does before handing over

1. **Add Carolina to the repository** with Write access (Settings → Collaborators).
   Better: transfer the repository to a Sage GitHub organisation or to Carolina's account, so it does not depend on a personal account.
2. **Run the workflow once by hand** (Actions → Daily tracking check → Run workflow) and check that it finishes green and commits `results/<day>.json`.
3. **Settle the open DE question:** should Microsoft UET fire on the DE payroll and HR landing pages (`/cp/payroll-*-shopping/`, `/cp/hr/*`)? Then confirm the DE baseline.
4. **Walk Carolina through the dashboard and one finding** (the DE tag 98 story is the best example).
5. **Agree the email set-up** with Carolina and, if needed, IT (see "Email alerts" below).

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
7. **Confirm the baselines** with the market owners, one market at a time. In Claude Code inside the repository: "Show me the pending baseline for FR", then "Confirm the FR baseline".

### Every working day (about 10 minutes)
- 05:00 UTC GitHub runs the checks. 06:45 the routine writes the explanation and updates the dashboard. Ready before 08:00.
- Look at **red** first, then **new yellow**.
- Red: forward Claude's diagnosis to the owner it names (usually MarTech) and acknowledge the finding with the ticket reference.
- Yellow because of a Tealium publish: check with MarTech that a changed conversion tag was intended.
- "Blocked" or system notices are not tracking problems. They usually mean the allowlist header is missing or expired.

### When something changes
In Claude Code inside the repository, in plain English: "Add <URL> to FR as landing page", "Remove fr-xyz from FR", "Run the check now for DE", "Why is AT yellow?".

## What to watch out for

- **Without the allowlist, the daily run is only half useful for DE, FR, ES and PT.** It still catches Tealium rule changes (like tag 98), but not what happens on the page (cookie banner, click IDs, tags firing).
- **Do not work around the bot protection** (other IP addresses, faked browsers). The request asks for an official exception.
- **The rules engine decides colours, Claude only explains them.** If a colour looks wrong, fix the configuration or the baseline, not the diagnosis text.
- **Acknowledgements expire.** A finding comes back on the date chosen. Use 7 or 14 days, not "forever".
- **GitHub schedules can start up to about an hour late.** If the routine finds no result for today, it says so and shows the last run. Check the Actions tab.
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

- [ ] Marius: add Carolina to the repository (or transfer it).
- [ ] Marius: first manual GitHub Actions run, green.
- [ ] Marius: decide UET on DE payroll / HR pages, confirm DE baseline.
- [ ] Carolina: send the allowlist request; add `MONITOR_AUTH_HEADER` when granted.
- [ ] Carolina: check Claude account (variant A / B / C), set up the routine, publish and share her dashboard.
- [ ] Market owners: review URL lists, add paid-only landing pages; confirm AT, FR, ES, PT baselines.
- [ ] Carolina + IT: choose the email channel; then build and test email alerts.
- [ ] MarTech: fix DE tag 98 and FR tag 129 load rules; confirm the AT conversion set-up.
