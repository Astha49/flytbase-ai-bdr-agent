"""Explicit, inspectable follow-up progression for a hypothetical new buyer update."""
import re
from .models import EmailDraft, Audit
from .provider import ProviderError
from .providers.groq import GroqProvider
from .grounding import audit_mechanical, iter_claims
from .compact import lead_context, evidence_batch
from . import prompts


def choose_branch(update: str, no_reply=False) -> dict:
    text = update.casefold()
    if no_reply:
        return {"branch": "no_reply", "reason": "No reply after the suggested follow-up interval; add one useful point and an easy next step."}
    if re.search(r"contact|speak (?:to|with)|colleague|introduc|procurement|cc\b", text):
        return {"branch": "stakeholder_referral", "reason": "Buyer redirects to another stakeholder; clarify ownership and request a joint introduction."}
    if re.search(r"budget|funding|fiscal|\bq[1-4]\b|approv", text):
        return {"branch": "budget_clarification", "reason": "Buyer adds budget/timing information; distinguish approval from discussion and clarify any missing year."}
    return {"branch": "interested", "reason": "A new reply invites a useful next step; propose a short agenda and clarify intent without assuming commitment."}


def simulate_followup(run, settings, update, no_reply=False, provider_factory=GroqProvider):
    if not update.strip() and not no_reply:
        raise ValueError("Enter a hypothetical update or select no reply.")
    decision = choose_branch(update, no_reply)
    prior = run.stages[2].output
    matching = next((d for d in prior.get("drafts", []) if d["branch"] == decision["branch"]), None)
    sources = list(dict.fromkeys(r.source_id for _, c in iter_claims(matching or {}) for r in c.evidence))
    combined = run.input + "\nHypothetical buyer update (user supplied):\n" + update
    client = provider_factory(settings, run)
    try:
        draft = client.structured(EmailDraft, prompts.EMAILS + "\nReturn ONE draft for selected_branch only. Adapt the questions and next step to the hypothetical new update; do not imply a real reply was received. Keep branch hypothetical=true.",
                                  {"enquiry": run.input, "hypothetical_update": update, "selected_branch": decision["branch"],
                                   "progression_reason": decision["reason"], "qualification": lead_context(run.stages[0].output),
                                   "previous_branch": matching, "sources": evidence_batch(run.sources, sources, settings)},
                                  "followup:simulation", max_tokens=1200)
        if draft.branch != decision["branch"]:
            raise ProviderError("Follow-up branch did not match the progression rule; no draft accepted.")
        draft.hypothetical = True
        data = draft.model_dump()
        findings = audit_mechanical(data, run.sources, combined, run.as_of_date)
        review = client.structured(Audit, prompts.AUDIT,
                                   {"enquiry": combined, "output": data, "sources": evidence_batch(run.sources, sources, settings, data)},
                                   "audit:followup")
        findings += [f.model_dump() for f in review.findings]
        return {"mode": "hypothetical simulation; no actual buyer response asserted", "update": update,
                "decision": decision, "draft": data, "groundedness_findings": findings,
                "status": "partial" if findings else "complete"}
    finally:
        if hasattr(client, "close"):
            client.close()
