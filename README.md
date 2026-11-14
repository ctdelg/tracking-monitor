# EU Tracking Monitor

A daily, automated **outside-in check of paid media tracking** on sage.com for **DE, AT, FR, ES and PT**.
It visits the pages paid campaigns send traffic to, the way a visitor would. It then reports a
traffic light per market:

| Status | Meaning |
|---|---|
| 🔴 **Red** | Something that breaks paid media measurement: a conversion tag would not fire, a click ID (gclid / msclkid) is lost, or tags fire before consent. |
| 🟡 **Yellow** | Secondary problems: a secondary pixel (Meta, LinkedIn, TikTok …) missing, data layer gaps, an unconfirmed baseline, or a Tealium publish that touched conversion tags. |
| 🟢 **Green** | Everything checked works. |
| ⚫ **Site down** | A page or utag.js is unreachable. Shown separately from the tracking colour. |
| 🔴 **Global incident** | The same check fails in 3 or more markets, which points to a shared cause. |

Built after the DE Floodlight tag-98 break: a Tealium publish on 2026-08-24 stopped ecom
trial/buy conversions from firing and nobody noticed for weeks. The monitor's load-rule check (CONV-01)
would have turned DE red the next morning. The regression test in `tests/` replays exactly that.

## How it works

```
GitHub Actions (Mon–Fri 05:00 UTC)                         Claude routine (06:45, colleague's account)
  python -m monitor run                                       reads results + acknowledgements
   ├─ Tealium CDN: utag.js per market, diff vs. last publish   writes plain-English diagnosis
   ├─ Load rules: replays conversion events in a sandbox       publishes the dashboard artifact
   ├─ Browser: each URL before/after consent, click IDs        (Phase 2: email on new red/yellow)
   └─ Rules engine → results/<day>.json + report/index.html
```

- **Deterministic core** (`monitor/`, Python + Playwright): all checks and all colours. It runs anywhere Python
  runs, for example GitHub Actions, a server, Azure DevOps or a future web app. It does not depend on Claude.
- **Claude** only explains results, keeps acknowledgements in sync and publishes the dashboard.
- **No conversions are created.** Forms are never submitted. Tracking hits are captured and then blocked,
  except on one marked sample page per market (`utm_source=tracking-monitor`, click IDs `TEST_MON_<date>`).

## Current status (2026-11-14)

- Tealium CDN, publish diff and load-rule checks run fully automated for all 5 markets.
- **Browser checks are blocked by sage.com bot protection (HTTP 403)**. An allowlist request is with the web
  team (`docs/allowlist-request.md`). Until it is granted, blocked pages show as
  "blocked" (system status, not red). Page checks can be collected manually in the Claude desktop browser
  (see the skill, "Interim browser run").
- URL lists are a first proposal from the sitemaps. Market owners still need to add paid-only landing pages.
- Baselines are proposed (`baseline/_pending/`) and need one confirmation per market.

## Quick start (local)

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m monitor run --no-browser        # Tealium + load-rule checks only
python -m monitor run --market DE         # full run for one market
python -m unittest discover tests         # regression tests incl. the tag-98 replay
```

Results: `results/<day>.json`. Readable report: `report/index.html`.

## Repository map

| Path | What |
|---|---|
| `config/markets.yaml` | Markets, URLs, journeys, conversion events. Edit this to change what is checked. |
| `config/platforms.yaml` | How each vendor's hits are recognised, and how severe a missing hit is |
| `config/acks.json` | Acknowledged findings (mirrored from the dashboard) |
| `baseline/` | Confirmed expected tags per page and conversion event |
| `monitor/` | The checker (see `monitor/checks.py` for the check catalogue) |
| `results/` | Daily results, history index, utag.js snapshots, Claude diagnoses |
| `.github/workflows/daily.yml` | Scheduled run + manual "Run workflow" button |
| `routine/daily-prompt.md` | Prompt for the daily Claude routine |
| `.claude/skills/tracking-monitor/` | Claude skill for day-to-day operation ("add this URL to FR") |
| `docs/` | Handover guide, check catalogue, troubleshooting |

See `docs/HANDOVER.md` to set it up in another account, `docs/spec.md` for the full specification and
`docs/problem.md` for the original problem statement.
