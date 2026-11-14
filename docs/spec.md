# Spec: EU Outside-In Tracking Monitor

| | |
|---|---|
| Status | Draft v1 – for review |
| Date | 2026-11-14 |
| Owner (build) | Marius |
| Owner (operation) | UK colleague (non-technical, Claude Code + GitHub account) |
| Markets | DE, AT, FR, ES, PT |
| Demo / handover | ~2026-11-17 (3 days) |
| Related | `problem.md`, `Tracking_Audit_DE_Summary_EN.md`, `MarTech_Briefing_Tag98_EN.md` |

---

## 1. Purpose and scope
The monitor checks paid media tracking on Sage websites in five EU markets every working day, from the outside. It reports a traffic-light status per market and overall. The goal is to catch breaks like the DE tag-98 issue (Tealium publish of 2026-08-24) within 24 hours instead of weeks. See `problem.md` for the full problem statement.

**Hard constraints**
- No test conversions. No form or checkout is ever submitted.
- No access to Tealium or the tag managers; everything is observed from outside.
- Portable core: checks and rating run without Claude, so the core could also run in a web app or other CI.
- Handover-ready: the solution runs in the colleague's accounts, not on Marius' machine.
- All documentation, UI and messages are in English.

### 1.1 MVP (demo in 3 days)
- Checks and traffic light for all 5 markets, including the *Site down* and *Global* states
- Auto-baseline of expected tags per URL
- Consent tested in two states: none, and "accept all"
- Click-ID persistence checks and multi-step journeys (no submit)
- `utag.js` daily diff, offline load-rule evaluation, AI summary
- Artifact dashboard with unlimited history and an acknowledge button
- Maintenance skill for the colleague
- Handover documentation (README, HANDOVER)

### 1.2 Phase 2
- Email alerts on yellow/red, respecting acknowledgements
- Partial-consent combinations (e.g. analytics only)
- EU proxy or self-hosted runner, if the geo/bot tests require it (see §12)
- Second daily run
- Teams notification

---

## 2. Architecture

```
┌──────────────────────────── GitHub (private repo, Marius' account) ────────────────────────────┐
│                                                                                                 │
│  config/markets.yaml ──► GitHub Actions (Mon–Fri 06:00 CET, Playwright/Chromium)                 │
│  baseline/*.json     ──►   1. load URLs + journeys, 2 consent states each                        │
│                            2. capture network/cookies/dataLayer, block tracking hits             │
│                            3. fetch + diff utag.js, evaluate load rules offline                  │
│                            4. rules engine → status per check/URL/market/global                  │
│                            5. commit results/YYYY-MM-DD.json + utag snapshots                    │
│                            6. render static report (fallback dashboard)                          │
└─────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                              │ results JSON
                                              ▼
┌──────────────────── Claude (colleague's company account) ────────────────────┐
│  Routine "tracking-monitor-daily" (~06:45 CET, Mon–Fri)                        │
│   - pull repo, read today's results + diff                                      │
│   - read acknowledgements from the artifact DB                                  │
│   - write a plain-English diagnosis (likely cause, who should act)              │
│   - summarise the utag.js diff and rate its risk                                │
│   - republish the dashboard artifact (same URL)                                 │
│   - (Phase 2) send email on new yellow/red                                      │
│  Skill "tracking-monitor" – maintenance commands (add URL, confirm baseline …)  │
└───────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
              Dashboard artifact (shared with all stakeholders) + artifact DB (acks)
```

**Division of responsibilities**
- **Deterministic (repo):** everything that decides green, yellow or red.
- **Claude:** explanation, diff interpretation, risk rating of publishes, dashboard publishing and maintenance.
- If Claude is unavailable, the status is still correct and visible in the static report.

### 2.1 Runtime variants (all supported)
| Variant | Checks | Diagnosis + dashboard | When to use |
|---|---|---|---|
| **A (default)** | GitHub Actions | Claude cloud routine | Colleague's account supports routines with GitHub access |
| B | GitHub Actions | Claude Desktop scheduled task (her machine must be on) | No cloud routines available |
| C | GitHub Actions | none; static HTML report (GitHub Pages, private) + rule-based text | No Claude automation available |
| D | Any Node host (VM, Azure DevOps, cloud function) | as above | Future web app / non-GitHub setup |

