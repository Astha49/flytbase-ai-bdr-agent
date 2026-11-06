"""Human-friendly, read-only acceptance guide based ONLY on recorded evidence.

A green code test is not proof of an acceptable live research run. This helper
never calls external providers and never modifies the user's run.
"""
from __future__ import annotations

from .diagnostics import _verified_topic_claims, own_company_mentions
from .models import Run


def check_requirements(run: Run) -> list[dict[str, str]]:
    """Six assignment checks with plain-language reasons and next actions.

    State is deliberately conservative: a stage marked 'complete' is still
    independently inspected for missing assignment deliverables.
    """
    stages = run.stages
    if len(stages) != 6:
        return [{"name": "All six assignment steps", "state": "needs_work",
                 "details": "The saved run does not contain all six steps.",
                 "next": "Review the run file and execute the missing steps."}]
    q, research, emails, cases, partners, handoff = [s.output or {} for s in stages]
    lead = q.get("lead") or {}
    priority = q.get("priority_score")
    questions = [name for name in ("budget", "authority", "timeline")
                 if (lead.get(name) or {}).get("status") in {"unknown", "ambiguous"}]
    items = []

    def add(name, done, details, next_action, review=False):
        reasons = ["Priority and buying readiness answer different questions.",
                   "Financial and organisation evidence shape the account strategy and prevent invented budgets or reporting lines.",
                   "Unverified claims or assumed buyer replies can mislead a senior customer.",
                   "A different commodity or country does not establish suitability for these sites.",
                   "Commercial ownership, local capability and current partner capacity are separate decisions.",
                   "A salesperson needs three distinct supported findings and a usable next step."]
        items.append({"name": name, "state": "ready" if done else ("review" if review else "needs_work"),
                      "details": details, "why": reasons[len(items)], "next": next_action})

    q_ready = stages[0].status == "complete" and isinstance(priority, int) and bool(lead)
    add("1. Check the lead", q_ready,
        (f"The system scored this lead {priority}/100. " if isinstance(priority, int) else "No lead score was saved. ")
        + ("The buyer still needs to confirm: " + ", ".join(questions) + "." if questions else "No missing budget/decision/timing questions recorded."),
        "The lead can remain high priority even when the buyer has not confirmed a budget. Ask the open questions on the first call." if q_ready else "Check why lead extraction or scoring failed.")

    topics = ["Organisation and reporting lines", "Budget and investment signals", "News and strategic announcements",
              "Investor priorities", "Corporate changes and customer relationships"]
    topic_counts = {name: _verified_topic_claims(run, name) for name in topics}
    missing = [name for name, n in topic_counts.items() if n == 0]
    research_ok = stages[1].status == "complete" and not missing
    add("2. Research the company", research_ok,
        f"Evidence-backed findings in {len(topics)-len(missing)} of {len(topics)} required areas. "
        + ("Still missing reliable findings for: " + "; ".join(missing) + "." if missing else "All five areas contain checked findings."),
        "Find original company reports and investor documents; verify dates, reporting lines, figures and currencies. Never replace missing facts with guesses.")

    drafts = emails.get("drafts") or []
    branches = {x.get("branch") for x in drafts}
    expected = {"initial", "no_reply", "interested", "budget_clarification", "stakeholder_referral"}
    email_ok = stages[2].status == "complete" and branches == expected and emails.get("groundedness", {}).get("semantic_review") == "performed"
    add("3. Prepare reply emails", email_ok,
        f"{len(branches & expected)} of 5 reply situations drafted. " +
        ("Final wording/evidence check passed." if email_ok else "Some drafts or the final evidence check need review."),
        "Check that drafts use verified facts, ask useful questions, and never claim the buyer replied or an email was sent.")

    selected = cases.get("primary")
    candidate_title = (selected or {}).get("candidate", {}).get("title") or ""
    case_ok = stages[3].status == "complete" and bool(candidate_title)
    relationship = bool(own_company_mentions(run))
    add("4. Choose a relevant case study", case_ok,
        (f"Chosen example: {candidate_title}." if candidate_title else "No case study passed the saved evidence checks.")
        + (" A FlytBase source mentions a possible existing relationship with this same company; confirm which site." if relationship else ""),
        "Use inspected FlytBase articles, score relevance, and cross-check both the referring company and any existing customer relationship. Do not hard-code a winner.")

    motion = partners.get("recommended_motion")
    fallback = any(term in str(partners.get("decision_basis", "")).lower()
                   for term in ("fallback", "did not complete", "policy"))
    partner_ok = stages[4].status == "complete" and motion in {"direct_ae", "partner_led"} and not fallback
    add("5. Decide who should follow up", partner_ok,
        ("An account executive should lead the deal." if motion == "direct_ae" else
         "A local partner is proposed to lead." if motion == "partner_led" else "No follow-up owner selected.")
        + (" The saved choice was a safety fallback, not a finished partner check." if fallback else ""),
        "Check genuine partner capabilities and country coverage. A direct account executive is an acceptable answer if local support is unverified.")

    findings = handoff.get("top_three_research_findings") or []
    handoff_ok = stages[5].status == "complete" and len(findings) >= 3 and bool(handoff.get("suggested_next_action")) and bool(handoff.get("recommended_case_study"))
    add("6. Give the sales team a handoff", handoff_ok,
        f"{len(findings)} of 3 requested research highlights are included. "
        + ("The case study and next action are recorded." if handoff.get("recommended_case_study") else "No verified case study appears in the handoff."),
        "Refresh the handoff only after the research and case study are supported by original sources.")
    return items


def submission_checklist(run: Run) -> list[dict[str, str]]:
    """User actions, not fabricated completion of an external submission."""
    return [
        {"item": "Working system", "status": "Test locally", "details": "Share the source code or a repository link. The reviewer must be able to inspect the logic."},
        {"item": "Actual live results", "status": "Needs review" if run.status != "complete" else "Inspect sources", "details": "Export a real six-step run. A saved partial run does not prove all six steps were verified."},
        {"item": "8–12 minute screen recording", "status": "Record yourself", "details": "Show the architecture, a live run, BANT, one design choice and one limitation. This app cannot record the video."},
    ]
