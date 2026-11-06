# FlytBase inbound BDR workbench

A local Python/Streamlit application that turns one inbound enquiry into six reviewable sales outputs. Groq generates typed proposals; Tavily retrieves public evidence; Python controls dependencies, BANT scoring, citations, budgets and exports. Emails are drafts only: there is no sending integration.

**Readiness, 6 November 2026:** repaired and validated offline. Historical live results remain partial; no repaired end-to-end live acceptance or recorded video is claimed. The included recruiter example is explicitly fictional. Read the [reviewer guide](docs/REVIEWER_GUIDE.md), [architecture](docs/ARCHITECTURE.md), [requirements](docs/REQUIREMENTS.md), [approval procedure](docs/APPROVED_CONTINUATION.md), and [10-minute walkthrough](docs/WALKTHROUGH_READY_SCRIPT.md).

## Windows setup

From this project's folder (Python 3.11+; tested locally with Python 3.14):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

For an existing installation, run only the last command. Open `http://localhost:8501`. Keep **Read-only demonstration** selected. The five pages are Command Center, Account Intelligence, Sales Strategy, AE Handoff, and How It Works & Evidence. Existing saved runs are accessible in Command Center. JSON, complete Markdown and standalone AE handoff downloads are local and do not invoke providers.

For inspection without installation, read the labelled [fictional saved report](examples/recruiter_demo/offline_simulation/report.md) or [JSON](examples/recruiter_demo/offline_simulation/run.json). These are synthetic examples, not genuine live research.

Replay needs no credentials. A clean checkout opens the labelled fictional example. Actual private executions and budget records are intentionally excluded from the submission archive. Install direct dependencies with `requirements.txt` if the tested lock file is unsuitable for your platform; dependency versions in the lock file reflect the tested local environment.

## Safe configuration

Copy `.env.example` to `.env` only if `.env` does not already exist. Configure `GROQ_API_KEY`, `TAVILY_API_KEY`, and `GROQ_MODEL=openai/gpt-oss-120b` locally for future live work. Never paste secrets in chat, Git, screenshots or a recording. Runtime API access is independent of the model used by the coding assistant.

```powershell
.\.venv\Scripts\python.exe -m flytbase_bdr.cli --check-config
.\.venv\Scripts\python.exe scripts\acceptance_preflight.py
```

These checks are local and print presence only. Groq uses strict Chat Completions JSON schemas; Tavily is a separate provider. There is no paid-provider fallback. Groq does not expose a reliable billing-plan verification endpoint here: operators must confirm Free status and current dashboard limits. Tavily's normal live path checks its free plan/PAYGO settings before research. Neither check is performed during replay.

## Six-stage architecture and sales judgment

1. **Qualification:** BANT knowns, gaps, questions, priority and completeness.
2. **Deep Account Research:** organisation, investment, developments, investor priorities and existing relationships.
3. **Response Generation:** initial draft plus hypothetical no-reply, interest, budget clarification and stakeholder-referral branches.
4. **Case Study and Material Matching:** runtime-discovered first-party cases, relevance dimensions, evidence and transfer limitations.
5. **Partner Identification:** direct AE versus partner involvement; capability, country activity and availability remain separate.
6. **AE Handoff Summary:** supplied buyer identity, qualification, up to three cleared findings, verified material if available, routing and next actions.

Execution order is **1 -> 2 -> 4 -> 5 -> 3 -> 6** so drafts use the earlier research and decisions. Ordinary Python orchestrates the existing engine; Streamlit and the CLI share it. No database, agent framework, deployment or customer-contact service is required.

BANT (Budget, Authority, Need, Timeline) gives an initial discovery agenda, with deeper enterprise discovery still required. Budget discussion is not approval; a senior title is not purchasing authority; a referral is not a deal; Q3 without a year stays ambiguous. Priority and qualification completeness answer different questions.

Priority rubric: need fit 25, operational pain 20, multiple sites 10, continuous operations 10, senior role 10, referral 5, approved budget 10, explicit authority 5, dated timing 5. Points require supported enquiry signals. Completeness separately counts confirmed BANT dimensions. Unknowns are not negative evidence.

## Evidence, status and budgets

Claims retain public/supplied/inference/unknown provenance. Stable source IDs connect exact quotes to URLs, source access, retrieval dates, publication metadata and reading limitations. Citation existence does not prove entailment: mechanical checks and a separate semantic audit gate downstream use. Search snippets, original-page extraction and full-document reading are distinct. Financial currency/period/scope must be supported; company capex never proves project funding. Missing reporting lines or partner capacity remain unknown.

Partial results remain partial. Unsupported passages and model failures stay inspectable. Deterministic recovery is labelled, not passed off as AI-authored or semantically verified. All email branches need human approval. Exports contain recorded statuses, evidence and limitations; replay never becomes a fresh execution.

The dashboard separates **historical cumulative usage**, **local UTC-day usage**, **unverified provider daily limits**, **new-run allowance**, and **emergency/demo reserves**. The legacy cumulative ceiling may be exhausted even when today's account quota has headroom. Historical entries are never reset. Separately approved cache-only allowances are append-only, bound to one source hash and one new run, protect reserves, enforce daily/request limits, and require another explicit launch approval. None is created by opening the app or reading a plan.

See [the approval procedure](docs/APPROVED_CONTINUATION.md) for the exact offline plan and gated future commands. That continuation has zero Tavily calls, zero retries and a conservative rolling-window scheduler. It forks the source record, preserves qualification/research dates, regenerates affected AI outputs and counts only new usage in the new run. No final live execution is currently authorized.

## Offline validation

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -B -m scripts.simulate_offline --output tmp\rehearsal
```

Tests block external networking and cover all stages, evidence, source-based selection, changed leads, five email branches, failures, budgets, recovery, five-page navigation, exports and replay. Private-record regressions explicitly skip when their confidential fixtures are absent. The fictional integration simulation performs 19 output/export checks; it is not live research or acceptance evidence. See [submission readiness](docs/SUBMISSION_READY.md) for final measured results.

## Submission package

```powershell
.\.venv\Scripts\python.exe -m scripts.package_source
```

The archive at `dist/flytbase-inbound-source.zip` uses a curated allowlist, secret scan, ZIP integrity check and SHA-256 manifest. It includes runnable code, safe config, dependencies, tests, reviewer documentation and a labelled fictional example. It excludes private runs/budgets, `.env`, confidential PDFs, private research packs, virtual environments, caches, backups and internal progress records. Review the archive before manually uploading it. Nothing is published, deployed or submitted automatically.
