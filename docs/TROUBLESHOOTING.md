# Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| All pages "blocked" (BOT-01), notice "No page-level evidence" | sage.com bot protection answers 403 to the automated browser | Expected until the allowlist exists. Check the `MONITOR_AUTH_HEADER` secret once it is agreed. Never disguise the browser. |
| Workflow fails at "Commit results" | Workflow lacks write permission | Settings → Actions → General → Workflow permissions → Read and write |
| Workflow fails at "Regression tests" | A code change broke the checker | Open the log. The failing test name says what broke. |
| A market is yellow with "baseline pending" | Baseline not confirmed yet | Ask Claude: "Show me the pending baseline for <MKT>", then confirm |
| New red `TAG:<vendor>` after a publish | Tealium change removed or broke the tag | Read the publish panel. If intended, re-baseline the page; if not, send the finding to MarTech |
| `CONV-01` red | Conversion tag's load rule no longer matches the conversion event | See the diagnosis. Compare `results/utag/<profile>/` snapshots before and after the publish |
| `CONV-01` warns "could not run" | utag.js structure changed so the sandbox cannot evaluate it | Run `python -m unittest discover tests` locally; check `monitor/loadrules.py` |
| `PAGE-01` site down: "Redirected away from the market" | Page moved or was removed | Update or remove the URL in `config/markets.yaml` |
| Flapping yellow/green for a secondary pixel | Pixel loads late or is sampled | Increase `POST_CONSENT_MS` in `monitor/browser.py`, or lower its severity in `config/platforms.yaml` |
| Dashboard did not update | Routine did not run or could not publish | Check the routine's last run in Claude; run the steps in `routine/daily-prompt.md` by hand |
| Acknowledge button missing | Viewer has view-only access or is signed out | Give them Contributor access on the artifact |
