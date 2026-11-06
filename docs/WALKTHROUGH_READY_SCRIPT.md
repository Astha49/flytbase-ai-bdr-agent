# Walkthrough narration: approximately 10–11 minutes

This is a script to rehearse and adapt, **not a recorded video**. Allow about 1,200 spoken words plus clicks. Use the actual displayed findings, not memorised facts. Read bracketed instructions silently. Hide `.env`, keys and private terminal history before recording.

**Today: offline rehearsal only.** Keep read-only mode selected. Say “synthetic simulation” for the public fixture and “saved partial live result” for the historical private run. The genuine-live paragraph below may be used only after explicit approval, a feasible resource allocation and a real execution. Never claim all six stages passed just because the simulation passed. See [SUBMISSION_READY.md](SUBMISSION_READY.md) for the current blockers and commands.

## 0:00–0:50 — problem and product

[Show the enquiry and the executive overview. Name the displayed mode immediately.]

“This is a local inbound-sales workbench for FlytBase. A representative pastes one customer enquiry. The application prepares qualification, account research, response drafts, relevant materials, a routing recommendation and a sales handoff. The enquiry is the only business input. API credentials and model choice are separate configuration.

“The goal is to make a useful first sales decision with evidence, while keeping unknowns visible. A senior operations buyer may have a compelling problem without an approved budget or established buying process. The system should help us earn a discovery conversation rather than pretend the opportunity is ready to close.”

## 0:50–2:00 — architecture and one design choice

[Show README diagram, then `workflow.py`, `models.py`, `evidence.py` and the two provider modules.]

“Streamlit is the interface. Ordinary Python controls the workflow, so the same core runs from a command line. Pydantic defines and validates the shape of the records. Groq handles structured extraction and synthesis. Tavily separately searches and extracts public sources. Groq is not being asked to use OpenAI's hosted web-search tool.

“My main design choice was to separate retrieval from synthesis. We first collect source text in a shared registry. Later stages reuse it rather than paying to rediscover the same page. The logical order is qualification, research, materials, routing, emails and handoff. Materials and routing come before the emails because the drafts should have that context.

“Python calculates the qualification and relevance scores. The model proposes facts and interpretations; it does not choose an unexplained score. Successful structured responses are checkpointed, and a targeted continuation can reuse matching work.”

## 2:00–2:45 — execution, honestly labelled

[For a separately approved cached live continuation: follow APPROVED_CONTINUATION.md, select Protected live execution and the approved source-bound allowance, then press Run approved cached continuation once. Show its new run ID and genuine stage changes. Explain that qualification and dated research are reused while affected AI outputs are regenerated. Never show credentials. A genuinely fresh research demonstration requires its own later approved plan.]

“I am starting a new AI continuation using previously inspected research now. These changing stage statuses and this new run ID belong to requests made by this application. The work is bounded by request, token and search limits. The application does not enable billing, switch to a paid provider or send emails. If a request fails or evidence is missing, that remains visible.”

[OFFLINE REHEARSAL REPLACEMENT:]

“I am showing a saved result without making API calls. This public example is a fictional simulation. It demonstrates workflow behaviour and exports, not current web research. The private historical live run remains partial; I am not presenting either as a fresh successful execution.”

## 2:45–4:00 — qualification and sales framework

[While a separately approved genuine run executes, show `qualification.py`; otherwise show saved qualification in Command Center.]

“BANT stands for Budget, Authority, Need and Timeline. I chose it because it is a small, understandable checklist for first-contact discovery. It is not a complete enterprise-sales methodology. Later discovery still needs procurement, stakeholders, technical feasibility and measurable success criteria.

“For the assignment enquiry, there is explicit operational need: three large, continuously operating lithium sites and expensive, hazardous contracted work. A budget discussion is not an approved budget. A senior title is not proof of final purchasing authority. The referral gives context without proving approval or an active deal.

“Q3 has no year. The application preserves that ambiguity instead of deciding that the buyer must mean the next quarter or next year. Priority and qualification completeness are separate. An enquiry can deserve prompt discovery even while budget, authority and timing are unknown. Here I would ask who owns the business case, which year the quarter means and what a successful pilot should demonstrate.”

## 4:00–5:35 — research verification

[Open Account Intelligence, then How It Works & Evidence. Choose an actual inspected finding and its passage. Do not read a synthetic financial figure as a fact about SQM.]

“Queries come from the enquiry's company, domain, country, industry and operational need. The research covers organisational structure, financial signals, recent developments, investor priorities and corporate or customer changes. It prefers company publications, investor relations and primary filings.

“For this finding, I can trace the conclusion to a stable source ID, a URL and the retrieved passage. I check the publication date separately from the reporting period. For a financial claim, I also check currency, units and whether it concerns the group, a subsidiary or this project. Company capital expenditure is a signal about investment priorities, never proof of a drone budget.

“A search excerpt does not mean the full document was read. The registry records access level, truncation and PDF page information. A source that cannot be accessed stays a gap. If public reporting does not establish the named buyer's manager, the system should say that and offer only a labelled stakeholder hypothesis.”

