# AETHER v5 · FlytBase Inbound Intelligence

## Main change: Run New Analysis actually lives inside AETHER

**Open:** `http://localhost:8504`

AETHER v5 runs a **new six-stage Python agent workflow** from an arbitrary inbound *FlytBase sales enquiry* pasted into the **New analysis** screen. It no longer opens a dead `localhost:8501` link. The original working source project and its saved history are still used for credentials, budget control, and output storage.

### Launch on Windows

1. Extract this folder as `F:\Downloads\AETHER-FlytBase-v5`.
2. Keep the original folder at `F:\Downloads\Flytbase-inbound-agent` (including its existing `.venv`, private `.env`, and `runs/project_budget.json`).
3. Open this new folder in VS Code and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1
   ```
4. Open `http://localhost:8504`.
5. Click **Run new analysis** in the top-right corner. Paste a new inbound email. Optionally insert the original SQM assignment message.
6. Check the actual **Groq Usage (UTC)** and **Tavily Free** dashboard, ensure paid billing is disabled, and enter the reported Groq usage. Choose strict per-run caps and approve the budget.
7. Click **Run the six-stage analysis**. A stage monitor displays genuine processing and saved outcomes. Open the latest analysis when completed.

**No API requests are made by simply opening AETHER or by approving a budget.** Live requests begin only after a separate launch click. Providers use the original API keys from the private `.env`; neither key is bundled with this ZIP. The provider and project ledger may refuse execution when credits or the protected emergency reserve are insufficient. This is by design, and AETHER explains the block inside the screen rather than opening a broken URL.

### Scope and real-time capabilities

The agent processes any buyer inquiry in the FlytBase inbound-sales domain, within the existing engine's 16,000-character input limit. The workflow is specialized for enterprise autonomous-drone enquiries; results for irrelevant or insufficiently specified messages are appropriately incomplete, never guaranteed six-stage success. Real company research needs Groq and Tavily Free credentials, a positive Free credit balance, an approved project allowance, and public pages that can be inspected. No case study, contact, or answer is invented to make a report appear complete.

For every real run, the original source project saves `runs/<new-run-id>/run.json` and `report.md`; the completed analysis appears in the AETHER selector. Review any `partial` status before using the outbound drafts. The original runs are never edited by the AETHER display screens.

### UX refinements

- No sidebar CTA overlapping the logo or navigation; **Run new analysis** is always a prominent action at the top of each results page and an explicit navigation page.
- No broken external Streamlit dependency; all intake and execution controls are on the AETHER page.
- Sidebar scroll remains independent; no persistent fake pointer dot.
- Blue/cyan ambient cursor-following lighting is attached to the parent page and works across Streamlit rerenders.
- More expressive typographic hero, nav glow, tasteful orbit/constellation visual, animated selection and button effects; reduced-motion accessibility preserved.
- All six BDR review sections and their genuine source links remain available.

### Implementation / integrity

The original Python `Workflow` code is included for inspectability. The only backend extensions are an explicitly approved `fresh_enquiry` allowance in `aether_live.py` and per-provider bounded ledger reservations (`flytbase_bdr/run_allowance.py`, `flytbase_bdr/providers/tavily.py`). Those modifications apply inside **this extracted AETHER folder**, while the ledger and run outputs continue to be written to the original project.

No fresh API calls, emails, GitHub pushes, or file uploads were performed while building this release. The project was checked with Python compilation and offline tests. Browser execution and provider operations still need to be verified on the user's machine; Streamlit and external dependencies could not be installed inside the release environment.
