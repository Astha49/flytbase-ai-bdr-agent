"""Buyer-facing drafts only retain paragraphs that cleared the recorded checks."""
from copy import deepcopy
import re
from .grounding import check_claim, path_affects_claim, unresolved_paths
from .models import Claim


def introduces_timing_year(paragraph, enquiry, branch=""):
    """Keep public reporting periods separate from an undated buyer milestone."""
    if not (re.search(r"\bQ[1-4]\b", enquiry, re.I) and not re.search(r"20\d{2}", enquiry)):
        return False
    text = paragraph["text"]
    # This exemption only identifies public reporting context. Source/semantic
    # validation still decides whether that assertion may be used at all.
    if (paragraph["kind"] == "public" and paragraph.get("evidence")
            and re.search(r"\bresults|\bearnings|\breport(?:ing)?\b", text, re.I)
            and not re.search(r"your.{0,30}(?:budget|timing|deadline)|project.{0,25}(?:deadline|timeline)|approved budget", text, re.I)):
        return False
    return bool(re.search(r"20\d{2}", text) and (
        re.search(r"\bQ[1-4]\b.{0,100}20\d{2}|20\d{2}.{0,40}\bQ[1-4]\b", text, re.I)
        or (branch == "budget_clarification" and paragraph["kind"] in {"inference", "unknown"})))


def checked_drafts(data, sources, enquiry, as_of):
    result = deepcopy(data)
    findings = result.get("groundedness", {}).get("mechanical_and_semantic_findings", [])
    errors = unresolved_paths(findings)
    warnings, withheld = [], []
    for i, draft in enumerate(result.get("drafts", [])):
        prefix = f"drafts.{i}"
        original = deepcopy(draft)
        safe = []
        for j, paragraph in enumerate(draft["paragraphs"]):
            path = f"{prefix}.paragraphs.{j}"
            problems = check_claim(Claim.model_validate(paragraph), sources, enquiry, as_of)
            if introduces_timing_year(paragraph, enquiry, draft["branch"]):
                problems.append("The draft suggests an unprovided timing year; ask which year instead.")
            if any(path_affects_claim(error, path) for error in errors):
                problems.append("Recorded grounding review rejected this paragraph.")
            if draft["branch"] == "initial" and re.search(
                r"as we (?:agreed|discussed)|following our (?:call|meeting)|thank\w* for (?:our|the) (?:call|meeting)", paragraph["text"], re.I
            ) and paragraph["text"] not in enquiry:
                problems.append("An initial response cannot invent an earlier call or agreement.")
            if problems:
                warnings.append(f"{draft['branch']}: unsupported paragraph withheld from the draft.")
            else:
                safe.append(paragraph)
        subject_bad = any(path_affects_claim(error, prefix + ".subject") for error in errors)
        if subject_bad:
            draft["subject"] = "Subject withheld — review required"
            warnings.append(f"{draft['branch']}: unsupported subject withheld.")
        draft["paragraphs"] = safe
        draft["review_status"] = "needs_review" if len(safe) != len(original["paragraphs"]) or subject_bad else "checked"
        if draft["review_status"] == "needs_review":
            withheld.append({"branch": draft["branch"], "status": "WITHHELD — not an approved sales draft", "original": original})
        if not safe:
            warnings.append(f"{draft['branch']}: no safe email body remains; rewrite and audit before use.")
        if len(" ".join(p["text"] for p in safe).split()) > 140:
            warnings.append(f"{draft['branch']}: shorten the message for a senior buyer.")
    if withheld:
        result["withheld_content"] = withheld
    if re.search(r"\bQ[1-4]\b", enquiry, re.I) and not re.search(r"20\d{2}", enquiry):
        copy = " ".join(p["text"] for draft in result.get("drafts", []) for p in draft["paragraphs"])
        if not re.search(r"which year|what year|year.{0,35}refer|refer.{0,35}year", copy, re.I):
            warnings.append("The timing year is still unknown and no retained draft asks for clarification.")
    return result, list(dict.fromkeys(warnings))
