---
name: tracking-monitor
description: Operate and maintain the EU Tracking Monitor (daily outside-in check of Sage paid media tracking for DE, AT, FR, ES, PT). Use when the user asks to add or remove a URL or journey, create or confirm a tag baseline, run the check now, explain why a market is red or yellow, acknowledge a finding, run the interim browser check, or anything about the tracking monitor, its dashboard or its results.
---

# EU Tracking Monitor – operator skill

You are helping someone (often non-technical) operate the tracking monitor in this repository.
Always answer in plain English, say what you changed, and commit + push every config change
with a clear message so the daily GitHub Actions run picks it up.

Key files:
- `config/markets.yaml`: markets, URLs, journeys, conversion events. Edit with care; keep the format.
- `config/platforms.yaml`: vendor patterns and severities (change only when asked).
- `baseline/<MKT>.json`: confirmed expected tags; `baseline/_pending/` = proposals.
- `results/<day>.json`: evaluated results; `results/index.json`: history; `results/diagnosis/`: explanations.
- Commands: `python -m monitor --help` (run, collect, ingest, evaluate, baseline, report, dashboard).

Before running Python commands make sure dependencies exist: `pip install -r requirements.txt` and
`python -m playwright install chromium` (first time only).

## Add a URL
"Add https://www.sage.com/fr-fr/... to FR as landing page"
1. Check that the URL belongs to the market prefix (`/fr-fr/` for FR, `/de-de/` DE, `/de-at/` AT, `/es-es/` ES, `/pt-pt/` PT).
   Strip tracking parameters (gclid, utm_* ...).
2. Create a short unique id: `<mkt>-<slug>` in lowercase, e.g. `fr-sage-50-trial`.
3. Append under `markets.<MKT>.urls` as `{id: ..., url: "...", type: landing_page}`.
   Types: landing_page, product, pricing, form, trial, checkout, content. Never set `live_sample`
   unless asked (one per market maximum).
4. Run `python -m monitor run --market <MKT> --url <id>` (works once the allowlist exists; until then the
   page shows as blocked, which is expected). Then propose a baseline for that page:
   `python -m monitor baseline propose --market <MKT> --url <id>`, show the user the vendors found,
   and ask whether to confirm.
5. Commit: `Add <id> to <MKT>` and push.

## Remove a URL
Delete the entry from `markets.yaml` (history in `results/` stays). Commit `Remove <id> from <MKT>`.

## Create / confirm a baseline
- Propose from the latest run: `python -m monitor baseline propose --market <MKT> [--day YYYY-MM-DD] [--url id ...]`.
- Show the user, per page, which vendors and account IDs were seen (from `baseline/_pending/<MKT>.json`)
  and the conversion tags per event. Point out anything odd (e.g. no Floodlight on a paid landing page).
- Only after the user says yes: `python -m monitor baseline confirm --market <MKT> --by "<their name>"`,
  then `python -m monitor evaluate`, commit `Confirm baseline <MKT>` and push.

## Run the check now
- Full: `gh workflow run daily.yml` (optionally `-f market="FR" -f url="fr-home"`), then tell the user
  the run usually takes 10–25 minutes and results appear on the dashboard after the routine runs, or
  run the routine steps from `routine/daily-prompt.md` yourself.
- Tealium-only, locally: `python -m monitor run --no-browser`.

## Why is a market red / yellow?
Read `results/<latest>.json` → `markets.<MKT>.checks` where `result` is `fail`/`warn`, plus
`results/diagnosis/<latest>.json`. Explain in plain language: what is broken, since when
(`red_since`), what it affects (bidding, reporting, compliance), who should fix it and how.
Severity meaning: red = conversions, click IDs or consent compliance broken; yellow = secondary
pixel, data layer, unconfirmed baseline or a conversion-relevant Tealium publish; site down = page
or utag.js unreachable; system = monitor was blocked (not a tracking problem).

## Acknowledge a finding
Preferred: the Acknowledge button on the dashboard. Via Claude: add a document to the dashboard
artifact's database collection `acks` (ArtifactData `set`, new doc id) with
`{market, check, target ('*' for all pages), note, expires (YYYY-MM-DD or null), created, by}`,
then mirror to `config/acks.json`, run `python -m monitor evaluate`, republish the dashboard.

## Interim browser run (until sage.com allowlists the monitor)
The automated browser is blocked by sage.com bot protection (HTTP 403). Until the allowlist exists,
page checks can be collected in the Claude desktop app's built-in browser, which is a normal browser.
Never try to disguise the automated browser to get around the bot protection.
Per page (use the `live_sample: true` page of each market unless the user names others; keep it to a
handful of pages, because these visits send real, marked tracking hits):
1. Navigate to `https://www.sage.com/robots.txt` and run `monitor/collector.js` followed by
   `__tm.reset()` in the JavaScript tool (clears cookies on a page without running tags).
2. Navigate to the page URL with `?gclid=TEST_MON_<yyyymmdd>&msclkid=TEST_MON_<yyyymmdd>&fbclid=TEST_MON_<yyyymmdd>&utm_source=tracking-monitor&utm_medium=monitoring`.
3. Run `monitor/collector.js` again, then `JSON.stringify(await __tm.visit(5000, 8000))`.
4. Add the result to an evidence file shaped like `results/claude-browser/2026-11-14.json`
   (`{"markets": {"<MKT>": {"visits": [{"id", "url", "status": 200, "final_url", "click_ids", "live_sample", "pre", "post"}]}}}`).
Then: `python -m monitor ingest <file> --day <day>`, `python -m monitor evaluate --day <day>`,
render and publish the dashboard, commit.

## Rules
- Never submit forms, start checkouts or create leads. Journeys stop before submit.
- Never put personal data or secrets in the repo. The allowlist header lives only in the GitHub secret `MONITOR_AUTH_HEADER`.
- Keep all repository text in English.
