"""UI and Markdown exports share one renderer; JSON is the same saved run."""
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from .models import Run, Source

_SAVE_LOCK = threading.RLock()


class RunSaveError(OSError):
    """A safe user-facing save error; the last good file is never truncated."""


def _atomic_text(path: Path, data: str):
    # Unique names avoid collisions between a UI save and worker checkpoint.
    # Close our handle before Windows rename; indexers/previewers may still
    # hold a short-lived handle without FILE_SHARE_DELETE.
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", suffix=".pending", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except PermissionError:
        raise RunSaveError(f"Windows blocked writing a checkpoint in {path.parent.name}. Verify folder write permission and file/sync locks. The existing saved record was not truncated.") from None
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise RunSaveError(
                    f"Windows blocked saving {path.name}. Last good file is intact; new content is retained in {temporary.name} "
                    f"inside {path.parent.name}. Close file previews/sync locks and verify folder write permission before recovery. "
                    "No model call should be repeated just to save this checkpoint.") from None
            time.sleep(.05 * (2 ** attempt))


def sanitise(value):
    secrets = [os.environ.get(k, "") for k in ["OPENAI_API_KEY", "GROQ_API_KEY", "TAVILY_API_KEY"]]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"\b(?:sk-|gsk_|tvly-)[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"api.key|authorization|password|secret", k, re.I) else sanitise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitise(v) for v in value]
    return value


def json_export(run: Run) -> str:
    return json.dumps(sanitise(run.model_dump(mode="json")), ensure_ascii=False, indent=2)


def handoff_export(run: Run) -> str:
    """A standalone, source-linked brief from this exact recorded execution."""
    header = (f"# AE handoff — {safe_text(run.run_id)}\n\n"
              f"Recorded mode: **{run.mode}** · Run status: **{run.status}** · As of: {run.as_of_date}\n\n"
              "Export of recorded results, not a new execution. Drafts require human approval.\n\n"
              "## Upstream status\n\n" + "\n".join(f"- {s.name}: **{s.status}**" for s in run.stages) + "\n\n")
    return sanitise(header + stage_markdown(run.stages[5], run.sources)
                    + "\n## Run limitations\n\n" + _bullets(run.warnings))


def label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def safe_text(value) -> str:
    # Retrieved content cannot inject HTML or misleading Markdown links into the app.
    text = str(value).replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_[\]#])", r"\\\1", text)


def source_link(sid: str, sources: dict[str, Source]) -> str:
    from urllib.parse import quote
    source = sources.get(sid)
    return f"[{sid}]({quote(source.url, safe=':/?=&%+~@!;')})" if source else f"UNKNOWN SOURCE `{sid}`"


def render_value(value, sources: dict[str, Source], depth=3) -> str:
    if value is None:
        return "Not established.\n"
    if isinstance(value, dict) and {"text", "kind", "evidence"}.issubset(value):
        citations = " ".join(source_link(r["source_id"], sources) for r in value["evidence"])
        out = f"**{value['kind'].upper()}** — {safe_text(value['text'])} {citations}\n\n"
        if value.get("input_quote"):
            out += f"> Enquiry: {safe_text(value['input_quote'])}\n\n"
        for ref in value["evidence"]:
            out += f"> {source_link(ref['source_id'], sources)} evidence: {safe_text(ref['quote'])}\n\n"
        if value.get("uncertainty"):
            out += f"Uncertainty: {safe_text(value['uncertainty'])}\n\n"
        if value.get("financial_context"):
            out += "Financial context: " + "; ".join(f"{label(k)}: {safe_text(v)}" for k, v in value["financial_context"].items()) + "\n\n"
        if value.get("event_date"):
            out += f"Event date: {safe_text(value['event_date'])}\n\n"
        return out
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            title = f"{'#' * min(depth, 6)} {label(key)}" if isinstance(child, (dict, list)) else f"**{label(key)}**"
            if key == "source_id" and isinstance(child, str):
                body = source_link(child, sources)
            else:
                body = render_value(child, sources, depth + 1)
            parts.append(f"{title}\n\n{body}\n")
        return "\n".join(parts)
    if isinstance(value, list):
        if not value:
            return "None recorded.\n"
        if all(not isinstance(v, (dict, list)) for v in value):
            return "\n".join(f"- {safe_text(v)}" for v in value) + "\n"
        return "\n".join(f"**Item {i+1}**\n\n{render_value(v, sources, depth)}" for i, v in enumerate(value))
    return safe_text(value) + "\n"