---

## 3. Repository structure
```
tracking-monitor/
├─ README.md                    # what it is, how it works (EN)
├─ docs/
│  ├─ HANDOVER.md               # setup steps + demo script for the colleague
│  ├─ CHECKS.md                 # check catalogue (generated from src/checks)
│  └─ TROUBLESHOOTING.md
├─ config/
│  ├─ markets.yaml              # markets, Tealium profile, URLs, journeys, recipients
│  └─ platforms.yaml            # request patterns + criticality per vendor
├─ baseline/
│  └─ <market>/<url-id>.json    # confirmed expected tags per URL + consent state
├─ src/
│  ├─ run.ts                    # entry point (CLI: run, baseline, report)
│  ├─ browser/                  # Playwright session, consent handling, request interception
│  ├─ checks/                   # one module per check (see §4)
│  ├─ tealium/                  # utag.js fetch, parse, diff, load-rule evaluator
│  ├─ rules/                    # severity + aggregation (URL → market → global)
│  └─ report/                   # JSON writer + static HTML renderer
├─ results/
│  ├─ YYYY-MM-DD.json           # one file per run, kept forever
│  └─ utag/<profile>/YYYY-MM-DD.js
├─ dashboard/
│  └─ index.html                # artifact template (reads data embedded at publish time)
├─ skills/tracking-monitor/
│  └─ SKILL.md                  # maintenance + diagnosis skill for Claude
├─ routine/
│  └─ daily-prompt.md           # prompt of the Claude routine
└─ .github/workflows/
   ├─ daily.yml                 # cron: 0 5 * * 1-5 (UTC; 06:00 CET winter / 07:00 CEST summer, see note)
   └─ manual.yml                # workflow_dispatch: run one market / one URL / baseline
```
**Tech stack:** Node 20 + TypeScript, Playwright (Chromium), `js-yaml`, a small HTML renderer without a framework. The workflow is pinned to `ubuntu-latest`.

*Note on time zones:* GitHub cron is in UTC. Use `0 5 * * 1-5`, which is 06:00 CET in winter and 07:00 CEST in summer. Alternatively, run two cron entries with a guard. Decision for the MVP: 05:00 UTC.

---

## 4. Check catalogue
Each check produces `pass | warn | fail | error`, with evidence: request URL, parameters, cookie values and a screenshot on failure.

**Severity legend:** **R** = counts toward red, **Y** = counts toward yellow, **SD** = site down, **I** = info only.

### 4.1 Page and Tealium
| ID | Check | Method | Sev. |
|---|---|---|---|
| PAGE-01 | Final HTTP status 2xx; no unexpected redirect (e.g. to another market or a 404 page) | navigation response + final URL vs. expected | SD |
| PAGE-02 | Page renders (no error template, title present) | DOM | SD |
| TEAL-01 | `utag.js` loaded from `tags.tiqcdn.com/utag/sage/<profile>/prod/` | request match | SD |
| TEAL-02 | Correct profile per market (e.g. `de-de`); environment `prod` | URL parse | R |
| TEAL-03 | `utag_data` / data layer present, with key variables (page type, language, country) | `window.utag_data` | Y |
| TEAL-04 | `utag.js` changed since the previous run (publish detected) | hash + diff | I → Y if conversion-relevant (§6.4) |

### 4.2 Consent (OneTrust)
| ID | Check | Method | Sev. |
|---|---|---|---|
| CONS-01 | Banner shown on first visit (EU variant, correct language) | DOM `#onetrust-banner-sdk` | R |
| CONS-02 | **Before consent:** no marketing hits (Floodlight, Ads, Meta, LinkedIn, UET, TikTok …) and no marketing cookies | request/cookie capture | R |
| CONS-03 | Before consent: Google Consent Mode default = `denied` (if Consent Mode is used) | `gcs`/`gcd` params, dataLayer | R |
| CONS-04 | After "Accept all": consent groups set (`OptanonConsent` contains C0002/C0004 …), Consent Mode update `granted` | cookie + params | R |

### 4.3 Tags after consent (baseline-driven)
Expected tags per URL come from the confirmed baseline (§6.1). Vendor patterns are in `config/platforms.yaml`.

