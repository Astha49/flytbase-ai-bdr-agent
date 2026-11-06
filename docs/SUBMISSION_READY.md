# Submission readiness - 6 November 2026

**Offline-ready source; genuine repaired live acceptance and the user-recorded video are still outstanding.** No live API request, new real allowance, billing change, upload or submission occurred in this improvement task.

## Deliverables

- Existing six-stage engine and five-page Streamlit application preserved, including BANT scoring and strengthened evidence checks.
- History/daily/new-run/reserve accounting separated; explicit source/model-bound approval path, no automatic allowance or provider dispatch.
- JSON, complete Markdown and standalone AE handoff downloads across all five pages; saved replay stays labelled and makes no provider calls.
- Windows setup, dependencies, safe configuration, architecture, requirements, reviewer guide and an 8-12 minute walkthrough script.
- Curated source archive with credential scan, CRC check and SHA-256 manifest. Private runs/ledgers, confidential PDFs, .env, private research packs, venvs, caches, internal progress and backups excluded.

## Validation

**Final local suite: 250 passed, 0 failed (93.13 seconds). Extracted source-package suite: 233 passed, 17 explicitly skipped private-fixture tests, 0 failed (80.11 seconds).** No private fixtures were substituted or called live. The existing 19/19-check fictional six-stage simulation passes; it is not live acceptance. The latest real saved execution remains unchanged and partial. All five pages also rendered the actual latest partial record without constructing providers or changing its JSON/ledger. A headless local Streamlit server returned HTTP 200 for health and app HTML and was stopped after the smoke check.

## Exact commands

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -B -m scripts.simulate_offline --output tmp\rehearsal
.\.venv\Scripts\python.exe -m scripts.package_source
```

Opening the app and inspecting the included labelled fictional example requires no credentials or credits. The current archive is `dist/flytbase-inbound-source.zip`; manually review it before upload. No repository was published.

## Remaining live blockers and safe next action

No new-run allowance is approved. The legacy repair allowance is exhausted. Read the current free dashboard before any separate budget decision; cumulative project usage does not establish today's provider balance. Current Groq billing-plan status cannot be independently verified by the app. Genuine unknown public/private facts must remain unknown.

Use the read-only plan first:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m flytbase_bdr.run_allowance plan --source .\runs\20261105T195016_6b3a6fb0d3\run.json
```

It recommends a conditional 63,000 combined-token cap based on recorded expanded-mode usage plus reserve, zero Tavily calls, zero retries, bounded requests and cached evidence. It does not authorize or guarantee execution. [APPROVED_CONTINUATION.md](APPROVED_CONTINUATION.md) contains the exact **separate** budget approval and launch commands, expiry rules and inspection requirements. A future live run gets a new ID; history/reservations are retained. Do not record a saved replay as new AI execution.