def _bullets(items):
    """Short human-readable list for a sales walkthrough, not nested JSON-style headings."""
    if not items:
        return "_Not established._\n\n"
    return "".join(f"- {safe_text(item)}\n" for item in items) + "\n"


def _claim_summary(claim, sources):
    """Render claims visibly labelled by provenance while retaining source links."""
    if not isinstance(claim, dict):
        return safe_text(claim)
    references = " ".join(source_link(ref.get("source_id", ""), sources)
                          for ref in claim.get("evidence", []))
    kind = claim.get("kind", "unknown")
    text = safe_text(claim.get("text", "Not established"))
    item = f"**{safe_text(kind.upper())}:** {text}"
    if references:
        item += f" {references}"
    if claim.get("uncertainty") and claim["uncertainty"] not in {"none", ""}:
        item += f" _(Uncertainty: {safe_text(claim['uncertainty'])})_"
    return item


def _claims(claims, sources):
    if not claims:
        return "_No verified findings recorded._\n\n"
    return "".join(f"- {_claim_summary(c, sources)}\n" for c in claims) + "\n"


def _simple_properties(data):
    if not isinstance(data, dict):
        return f"{safe_text(data)}\n\n"
    return "".join(f"- **{label(k)}:** {safe_text(v) if v else 'Not established'}\n"
                   for k, v in data.items()) + "\n"


def _warnings(stage):
    if not stage.warnings:
        return ""
    # Place warnings after the useful output rather than before it.
    return f"\n### Review warnings ({len(stage.warnings)})\n\n" + _bullets(stage.warnings)