| ID | Vendor / tag | Detection pattern (examples) | Sev. if missing |
|---|---|---|---|
| TAG-GA4 | GA4 page_view | `google-analytics.com/g/collect` or `*/g/collect`, `tid=G-…`, `en=page_view` | R |
| TAG-FL | Floodlight pageview / counter | `ad.doubleclick.net/activity` or `*.fls.doubleclick.net`, `src=<id>` | R |
| TAG-ADS | Google Ads remarketing / config | `googleads.g.doubleclick.net/pagead/viewthroughconversion`, `google.com/pagead` | R |
| TAG-CL | Conversion Linker active (writes `_gcl_au`) | cookie | R |
| TAG-UET | Microsoft UET | `bat.bing.com/action`, `ti=` | R |
| TAG-META | Meta Pixel PageView | `facebook.com/tr`, `ev=PageView` | Y |
| TAG-LI | LinkedIn Insight | `px.ads.linkedin.com`, `snap.licdn.com` | Y |
| TAG-OTHER | Any other vendor found in the baseline (TikTok, Xing, programmatic …) | auto-discovered host list | Y |
| TAG-NEW | A tag fires that is **not** in the baseline | diff | I |

*Criticality per vendor can be changed in `platforms.yaml`. The Google stack and UET default to red because they drive bidding.*

### 4.4 Click-ID persistence
Each landing page is opened with synthetic IDs: `?gclid=TEST_MON_<date>&msclkid=TEST_MON_<date>&fbclid=TEST_MON_<date>&utm_source=tracking-monitor&utm_medium=cpc`.

| ID | Check | Method | Sev. |
|---|---|---|---|
| CLID-01 | `_gcl_aw` written with test gclid (after consent) | cookie | R |
| CLID-02 | `_uetmsclkid` written | cookie | R |
| CLID-03 | `_fbc` written | cookie | Y |
| CLID-04 | gclid is passed on Floodlight / Ads hits (`gclaw`/`gclid` param) | request params | R |
| CLID-05 | Click IDs survive the journey into form/checkout (cookies still set, sent on hits there) | journey (§4.5) | R |

### 4.5 Journeys (multi-step, no submit)
Defined per market in `markets.yaml`, e.g. *landing page with gclid → product page → trial/buy entry → checkout step 1*.

| ID | Check | Method | Sev. |
|---|---|---|---|
| JRNY-01 | Every step reachable via the defined click or URL | Playwright steps | SD |
| JRNY-02 | Expected tags fire on every step (baseline) | as §4.3 | R/Y |
| JRNY-03 | SPA virtual pageviews fire on route change (Next.js checkout) | GA4 `page_view` / `utag.view` | R |
| JRNY-04 | Click IDs are still present at the last step | as CLID-05 | R |
| JRNY-05 | Form fields and submit button present (form not broken) – **never clicked** | DOM | Y |

### 4.6 Conversion logic without converting
| ID | Check | Method | Sev. |
|---|---|---|---|
| CONV-01 | **Offline load-rule evaluation:** for each conversion tag (e.g. DE Floodlight tag 98 `sageg0/dynam00`, tag 284), evaluate the load rules in `utag.js` against realistic event payloads (`form_submit_success` with `customer_lead_type=ecom_try/ecom_buy`, gated content …). Expected: true. | parse `utag.js` loader + rule functions in a sandbox | R |
| CONV-02 | **In-browser event simulation:** call `utag.link({...conversion payload...})` on the form page and check which tags *would* fire. All outgoing hits are intercepted and aborted, so no conversion is recorded. | intercept | R |
| CONV-03 | Conversion tag set unchanged vs. baseline (tag IDs, Floodlight `type`/`cat`) | diff | Y |

> CONV-01 is exactly the check that would have caught the tag-98 break the day after the publish.
> Conversion payloads per market are kept in `config/markets.yaml` (`conversion_events`).

---

## 5. Request handling and data hygiene
- **Default: capture and block.** Playwright `page.route()` matches all vendor hosts from `platforms.yaml`. The request (URL, method, body) is recorded and then `route.abort()` is called. No data reaches GA4, Floodlight, Ads, Meta and similar vendors.
- **Live sample:** one URL per market (`live_sample: true` in config) lets requests through. This verifies real server responses (2xx, redirects such as `ad.doubleclick.net` → `fls`). These visits are marked with:
  - User-Agent suffix `SageTrackingMonitor/1.0`
  - `utm_source=tracking-monitor&utm_medium=monitoring`
  - the test click-ID prefix `TEST_MON_`

  MarTech is informed so they can filter these visits in GA4 (e.g. by UA or source).
