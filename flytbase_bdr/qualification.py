"""The AI extracts signals; ordinary Python calculates the score."""
import re
from .models import Lead
from .normalization import expand_verbatim

WEIGHTS = {"need_fit": 25, "operational_pain": 20, "multiple_sites": 10,
           "continuous_operations": 10, "senior_role": 10, "referral": 5,
           "approved_budget": 10, "confirmed_authority": 5, "dated_timeline": 5}
BANT_RATIONALE = ("BANT is a compact first-contact checklist for Budget, Authority, Need and Timeline. "
                  "It exposes gaps without blocking a promising discovery call. Enterprise discovery must "
                  "still establish stakeholders, procurement, technical feasibility and measurable success criteria.")


def normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def qualify(lead: Lead, enquiry: str) -> dict:
    lead = lead.model_copy(deep=True)
    warnings = []
    raw = normalise(enquiry)
    accepted = {}
    for signal in lead.signals:
        signal.quote = expand_verbatim(signal.quote, enquiry)
        if signal.quote.strip() and normalise(signal.quote) in raw:
            accepted[signal.code] = signal.quote
        else:
            warnings.append(f"Rejected {signal.code}: its supporting quote is absent from the enquiry.")
    # Positive qualification requires explicit evidence, not seniority or referral.
    for dimension, code in [(lead.budget, "approved_budget"), (lead.authority, "confirmed_authority"),
                            (lead.need_dimension, "need_fit"), (lead.timeline, "dated_timeline")]:
        dimension.evidence = [q for q in dimension.evidence if q.strip() and normalise(q) in raw]
        if dimension.status == "confirmed" and (code not in accepted or not dimension.evidence):
            dimension.status = "unknown"
            warnings.append(f"{code}: confirmation removed because explicit enquiry evidence is missing.")
        if dimension.status == "negative" and not dimension.evidence:
            dimension.status = "unknown"
            warnings.append(f"{code}: unknown is not negative evidence.")
    budget_quote = normalise(accepted.get("approved_budget", ""))
    if budget_quote and (not re.search(r"\b(approved|allocated|authorized|authorised|secured)\b", budget_quote)
                         or re.search(r"\b(not|no|unapproved|pending)\b", budget_quote)):
        accepted.pop("approved_budget", None)
        lead.budget.status = "unknown"
        warnings.append("A budget discussion, pending approval or negation is not an approved budget.")
    authority_quote = normalise(accepted.get("confirmed_authority", ""))
    if authority_quote and (not re.search(r"(final.*(decision|approv)|sign.off|purchasing authority|decision.maker)", authority_quote)
                            or re.search(r"\b(not|no|pending)\b", authority_quote)):
        accepted.pop("confirmed_authority", None)
        lead.authority.status = "unknown"
        warnings.append("A title does not establish final purchasing authority.")
    # A quarter is ambiguous unless the same timing statement contains a year.
    quarter = re.search(r"\bQ[1-4]\b[^.\n]*", enquiry, flags=re.I)
    if quarter and not re.search(r"\b20\d{2}\b", quarter.group()):
        lead.timeline.status = "ambiguous"
        lead.timeline.uncertainty = "Quarter supplied without a year; no deadline inferred from the run date."
        lead.timeline.questions = list(dict.fromkeys(["Which year does the stated quarter refer to, and is that a budget discussion or deployment target?", *lead.timeline.questions]))
        accepted.pop("dated_timeline", None)
    if "dated_timeline" in accepted and not re.search(r"\b20\d{2}\b", accepted["dated_timeline"]):
        accepted.pop("dated_timeline")
        lead.timeline.status = "ambiguous"
    for dim, code in [(lead.budget, "approved_budget"), (lead.authority, "confirmed_authority"),
                      (lead.need_dimension, "need_fit"), (lead.timeline, "dated_timeline")]:
        if dim.status != "confirmed":
            accepted.pop(code, None)
    score = sum(WEIGHTS[k] for k in accepted)
    completeness = sum(d.status in {"confirmed", "negative"} for d in
                       [lead.budget, lead.authority, lead.need_dimension, lead.timeline]) * 25
    return {"framework": "BANT", "framework_rationale": BANT_RATIONALE, "lead": lead.model_dump(),
            "priority_score": score, "priority_band": "prompt discovery" if score >= 55 else "discovery" if score >= 25 else "clarify fit",
            "priority_explanation": "An engagement priority, not a purchase probability. Unknowns earn no points and are not negative evidence.",
            "qualification_completeness_percent": completeness,
            "completeness_explanation": "25 points per dimension explicitly established, positively or negatively; ambiguous/unknown dimensions earn zero.",
            "score_breakdown": [{"signal": k, "points": WEIGHTS[k], "quote": v} for k, v in accepted.items()],
            "rubric": WEIGHTS, "warnings": warnings}