def stage_markdown(stage, sources, include_warnings=True):
    """Concise audience-facing report. The full original JSON remains available in the UI."""
    out = (f"**Status:** {safe_text(stage.status)}  ·  "
           f"**Elapsed:** {stage.elapsed_seconds:.1f}s  ·  "
           f"**Origin:** {safe_text(stage.execution_origin)}\n\n")
    data = stage.output
    if not data:
        return out + "_No output produced._\n" + _warnings(stage)

    if stage.name == "Qualification":
        lead = data["lead"]
        out += (f"### {safe_text(data.get('framework', 'BANT'))} qualification\n\n"
                f"{safe_text(data.get('framework_rationale', ''))}\n\n"
                f"**Engagement priority:** {data.get('priority_score', 0)}/100"
                f" ({safe_text(data.get('priority_band', ''))})  ·  "
                f"**Qualification completeness:** {data.get('qualification_completeness_percent', 0)}%\n\n"
                f"**Fit:** {safe_text(lead.get('fit', 'unknown'))} — "
                f"{safe_text(lead.get('fit_reason', ''))}\n\n"
                "#### Known information\n\n" + _bullets(lead.get("knowns", [])))
        for key, title in (("budget", "Budget"), ("authority", "Authority"),
                           ("need_dimension", "Need"), ("timeline", "Timeline")):
            dimension = lead[key]
            out += f"#### {title}: {safe_text(dimension['status'])}\n\n"
            if dimension.get("evidence"):
                out += "**Evidence:** " + "; ".join(safe_text(x) for x in dimension["evidence"]) + "\n\n"
            if dimension.get("uncertainty"):
                out += f"**Uncertainty:** {safe_text(dimension['uncertainty'])}\n\n"
            if dimension.get("questions"):
                out += "**Discovery questions**\n\n" + _bullets(dimension["questions"])
        out += "#### Priority score breakdown\n\n| Signal | Points | Enquiry evidence |\n|---|---:|---|\n"
        for row in data.get("score_breakdown", []):
            cell = lambda v: safe_text(v).replace("|", "\\|").replace("\n", " ")
            out += f"| {cell(label(row['signal']))} | {row['points']} | {cell(row['quote'])} |\n"
        out += ("\n_The priority score is not a purchase probability. Completeness records "
                "how many BANT dimensions were established._\n\n")
    elif stage.name == "Deep Account Research":
        out += "### Account research\n\n"
        for topic in data.get("topics", []):
            out += f"#### {safe_text(topic.get('name', 'Research area'))}\n\n"
            out += _claims(topic.get("claims", []), sources)
            if topic.get("gaps"):
                out += "**Unresolved:**\n\n" + _bullets(topic["gaps"])
        out += "#### Recommended positioning\n\n" + _claims(data.get("positioning", []), sources)
        out += "#### Stakeholder hypotheses (not confirmed reporting lines)\n\n" + _claims(data.get("stakeholder_hypothesis", []), sources)
        if data.get("conflicts"):
            out += "#### Conflicts\n\n" + _bullets(data["conflicts"])
    elif stage.name == "Response Generation":
        out += "_These are unsent drafts. Follow-up branches are hypothetical buyer scenarios._\n\n"
        for draft in data.get("drafts", []):
            out += f"### {label(draft['branch'])}" + (" — hypothetical" if draft.get("hypothetical") else " — initial") + "\n\n"
            out += f"**Subject:** {safe_text(draft['subject'])}\n\n"
            for paragraph in draft.get("paragraphs", []):
                refs = " ".join(source_link(r.get("source_id", ""), sources)
                                for r in paragraph.get("evidence", []))
                out += safe_text(paragraph["text"]) + (f" {refs}" if refs else "") + "\n\n"
            out += (f"**Trigger:** {safe_text(draft.get('trigger', ''))}  \n"
                    f"**Why this message:** {safe_text(draft.get('why_this_message', ''))}  \n"
                    f"**Next step:** {safe_text(draft.get('if_buyer_responds', ''))}\n\n")
        if data.get("limitations"):
            out += "#### Email limitations\n\n" + _bullets(data["limitations"])
    elif stage.name == "Case Study and Material Matching":
        primary = data.get("primary")
        if primary:
            candidate = primary.get("candidate", {})
            out += f"### Selected case study: {safe_text(candidate.get('title', ''))}\n\n"
            out += f"**Score:** {primary.get('score', 0)}/100 · " + source_link(candidate.get("source_id", ""), sources) + "\n\n"
            out += _claim_summary(candidate.get("relevance", {}), sources) + "\n\n"
            if primary.get("excluded_dimensions"):
                out += "_The following proposed matches were excluded from scoring because their evidence was insufficient:_\n\n"
                out += _bullets(primary["excluded_dimensions"])
        else:
            out += "### No case study selected\n\nThe current candidates did not pass evidence verification; do not present an unverified case as the winner.\n\n"
        audited = data.get("groundedness", {}).get("semantic_review") == "performed"
        out += "#### Candidate comparison\n\n| Candidate | Score | Evidence review eligibility |\n|---|---:|---|\n"
        for row in data.get("comparison", []):
            cand = row.get("candidate", {})
            title = safe_text(cand.get("title", "Unknown")).replace("|", "\\|")
            eligibility = ("Yes" if audited else "Provisional: semantic review unavailable") if row.get("eligible") else "No"
            out += f"| {title} | {row.get('score', '—')}/100 | {eligibility} |\n"
        out += "\n"
        for row in data.get("comparison", []):
            cand = row.get("candidate", {})
            out += f"**{safe_text(cand.get('title', 'Case study'))}** — {source_link(cand.get('source_id', ''), sources)}\n\n"
            if row.get("rejection_reasons"):
                out += "_Verification issues:_\n\n" + _bullets(row["rejection_reasons"])
            if row.get("excluded_dimensions"):
                out += "_Excluded from matching score:_\n\n" + _bullets(row["excluded_dimensions"])
            if cand.get("limitations"):
                out += "_Transfer limitations:_\n\n" + _bullets(cand["limitations"])
            if cand.get("own_company_expansion_assessment"):
                out += "_Existing-customer / expansion assessment:_ " + safe_text(cand["own_company_expansion_assessment"]) + "\n\n"
        if data.get("possible_existing_company_relationship"):
            out += "#### Possible existing customer-level deployment (site scope unconfirmed)\n\n"
            for item in data["possible_existing_company_relationship"]:
                out += "- " + source_link(item["source_id"], sources) + " — " + safe_text(item["quote"]) + "\n"
            out += "\n_Confirm whether the inbound enquiry concerns expansion, a separate division or different sites._\n\n"
        if data.get("referral_findings"):
            out += "#### Referral connection\n\n" + _claims(data["referral_findings"], sources)
        if data.get("gaps"):
            out += "#### Unresolved gaps\n\n" + _bullets(data["gaps"])
    elif stage.name == "Partner Identification":
        out += f"### Recommended motion: {safe_text(str(data.get('recommended_motion', 'unverified')).replace('_', ' '))}\n\n"
        out += _simple_properties({k: data.get(k) for k in ["commercial_owner", "selected_partner_name", "implementation_owner", "required_partner_type", "next_action", "decision_basis"] if k in data})
        if data.get("rationale"):
            out += "#### Evidence and rationale\n\n" + _claims(data["rationale"], sources)
        if data.get("candidates"):
            out += "#### Partner candidates\n\n"
            for partner in data["candidates"]:
                out += f"**{safe_text(partner.get('name', 'Unconfirmed'))}** ({safe_text(partner.get('partner_type', ''))})\n\n"
                out += _claim_summary(partner.get("geographic_coverage", {}), sources) + "\n\n"
        if data.get("gaps"):
            out += "#### What still needs verification\n\n" + _bullets(data["gaps"])
    elif stage.name == "AE Handoff Summary":
        from .identity import handoff_identity
        identity, recovered = handoff_identity(data)
        out += "### Buyer context\n\n" + _simple_properties(identity)
        if recovered:
            out += "_Missing handoff identity fields are displayed from the original enquiry qualification; saved JSON is unchanged._\n\n"
        out += f"**Business problem:** {safe_text(data.get('business_problem_and_desired_outcome', ''))}\n\n"
        q = data.get("qualification", {})
        out += (f"**Priority:** {q.get('priority_score', '—')}/100  ·  "
                f"**BANT completeness:** {q.get('qualification_completeness_percent', '—')}%\n\n"
                "#### Verified research highlights\n\n")
        out += _claims(data.get("top_three_research_findings", []), sources)
        case = data.get("recommended_case_study")
        out += "#### Recommended case study\n\n"
        if case and case.get("candidate"):
            out += f"{safe_text(case['candidate'].get('title', ''))} — {source_link(case['candidate'].get('source_id', ''), sources)}\n\n"
        else:
            out += "_Not verified; do not send an unverified case study._\n\n"
        if data.get("possible_existing_company_relationship"):
            out += "#### Existing-company relationship to verify\n\n"
            for item in data["possible_existing_company_relationship"]:
                out += "- " + source_link(item["source_id"], sources) + " — " + safe_text(item["interpretation"]) + "\n"
            out += "\n"
        out += "#### Routing\n\n" + _simple_properties(data.get("routing", {}))
        out += (f"#### Suggested next action\n\n{safe_text(data.get('suggested_next_action', ''))}\n\n"
                f"**Why:** {safe_text(data.get('why', ''))}\n\n"
                "#### Discovery questions\n\n" + _bullets(data.get("discovery_questions", [])))
        if data.get("stakeholder_hypotheses"):
            out += "#### Stakeholder hypotheses\n\n" + _claims(data["stakeholder_hypotheses"], sources)
        if data.get("important_limitations"):
            out += "#### Important limitations (top five; see complete structured record for all)\n\n" + _bullets(data["important_limitations"][:5])
    else:
        out += render_value({k: v for k, v in data.items() if k != "groundedness"}, sources)

    if data.get("groundedness"):
        review = data["groundedness"]
        findings = review.get("mechanical_and_semantic_findings", [])
        errors = sum(f.get("severity") == "error" for f in findings)
        warns = sum(f.get("severity") == "warning" for f in findings)
        out += (f"\n#### Evidence audit\n\n**{errors} errors** · **{warns} warnings** · "
                f"semantic review: **{safe_text(review.get('semantic_review', 'unknown'))}**. "
                "See structured record for individual findings.\n\n")
    return out + (_warnings(stage) if include_warnings else "")