- CONV-02 simulations **always** block, even on live-sample URLs.
- No real personal data is ever typed into forms.
- Each consent state runs in a fresh browser context (no shared cookies).
- Retries: a failed check is retried up to 2 times. A check only fails if it fails in all attempts (prevents flaky alarms). Navigation timeout is 45 s.

---

## 6. Rating logic

### 6.1 Auto-baseline
1. `npm run baseline -- --market FR` (or the skill command "create baseline for FR") runs all URLs and records which vendors and IDs fire per consent state.
2. The output goes to `baseline/<market>/_pending/`. Marius or the colleague confirms it via the skill ("confirm baseline FR"), which moves the files into `baseline/` and commits them.
3. Until a URL has a confirmed baseline, its tag checks are `warn` (yellow) with the reason "baseline pending".
4. Re-baselining a single URL is possible after intended changes.

### 6.2 URL → market → global
- **URL status** = worst check result on that URL. `SD` checks set the URL to *Site down* instead of red.
- **Market status:**
  - 🔴 **Red:** any R-check fails on any URL or journey (and is not acknowledged)
  - 🟡 **Yellow:** no red, but at least one Y-check fails, or a conversion-relevant publish was detected
  - 🟢 **Green:** otherwise
  - ⚫ **Site down** is a separate badge per market (count of affected URLs). It does not change the tracking colour, but is listed at the top.
- **Global:**
  - If the **same check ID fails in ≥3 of 5 markets**, a 🔴 **Global incident** is raised, with a "likely shared cause" note (shared Tealium template, OneTrust, Google tag config).
  - Otherwise the overall status is the worst market status.

### 6.3 Acknowledgements
- On the dashboard, a user can acknowledge a failing finding (`market + check ID + URL or "all"`) with a note, e.g. "MarTech ticket #123 raised". They choose an expiry: until fixed / 7 days / 30 days.
- Acknowledged findings stay visible (greyed, with note and age) but **do not count toward the market colour** and do not trigger alerts.
- When the finding passes again, the acknowledgement closes automatically.
- Storage: artifact database, collection `acks`. The Claude routine also mirrors the active acks into `config/acks.json` in the repo, so the deterministic rules (and variant C) can use them.

### 6.4 Publish detection (utag.js diff)
- The runner stores `utag.js` and all loaded `utag.<n>.js` per profile each day and computes a structured diff:
  - tags added or removed
  - load-rule changes per tag
  - mapping/extension changes
- **Rule-based pre-classification:** if the change touches a tag in the conversion set (§4.6) or its load rules → yellow. Otherwise → info.
- **Claude** adds a plain-English summary ("Tag 98 got load rule 274 – requires ga4_customer_lead_type, which is not set on ecom forms → ecom conversions will not fire") and a risk rating (low/medium/high).

---

## 7. Data model

### 7.1 `config/markets.yaml` (excerpt)
```yaml
markets:
  DE:
    tealium_profile: de-de
    language: de
    consent_accept_selector: "#onetrust-accept-btn-handler"
    recipients: [ ... ]            # Phase 2
    urls:
      - id: de-lp-sage50
        url: https://www.sage.com/de-de/produkte/sage-50/
        type: landing_page         # landing_page | product | form | checkout | content
        live_sample: true
      - id: de-form-demo
        url: https://www.sage.com/de-de/.../demo-anfordern/
        type: form
    journeys:
      - id: de-j-trial-sage50
        steps:
          - goto: https://www.sage.com/de-de/produkte/sage-50/?{clickids}
          - click: "a[href*='/cart/']"
          - expect_url: "/de-de/cart/"
    conversion_events:
      - name: ecom_try
        payload: { tealium_event: form_submit_success, customer_lead_type: ecom_try }
        expected_tags: [98]
```

