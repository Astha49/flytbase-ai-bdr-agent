"""Read-only review of saved run acceptance. Does not call providers or invent research."""
import re
from pathlib import Path

from .evidence import is_flytbase
from .grounding import iter_claims, path_affects_claim, supported
from .models import Run


def _brand(company: str) -> str:
    """Best-effort matching label for a company's own FlytBase references, not a verified alias."""
    group = re.search(r"\(([A-Za-z][A-Za-z0-9&.-]{1,10})\)", company)
    return group.group(1) if group else company.strip()


def own_company_mentions(run: Run) -> list[dict]:
    """Flag a possible EXISTING relationship, never infer which site bought the product."""
    lead = run.stages[0].output.get("lead", {})
    brand = _brand(lead.get("company", ""))
    if len(brand) < 3:
        return []
    name_match = re.compile(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", re.I)
    results = []
    for sid, source in run.sources.items():
        if not is_flytbase(source.url) or source.access not in {"inspected_page", "inspected_pdf"}:
            continue
        if not name_match.search(source.text) or "flytbase" not in source.text.casefold():
            continue
        if not name_match.search(source.title + " " + source.url):
            # First-party navigation advertises unrelated customers. A passing
            # mention on another customer's page is not an account relationship.
            continue
        lines = re.split(r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z])", source.text)
        hits = [line.strip() for line in lines if name_match.search(line)
                and "flytbase" in line.casefold()
                and re.search(r"deploy|collaborat|partner|us(?:es|ing|ed)|integrat|powered", line, re.I)]
        if hits:
            results.append({"source_id": sid, "title": source.title, "url": source.url,
                            "quote": hits[0][:480],
                            "interpretation": "Possible existing company-level FlytBase relationship; division, sites and current scope require discovery."})
            # Require operational wording, not a general list of commodities the company produces.
            scope = re.search(r"[^.\n]*(?:iodine|lithium|copper|nitrate|coal|iron|gold)[ -]+(?:operations?|plants?|sites?|production facilities|extraction|leaching)[^.\n]*", source.text, re.I)
            results[-1]["deployment_scope_evidence"] = scope.group().strip() if scope else ""
            results[-1]["scope_limitation"] = (
                "Compare this explicitly stated operating context with the enquiry; confirm division/site coverage before proposing expansion."
                if scope else "The inspected excerpt does not establish which commodity, division or sites use the deployment.")
    # Variant domain prefixes can refer to the same page; prefer one per normalized path.
    deduped, paths = [], set()
    for item in results:
        path = re.sub(r"^https?://(?:www\.)?", "", item["url"]).rstrip("/")
        if path not in paths:
            deduped.append(item)
            paths.add(path)
    return deduped


def _verified_topic_claims(run: Run, topic_name: str) -> int:
    from .review import cleared_claims
    return sum(row["topic"] == topic_name for row in cleared_claims(
        run.stages[1].output, run.sources, run.input, run.as_of_date))


def assess_run(run: Run) -> dict:
    """Honest acceptance signals for an actual saved run; never modifies its data/status."""
    issues = []
    if run.mode != "live":
        issues.append("This is an offline test fixture, not a live demonstration.")
    if run.status != "complete":
        issues.append(f"Run status is '{run.status}', not complete.")
    for i, stage in enumerate(run.stages, 1):
        if not stage.output:
            issues.append(f"Stage {i} ({stage.name}) has no output.")
        elif stage.status != "complete":
            issues.append(f"Stage {i} ({stage.name}) is {stage.status}; warnings require review.")
    for topic in ["Organisation and reporting lines", "Budget and investment signals", "Investor priorities"]:
        if _verified_topic_claims(run, topic) == 0:
            issues.append(f"No publicly supported, audit-cleared finding for: {topic}.")
    if not run.stages[3].output.get("primary"):
        issues.append("No primary FlytBase case study passed selection; Stage 4 is not submission-ready.")
    email_audit = run.stages[2].output.get("groundedness", {}).get("semantic_review")
    if email_audit != "performed":
        issues.append("Email semantic audit unavailable; do not describe the drafts as verified.")
    case = run.stages[3].output
    own = own_company_mentions(run)
    from .cross_stage import _unsupported_denial
    research_denials = any(_unsupported_denial(c.get("text", "")) for topic in run.stages[1].output.get("topics", [])
                          for c in topic.get("claims", [])) or any(
                              _unsupported_denial(g) for topic in run.stages[1].output.get("topics", []) for g in topic.get("gaps", []))
    if own and research_denials:
        issues.append("Research contradicts an inspected first-party company relationship; reconcile the source evidence and audit added claims before outreach.")
    has_denial = any("no evidence" in str(c).lower() and "flytbase" in str(c).lower()
                     for c in case.get("candidates", []))
    if own and has_denial:
        issues.append("Cross-stage contradiction: inspected FlytBase material discusses this company while case comparison denies any such evidence. Verify site/division scope.")
    if (not run.stages[4].output.get("candidates") and
        (run.stages[4].status != "complete" or run.stages[4].output.get("groundedness", {}).get("semantic_review") != "performed")):
        issues.append("No named implementation partner cleared assessment; current direct-AE routing is a fallback, not verified partner coverage.")
    if len(run.stages[5].output.get("top_three_research_findings", [])) < 3:
        issues.append("Fewer than three public research findings cleared handoff checks.")
    if not run.sources:
        issues.append("No source registry was saved.")
    output = {
        "run_id": run.run_id,
        "mode": run.mode,
        "status": run.status,
        "safe_to_claim_full_acceptance": run.mode == "live" and run.status == "complete" and not issues,
        "stage_statuses": [{"name": s.name, "status": s.status, "warnings": len(s.warnings)} for s in run.stages],
        "blocking_review_items": list(dict.fromkeys(issues)),
        "possible_existing_customer_evidence": own,
        "reported_groq_tokens_in_run": sum(x.get("total_tokens", 0) or 0 for x in run.usage if x.get("provider") == "groq"),
        "reported_tavily_credits_in_run": sum(x.get("credits", 0) or 0 for x in run.usage if x.get("provider") == "tavily"),
        "next_step": "Review source URLs and repair code/claims; a fresh or targeted live execution requires explicit quota approval and manual verification.",
        "limitation": "This read-only checklist is not an independent fact-check or a substitute for the assignment's live run and walkthrough."
    }
    return output


def review_markdown(data: dict) -> str:
    from .reporting import safe_text
    lines = [f"# Saved-run review: {safe_text(data['run_id'])}", "",
             f"**Recorded state:** {data['status']}; mode: {data['mode']}.",
             f"**Full acceptance established:** {'yes' if data['safe_to_claim_full_acceptance'] else 'no'}", "",
             "## Review items"]
    lines += [f"- {safe_text(x)}" for x in data["blocking_review_items"]] or ["- No automatic blockers detected; human evidence review still necessary."]
    lines += ["", "## Existing company-level product references (scope not established)"]
    lines += [f"- {safe_text(x['title'])}: {safe_text(x['quote'])} ({safe_text(x['url'])})"
              for x in data["possible_existing_customer_evidence"]] or ["- None identified in inspected FlytBase source text."]
    lines += ["", f"Groq tokens reported in this run: {data['reported_groq_tokens_in_run']}",
              f"Tavily credits reported in this run: {data['reported_tavily_credits_in_run']}",
              "", safe_text(data['next_step']), "", safe_text(data['limitation'])]
    return "\n".join(lines) + "\n"
