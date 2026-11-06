"""Bounded evidence-safe email recovery after an AI draft fails validation.

Generates new, short questions/proposals from the *current enquiry*, never
re-uses rejected model claims and never asserts independent semantic approval.
This is deliberately a last-resort usable draft, not a fabricated AI output.
"""
import re
from copy import deepcopy
from .grounding import check_claim
from .models import Claim
from .evidence import is_flytbase

BRANCHES = ("initial", "no_reply", "interested", "budget_clarification", "stakeholder_referral")


def _claim(text: str, *, quote: str = "") -> dict:
    supplied = bool(quote)
    return Claim(text=text, kind="supplied" if supplied else "inference", evidence=[],
                 input_quote=quote, uncertainty="" if supplied else "Proposed message or discovery question, not an established buyer fact.",
                 financial_context=None, event_date="").model_dump()


def _raw_field(enquiry: str, field: str) -> str:
    match = re.search(r"^" + re.escape(field) + r"\s*:\s*(.+)$", enquiry, re.I | re.M)
    return match.group(1).strip() if match else ""


def _buyer_company(lead: dict, enquiry: str) -> str:
    stated = str(lead.get("company", "")).strip()
    raw = _raw_field(enquiry, "Company")
    if stated and stated.casefold() in enquiry.casefold():
        return stated[:65]
    if raw:
        return raw[:65]
    return "your operations"


def _safe_subject(branch: str, company: str, enquiry: str) -> str:
    subject = _raw_field(enquiry, "Subject")
    if branch == "initial" and subject:
        return "Re: " + subject[:110]
    prefixes = {"no_reply": "Following up on autonomous inspections",
                "interested": "Planning a drone-inspection discovery call",
                "budget_clarification": "Clarifying inspection project timing",
                "stakeholder_referral": "Coordinating the right inspection stakeholders"}
    return f"{prefixes[branch]} — {company}"[:150]


def _verified_case_hint(lead: dict, sources: dict, enquiry: str, as_of: str, verified_claims=()) -> dict | None:
    """Optional source-backed context, selected generically from inspected originals.

    A related-story footer never qualifies as deployment evidence. This does
    not assert that the specific requested sites already use the technology.
    """
    from .evidence_decisions import article_prose
    company = str(lead.get("company", ""))
    m = re.search(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", company)
    brand = m.group(1) if m else company.split("(")[0].strip()
    if len(brand) < 3 or brand.casefold() not in enquiry.casefold():
        return None
    # Inspection alone is not a semantic approval. Limit optional public copy
    # to evidence already cleared upstream, retaining that original Claim.
    for item in verified_claims:
        public = Claim.model_validate(item)
        if public.kind != "public" or check_claim(public, sources, enquiry, as_of):
            continue
        for ref in public.evidence:
            src = sources.get(ref.source_id)
            if (src and src.access in {"inspected_page", "inspected_pdf"}
                    and "/case-studies/" in src.url and is_flytbase(src.url)
                    and re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", ref.quote, re.I)
                    and ref.quote in article_prose(src.text)):
                return deepcopy(item)
    return None


def generate_safe_drafts(enquiry: str, lead: dict, original: dict, sources: dict, as_of: str, *, verified_claims=()):
    """Replace ONLY drafts missing usable content after original audit/withholding.

    Outputs remain clearly labelled as mechanically checked, deterministic
    recovery copy requiring ordinary human send approval. Never imply that an
    unavailable Groq semantic audit was performed.
    """
    result = deepcopy(original)
    company = _buyer_company(lead, enquiry)
    case_hint = _verified_case_hint(lead, sources, enquiry, as_of, verified_claims)
    subject = _raw_field(enquiry, "Subject")
    context = _raw_field(enquiry, "Context")
    year_unknown = bool(re.search(r"\bQ[1-4]\b", enquiry, re.I)) and not re.search(r"\b20\d{2}\b", enquiry)
    greetings = {
        "initial": ("Thank you for reaching out about autonomous drone inspections.",
                    "Could we schedule a brief discovery call to understand the sites, operational requirements and the approval process?"),
        "no_reply": ("Following up on the inspection enquiry.",
                     "Would a short conversation be useful, or is another time better for your team?"),
        "interested": ("If you'd like to explore the solution further, I suggest a focused technical discussion.",
                       "Could we review your inspection workflows, deployment constraints and who should join from operations and IT?"),
        "budget_clarification": ("It would help to align the discovery process with your internal planning.",
                                 "Is the budget discussion about project approval, or is it intended to set the deployment schedule?"),
        "stakeholder_referral": ("A joint discovery discussion could help clarify site requirements and responsibilities.",
                                 "Would you like to include colleagues responsible for procurement, safety or technical implementation?"),
    }
    restored = []
    for draft in result.get("drafts", []):
        branch = draft.get("branch")
        if branch not in BRANCHES:
            continue
        if (draft.get("review_status") == "checked" and draft.get("paragraphs")
                and draft.get("subject") != "Subject withheld — review required"):
            continue
        first, next_step = greetings[branch]
        paragraphs = [_claim(first)]
        if branch == "initial" and context:
            # A concrete context is exact enquiry input, not purported public data.
            # Quote a bounded original sentence instead of paraphrasing claims.
            sentence = re.split(r"(?<=[.!?])\s+", context)[0].strip()
            if sentence and len(sentence) <= 230:
                paragraphs.append(_claim("Your enquiry says: " + sentence, quote=sentence))
        if case_hint and branch in {"initial", "no_reply"}:
            paragraphs.append(deepcopy(case_hint))
        if branch == "budget_clarification" and year_unknown:
            next_step = "You mentioned Q3 for a budget discussion. Which calendar year does that refer to, and what would happen after that discussion?"
        paragraphs.append(_claim(next_step))
        problems = [p for paragraph in paragraphs for p in check_claim(Claim.model_validate(paragraph), sources, enquiry, as_of)]
        if problems:
            # Never use the recovery output if even its mechanical support fails.
            continue
        draft["paragraphs"] = paragraphs
        draft["subject"] = _safe_subject(branch, company, enquiry)
        draft["review_status"] = "source_limited_fallback"
        restored.append(branch)
    if restored:
        result["safe_recovery"] = {
            "branches": restored,
            "origin": "deterministic post-validation recovery from the supplied enquiry; not AI-authored or AI-semantically-audited",
            "send_approval": "Human approval required; no email was sent.",
            "limitations": "Unsupported public claims from rejected Groq drafts were not reused; optional case context must already have cleared upstream checks. Human review remains required.",
            "case_hint_source_ids": list({ref["source_id"] for draft in result["drafts"]
                                          for paragraph in draft.get("paragraphs", [])
                                          for ref in paragraph.get("evidence", [])})
        }
    return result, restored