### 7.2 `results/YYYY-MM-DD.json` (shape)
```json
{
  "run_id": "2026-11-17T05:00Z",
  "runner": { "type": "github-actions", "region": "us-east", "ip_country": "US" },
  "global": { "status": "yellow", "incidents": [] },
  "markets": {
    "DE": {
      "status": "red",
      "site_down": 0,
      "utag": { "version": "ut4.51.202611101203", "changed": true, "diff_ref": "utag/de-de/2026-11-17.diff.json" },
      "urls": [
        {
          "id": "de-lp-sage50",
          "status": "green",
          "checks": [
            { "id": "CONS-02", "result": "pass", "consent": "none", "evidence": { "requests": [] } }
          ]
        }
      ],
      "journeys": [],
      "conversion": [ { "id": "CONV-01", "tag": 98, "event": "ecom_try", "result": "fail", "detail": "load rule 274 false" } ]
    }
  },
  "acks_applied": []
}
```
The schema is versioned (`schema_version`) and documented in `docs/`.

---

## 8. Dashboard (Claude artifact)
- **Header:** global status, last run time, runner region, links to run logs.
- **Market tiles (5):** colour, site-down badge, count of failing checks, "red since" date, publish indicator.
- **Global incidents banner** (if any).
- **Drill-down per market:** URLs and journeys × checks matrix. Click a cell to see the evidence (request params, cookies, screenshot link) and Claude's diagnosis.
- **Publish panel:** latest `utag.js` changes per profile, with the AI summary and risk rating.
- **History:** status timeline per market (unlimited, paginated by month), plus a per-check failure trend.
- **Acknowledge button** on each failing finding (note + expiry). Uses the artifact DB.
- English only, light/dark mode, works on mobile.
- Shared with all stakeholders (colleague, Marius, market managers, MarTech/agency) inside the Sage org.
- The routine republishes it daily to the **same URL**. Data is embedded at publish time; acks are live from the DB.

**Fallback:** the runner also renders `report/index.html` (same layout, no ack button, no AI text) as a GitHub Actions artifact and on private GitHub Pages.

---

## 9. Claude routine (`routine/daily-prompt.md`)
Runs Mon–Fri, about 45 minutes after the checks. Tasks:
1. Pull the repo and load today's and yesterday's results. If today's file is missing → mark "runner failed" on the dashboard (red system banner).
2. Load the active acks from the artifact DB and mirror them to `config/acks.json` (commit).
3. For each new or ongoing failure: write a 1–3 sentence diagnosis with likely cause, evidence and suggested owner (MarTech / web team / agency).
4. Summarise the `utag.js` diffs and rate their risk.
5. Detect patterns across markets (supports the global logic with explanation).
6. Republish the dashboard artifact.
7. *(Phase 2)* Email on new yellow/red that is not acknowledged.

The routine never changes the colours computed by the rules engine. It only explains them.

---

## 10. Maintenance skill (`skills/tracking-monitor/SKILL.md`)
Plain-English commands for the colleague in Claude Code. The skill edits config, validates it, commits and pushes:

| Command (examples) | Effect |
|---|---|
| "Add URL https://… to FR as landing page" | adds to `markets.yaml`, runs a single-URL check, proposes a baseline |
| "Remove URL … from ES" | removes it; history is kept |
| "Create / confirm baseline for PT" | §6.1 |
| "Run the check now for AT" | triggers `manual.yml` via `gh workflow run` |
| "Why is DE red?" | reads the latest results + diff and explains |
| "Acknowledge FR CLID-01 – MarTech informed, 7 days" | writes the ack |
| "Add recipient …" | Phase 2 |

---

## 11. Handover
1. Marius creates the private repo and adds the colleague as collaborator (write access).
2. The colleague connects GitHub to Claude Code, then installs the skill (repo `skills/`) and the routine (from `routine/daily-prompt.md`).
3. The first routine run creates the dashboard artifact in **her** account (she owns it). She shares it with the stakeholders.
4. A 30-minute demo, following the script in `docs/HANDOVER.md`:
   - dashboard tour
   - walk through a seeded example failure
   - acknowledge it
   - add a URL via the skill
   - trigger a manual run
5. Checklist: account capabilities verified (routines, GitHub access, artifacts). If not → variant B or C (§2.1).

---

