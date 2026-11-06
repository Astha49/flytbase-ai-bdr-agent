# AETHER v4 — FlytBase BDR Intelligence Interface

**A redesign of the reviewing experience for the existing FlytBase Python workflow.** The engine, budgets and historical run files are not modified. AETHER reads actual saved executions rather than making paid provider requests.

## Windows launch

1. Extract this `AETHER-FlytBase-v4` folder beside your original `Flytbase-inbound-agent` folder under `F:\Downloads`.
2. Open it in a separate VS Code window. Run `powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1`.
3. Visit `http://localhost:8503`.
4. In **ACTIVE ANALYSIS** choose the newest item marked **LIVE**, e.g. `20261106T160227_505a19b77c` from your original workspace. If it doesn't appear, expand **Load saved executions** and enter `F:\Downloads\Flytbase-inbound-agent\runs`.
5. For another real incoming buyer email, run/open the existing protected operator app at `http://localhost:8501` using `python -m streamlit run app.py` in the original project. After saving a new run, refresh AETHER to review it.

## What's different

- A compact first-screen lead briefing, qualification status, knowns, unknowns and next action.
- Five email paths in tabs, each with **Edit email** and **Copy email** alongside one another. Local browser edits never overwrite source evidence or send mail.
- All non-empty warnings actually expand and display their text; an empty section explains that no warnings exist. Sources remain visible near findings.
- Published case-study navigation is available **only for real saved runs**. Offline synthetic cases are labelled and do not link to nonexistent articles. Verified official-case navigation paths are UI-only, not hard-coded matching/scoring.
- Streamlit developer toolbar is set to `minimal` so the built-in **Record screen** menu does not distract reviewers.
- Navigation attempts to reset page scroll to the top after each page or run change.
- `LIVE` and `OFFLINE DEMO` badges prevent synthetic fixtures from being mistaken for the requested six-stage live SQM execution.
- **Open operator console** links to the existing workflow engine rather than launching a provider request from the viewer.

## Alignment to FlytBase's assignment (original emailed 5-page PDF)

The PDF requires an end-to-end working AI agent with inspectable Python workflow logic, and three deliverables: source access, **real output from all six stages** for the provided SQM email, and an **8–12 minute** recorded walkthrough that includes architecture, live processing, a proud design decision, a limitation, and qualification-framework reasoning. AETHER is the output-facing interface. The original Python project is the inspectable/executable system. **Submitting only an AETHER screenshot or its bundled synthetic offline fixture would not satisfy the requirements.**

The five-page assignment PDF is the candidate-specific recruitment material and is not redistributed in this ZIP. The actual FlytBase run remains in the source workspace's `runs` folder.

## Case-study links researched for the interface

- SQM: https://flytbase.com/case-studies/sqm-678-km2-mine-autonomous-inspection-adentu-and-flytbase
- Anglo American: https://flytbase.com/case-studies/anglo-american-autonomous-mining-drones-peru-case-study
- Official case-study directory: https://flytbase.com/case-studies

Note: An existing SQM iodine/leaching deployment is **not evidence of deployment at the lithium sites in the sample enquiry**. Link navigation corrections do not alter source claims, confidence outcomes or scoring.

## Boundaries

AETHER is an interface layer. It doesn't directly invoke Groq/Tavily or change source `run.json`. The original protected operator console continues to manage real live executions. The browser email editor can be used to prepare and copy a draft, but does not send it. Browser-local edits are not part of the authentic AI output. No simulated data is presented as live.
