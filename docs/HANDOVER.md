# Handover guide

How to take over the EU Tracking Monitor in your own accounts, and how to demo it.
Estimated set-up time: 30–45 minutes, with one sitting together.

## What you get
- A private GitHub repository with the checker, its configuration and all results so far.
- A GitHub Actions workflow that runs the checks every working day at 05:00 UTC.
- A Claude routine prompt (`routine/daily-prompt.md`) that explains results and publishes the dashboard.
- A Claude skill (`.claude/skills/tracking-monitor/`) for day-to-day operation in plain English.

## 1. Access (Marius)
1. Invite the colleague to the GitHub repository as a collaborator with **Write** access
   (Settings → Collaborators → Add people).
2. Optional later: transfer the repository to the colleague or a Sage GitHub organisation
   (Settings → Danger zone → Transfer). Secrets and workflow history move with it.

## 2. GitHub settings (once)
1. **Actions → General → Workflow permissions:** "Read and write permissions". The workflow commits results.
2. **Secrets and variables → Actions → New repository secret:** `MONITOR_AUTH_HEADER`. Add it once the
   sage.com web team has agreed an allowlist header (format `Header-Name: secret-value`). Until then,
   leave it unset: browser checks report "blocked" and only Tealium and load-rule checks count.
3. **Actions → Daily tracking check → Run workflow** once, to confirm it runs green.

## 3. Claude (colleague's company account)
Check first which of these the account offers (Settings / Claude Code). This decides the set-up variant:

| Available | Variant |
|---|---|
| Claude Code cloud routines + GitHub connection | **A (default):** routine in the cloud, runs even when the laptop is off |
| Claude Code desktop app with scheduled tasks | **B:** same prompt as a scheduled task on the laptop (it must be on at 06:45) |
| Neither | **C:** GitHub Actions only. Use the static report (`report/index.html`, attached to every run) and ask Claude for explanations on demand |

Variant A or B:
1. Connect GitHub to Claude Code and open the repository.
2. The skill in `.claude/skills/tracking-monitor/` loads automatically in this repository. Try it:
   "Why is DE red?"
3. Create the routine or scheduled task: Mon–Fri 06:45 (Europe/London), prompt = everything below the
   line in `routine/daily-prompt.md`.
4. Run it once by hand. On the first run it publishes the dashboard as an artifact in **your** account.
   Paste that artifact URL into `routine/daily-prompt.md` (and the routine prompt) so later runs update
   the same page.
5. Share the dashboard (Share menu on the artifact) with the market managers, Marius and MarTech.
   People who should acknowledge findings need at least "Contributor" access.

## 4. Baselines (nothing to confirm)
The monitor learns which tags belong on each page by itself: the current state was adopted on 17 Nov 2026,
and new pages learn for their first 3 run days. A tag that fires on most pages of a market is expected on all
of them. To see what was learned: "Show me the baseline for DE". After an intended tag change:
"Re-learn the baseline for <page or market>".

## 5. Demo script (30 minutes)
1. **Why (3 min):** the DE tag-98 story. Nobody noticed for weeks. Show `tests/test_monitor.py`: the monitor
   replays the old and the new utag.js and would have turned DE red the next morning.
2. **Dashboard tour (8 min):**
   - The overall status pill and the five market tiles (colour, red/yellow counts, "red since", coverage, new publish).
   - Click DE and walk through a finding: title, detail, Claude's diagnosis and the evidence.
   - The pages matrix, the Tealium publishes panel and the history strip.
3. **Acknowledge (3 min):**
   - Click "Acknowledge" on a finding, enter a note ("MarTech ticket raised") and choose "7 days".
   - The tile colour updates.
   - Withdraw it again.
4. **Maintain (8 min)**, in Claude Code inside the repository:
   - "Add https://www.sage.com/fr-fr/... to FR as landing page"
   - "Run the check now for FR"
   - "Why is AT yellow?"
5. **Daily rhythm (5 min):**
   - The check runs at 05:00 UTC and the routine at 06:45.
   - The dashboard is ready before 08:00.
   - Look at red first, then new yellow. Acknowledge what is being handled.
6. **Questions (3 min).**

## 6. Daily operation
- **Red:** forward the diagnosis to the owner it names (usually MarTech for Tealium issues) and acknowledge
  the finding with the ticket reference.
- **Yellow because of a publish:** read the publish summary. If a conversion tag changed, confirm with
  MarTech that it was intended.
- **Site down:** check the page in a browser. If it is gone on purpose, remove it ("Remove fr-xyz from FR").
- **Blocked / system notices:** not a tracking problem. Check the allowlist header secret.

## Open items at handover (2026-11-14)
- [ ] Carolina Torres sends the allowlist request (`docs/allowlist-request.md`, not sent yet) to the sage.com IT / web security team; once granted, set `MONITOR_AUTH_HEADER`.
- [ ] Market owners review the URL lists and add paid-only landing pages.
- [ ] Decide the email channel (Phase 2): Claude mail connector or SMTP from GitHub Actions.
- [ ] Check with MarTech: AT has no active Floodlight / Google Ads conversion tags (they are limited to
      en-ZA style profiles); FR, ES and PT ecom checkouts (if used) do not fire the Floodlight form tag either.