def markdown_export(run: Run) -> str:
    # Redact before Markdown escaping (keys may contain underscores or other special characters).
    run = Run.model_validate_json(json_export(run))
    out = (f"# FlytBase inbound run {run.run_id}\n\n"
           f"Mode: **{run.mode}** · Result: **{run.status}** · Research as of: {run.as_of_date} (Asia/Kolkata)\n\n"
           f"Started: {run.started_at}\n\nFinished: {run.finished_at or 'in progress'}\n\n"
           "Emails are reviewable drafts. Follow-up branches are hypothetical. A saved run is a replay when reopened.\n\n"
           f"## Enquiry\n\n{safe_text(run.input)}\n\n")
    if run.mode == "offline_test":
        out = ("> **SYNTHETIC OFFLINE TEST — not live research or submission acceptance evidence.** "
               "Fixture data and simulated audit responses do not establish public facts.\n\n" + out)
    for index, stage in enumerate(run.stages):
        out += f"## Stage {index+1}: {stage.name}\n\n{stage_markdown(stage, run.sources)}\n\n"
    out += "## Sources and evidence\n\n"
    for sid, source in run.sources.items():
        out += (f"### {sid}: {safe_text(source.title)}\n\n{source_link(sid, run.sources)}\n\n"
                f"Access: {source.access}; retrieved: {source.retrieved_at}; publication: {safe_text(source.publication_date or 'not available')}; "
                f"date basis: {safe_text(source.publication_date_basis)}; truncated: {source.truncated}; "
                f"PDF pages processed: {source.pages_read}/{source.pages_total}; retained pages: {source.pages_retained}.\n\n")
        if source.error:
            out += f"Inspection warning: {safe_text(source.error)}\n\n"
    out += "## Usage (provider-reported; no cost estimate)\n\n" + render_value(run.usage, run.sources)
    out += "\n## Configuration\n\n" + render_value(run.config, run.sources)
    out += "\n## Execution logs (sanitised)\n\n" + render_value(run.logs, run.sources)
    out += "\n## Run warnings\n\n" + render_value(run.warnings, run.sources)
    if run.followup_updates:
        out += "\n## Hypothetical follow-up simulations\n\n" + render_value(run.followup_updates, run.sources)
    return sanitise(out)


def save_run(run: Run, root: Path):
    from .grounding import iter_claims
    for source in run.sources.values():
        source.cited_by = []
    for stage in run.stages:
        for path, claim in iter_claims(stage.output):
            for ref in claim.evidence:
                if ref.source_id in run.sources:
                    run.sources[ref.source_id].cited_by.append({"stage": stage.name, "path": path,
                                                              "claim": claim.text, "kind": claim.kind, "supporting_excerpt": ref.quote,
                                                              "limitation": "Citation linkage; consult stage groundedness flags for support assessment."})
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run.run_id):
        raise ValueError("Invalid run ID.")
    folder = root / run.run_id
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise RunSaveError("Windows blocked creating the run folder. Verify runs-directory write permission; previous records are unchanged.") from None
    with _SAVE_LOCK:
        for name, data in [("run.json", json_export(run)), ("report.md", markdown_export(run))]:
            _atomic_text(folder / name, data)
    return folder


def load_run(path: Path) -> Run:
    return Run.model_validate_json(path.read_text(encoding="utf-8"))