## 12. Risks and open points
| # | Risk / open point | Mitigation / decision needed |
|---|---|---|
| 1 | **Geo/bot:** GitHub runners are in the US. sage.com may geo-redirect, show a non-EU consent banner, or block datacenter IPs. | Day 1 spike: run all 5 markets from a runner and log the final URL, banner variant and HTTP status. If affected → EU proxy (Playwright `proxy`) or self-hosted EU runner (Phase 2, may cost a little). |
| 2 | Email delivery channel unknown (Claude connector vs. SMTP from Actions) | Phase 2; the architecture supports both. Clarify with the colleague/IT. |
| 3 | Colleague's company account may not allow cloud routines, GitHub connection or shared artifacts | Verify before the demo. Fallback variants B/C. |
| 4 | Tealium profile per market (`de-at`? shared template?) not yet verified | Day 1: verify outside-in from `utag.js` URLs. |
| 5 | URL lists for AT/FR/ES/PT | Claude proposes 20–50 per market from sitemap and navigation; Marius reviews (day 1). |
| 6 | Bot protection or consent changes cause false alarms | Retries, "runner/system" status separate from market status, screenshot evidence. |
| 7 | Live-sample hits appear in GA4 | Low volume (5 visits/day), clearly marked. Inform MarTech. |
| 8 | Load-rule evaluation needs to execute parts of `utag.js` | Run in an isolated VM sandbox with a mocked `window`/`document`; no network access. |
| 9 | Repo on a personal GitHub account holds Sage-internal details | Private repo. Transfer to a Sage org later if one exists. |

---

## 13. Acceptance criteria (MVP)
- [ ] A daily workflow runs Mon–Fri at 05:00 UTC for all 5 markets and commits `results/<date>.json` in under 30 minutes.
- [ ] All checks in §4 are implemented (journeys for at least 1 per market).
- [ ] A replay test against the archived DE `utag.js` from before and after 2026-08-24 shows CONV-01 green before and **red** after (tag 98, `ecom_try`).
- [ ] Before consent, no marketing request leaves the browser in block mode (verified in the logs).
- [ ] Baselines confirmed for all markets.
- [ ] The dashboard shows global and market status, drill-down, history, publish diff with AI summary, and a working acknowledge button.
- [ ] Skill commands from §10 (excluding Phase 2) work in the colleague's account.
- [ ] README and HANDOVER are complete, in English. The demo has been held.

## 14. Changes during implementation (2026-11-14)
- **Python instead of Node/TypeScript.** Python 3 was available on the build machine and Node was not. The
  structure is unchanged: `monitor/` replaces `src/`, and the CLI is `python -m monitor ...`. Python is just as
  portable to GitHub Actions, servers or a web app.
- **Bot protection.** sage.com answers the headless browser with HTTP 403, even from the Sage network. The
  monitor does not try to get around it. Instead:
  - An allowlist request was prepared (`docs/allowlist-request.md`).
  - Blocked pages are reported as a system status ("blocked"), not as red.
  - An **interim mode** collects page evidence in the Claude desktop browser (`collector.js`,
    `python -m monitor ingest`). It is limited to the marked sample page per market, because those visits
    send real (marked) hits.
- **CONV-01 payloads.** Conversion events now model the two real form types:
  - the ecom checkout (`action` + `customer_lead_type`)
  - Sitecore gated forms (`event_name`, `triggered_by=sitecore`, `release_date`, and a `gate_content_name`
    from which Tealium derives `ga4_customer_lead_type`)
- **Auto-discovered vendors** (not listed in `platforms.yaml`) are informational rather than yellow. This
  avoids flapping colours; a vendor is promoted by adding it to `platforms.yaml`.
- The skill lives in `.claude/skills/tracking-monitor/`, so Claude Code loads it automatically in the repo.

## 15. Three-day plan
| Day | Work |
|---|---|
| **1** | Repo scaffold. Geo/bot spike on GitHub runners. Verify Tealium profiles. Propose URL lists per market. Browser session + interception + consent handling. |
| **2** | All checks (§4), load-rule evaluator incl. tag-98 replay test, rules engine, results JSON, baseline flow, `utag.js` diff. |
| **3** | Dashboard artifact + acks, Claude routine prompt, maintenance skill, static fallback report, README/HANDOVER, demo dry run. |