## 5:35–6:45 — case comparison and existing relationships

[Show the two actual candidate cards, score breakdowns and evidence. Read the real winner only after inspecting it. For the public demo, say these are fictional candidates.]

“The application discovers FlytBase materials at runtime and compares them on industry, use case, operating context, geography, referral and same-company relevance. A candidate needs inspected support for the core industry and use case. Unsupported dimensions receive zero; a model's confident wording is not enough.

“The Anglo American referral should be investigated, but it does not automatically win the comparison. If retrieved evidence establishes an existing SQM iodine deployment, that is relevant account context. It does not prove these proposed lithium sites already use FlytBase. I would clarify division, site and deployment scope before calling the opportunity an expansion. Results from a different mine, mineral or country are examples, not promised outcomes.”

## 6:45–7:35 — ownership and partner support

[Show Who follows up, country evidence, responsibilities and availability limitation.]

“For a multi-site enterprise opportunity, direct Account Executive ownership can make sense while a local integrator supports implementation. Commercial ownership and technical delivery are separate responsibilities.

“A named partner needs evidence of FlytBase ecosystem participation, relevant capability and service in the actual country. Operating somewhere in Latin America does not establish Chile coverage. Even a published Chile deployment does not prove current capacity or availability. If those checks cannot be completed, the system should keep an AE owner and recommend verifying local support rather than manufacture a partner assignment.”

## 7:35–8:35 — five email scenarios

[Open Sales Strategy; read a short section of the actual initial draft, then show triggers for the other branches.]

“These are reviewable drafts. Nothing is sent. The initial response should recognise the operational problem, use a small amount of supported context and ask only a few useful questions. The next step should be easy for a senior buyer to accept.

“There are five scenarios: initial response, no reply, interest in a discussion, budget clarification and stakeholder referral. Each has a trigger, a reason for the message and what changes if the buyer responds. Follow-ups are explicitly hypothetical. The system must not pretend Rodrigo replied. If new information arrives, the next message should address it rather than repeat the original qualification questions. I also check that no draft invents ROI, pricing, deployment dates or regulatory assurances.”

## 8:35–9:35 — AE handoff and exports

[Show AE Handoff, then JSON/Markdown downloads. Compare the run ID in the UI and downloaded result.]

“The handoff is designed to let a salesperson act immediately: buyer context, operational problem, priority, qualification gaps, three distinct supported research highlights, a selected case, ownership, discovery questions and a next action.

“Only findings that cleared the recorded checks can become the top highlights. If there are only two, the application must not invent a third. The briefing keeps assumptions and limitations from the earlier stages. In the offline simulation, we also verified that a legitimate discovery caveat stays visible without making an otherwise complete briefing look like a processing failure.

“These downloads are generated from the same run object as the interface. The JSON is inspectable data; Markdown is the readable version. Recruiters can open the supplied fictional report directly or replay it without any API keys.”

## 9:35–10:45 — strengths, limitations and AI use

[Show the measured test result, execution mode and one actual unresolved limitation.]

“The strengths are explicit orchestration, transparent scores, shared evidence, bounded resource usage and honest failure states. Read-only replay consumes no model or search credits. Live execution requires deliberate approval, and resuming preserves the original historical record.

“The limits matter. Public sites can be inaccessible, large filings may be inspected only in part, and an automated semantic audit can miss a misleading interpretation. Offline tests show how the code behaves on fixtures; they cannot prove live source quality or provider access. The current live acceptance and recording status is stated in the submission checklist, not inferred from green test results.

“I used an AI coding assistant to help implement and test this system. I can explain the workflow, rubrics and evidence checks. The fictional demo was deliberately authored as test data. Actual live outputs must come from the application and be inspected before I present them as research.”

## Before recording or sharing

Current repair decision to explain during the architecture/case segment: the old full case JSON was truncated. Python now assembles cited candidates and asks Groq for only four short advisory fields; evidence-gated scoring and a separate audit determine acceptance. A fallback is labelled provisional, not AI-audited. Later relationship claims need their own audit rather than inheriting an earlier label.

For the limitation segment use the current [reviewer guide](REVIEWER_GUIDE.md): latest real run is partial, legacy repair allowance is exhausted; no new allowance or live request is currently authorised. Future source-bound approvals are separate and append-only. Do not recite old token balances or imply 38,000 demo tokens remain. Read-only replay is available now; genuine processing needs a separately approved feasible plan. Include these explanations within the 10–11-minute target, rather than adding an extra demonstration.

- Rehearse at a readable zoom; aim for 10–11 minutes and keep the final video within 8–12 minutes.
- Replace bracketed directions with observations from the displayed run. Do not recite an unverified winner, partner, financial figure or reporting line.
- If live work takes longer than expected, explain architecture and checks while it runs. If it fails, show the real limitation; do not edit a replay into the video as a fresh execution.
- A conditional script does not authorise API usage. Current instructions prohibit live execution and ceiling changes. No video or submission is claimed by this document.
