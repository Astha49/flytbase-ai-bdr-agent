"""Offline regressions using the actual partial execution plus bounded fixtures.

Private recordings are optional in a public checkout. No fixture is live evidence.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json

import pytest

from conftest import claim
from flytbase_bdr.compact import audit_batches
from flytbase_bdr.evidence import is_issuer_document
from flytbase_bdr.evidence_decisions import material_proposals, operating_context_quote, route_proposal
from flytbase_bdr.grounding import audit_mechanical, check_claim, resolve_audit_path
from flytbase_bdr.models import Claim, Run
from flytbase_bdr.normalization import expand_verbatim, normalize_claims
from flytbase_bdr.review import cleared_claims
from flytbase_bdr.safe_email_recovery import _verified_case_hint
from flytbase_bdr.sales_validation import checked_drafts, introduces_timing_year

RECORD = Path(__file__).resolve().parents[1] / "runs/20261105T195016_6b3a6fb0d3/run.json"


@pytest.fixture
def saved():
    if not RECORD.exists():
        pytest.skip("Private saved run is excluded from public source package")
    before = hashlib.sha256(RECORD.read_bytes()).hexdigest()
    result = Run.model_validate_json(RECORD.read_text(encoding="utf-8"))
    yield result
    assert hashlib.sha256(RECORD.read_bytes()).hexdigest() == before


def test_redundant_claim_wrapper_resolves_without_global_rejection():
    data = {"drafts": [{"paragraphs": [claim().model_dump()]}]}
    assert resolve_audit_path("output.drafts[0].paragraphs[0].claim.text", data) == "drafts.0.paragraphs.0.text"
    assert resolve_audit_path("drafts.0.paragraphs.9.claim.text", data) == ""
    assert resolve_audit_path("drafts.0.paragraphs.0.made_up.text", data) == ""


def test_recorded_email_rejection_is_local_and_all_five_bodies_survive(saved):
    data = deepcopy(saved.retrieval_cache["_structured"]["email drafts"]["output"])
    normalize_claims(data, saved.sources)
    findings = audit_mechanical(data, saved.sources, saved.input, saved.as_of_date)
    for raw in saved.retrieval_cache["_structured"]["audit:emails"]["output"]["findings"]:
        findings.append({**raw, "origin": "semantic", "path": resolve_audit_path(raw["path"], data)})
    data["groundedness"] = {"semantic_review": "performed", "mechanical_and_semantic_findings": findings}
    checked, warnings = checked_drafts(data, saved.sources, saved.input, saved.as_of_date)
    assert len(checked["drafts"]) == 5
    assert all(d["paragraphs"] and "withheld" not in d["subject"].casefold() for d in checked["drafts"])
    assert all(d["review_status"] == "checked" for d in checked["drafts"][1:])
    assert checked["drafts"][0]["review_status"] == "needs_review"
    assert not any("strategic focus on scaling" in p["text"] for d in checked["drafts"] for p in d["paragraphs"])
    assert not any("no safe email body" in w for w in warnings)


def test_recorded_financial_claim_stays_rejected_without_inventing_currency(saved):
    data = deepcopy(saved.stages[1].output)
    normalize_claims(data, saved.sources)
    item = Claim.model_validate(data["topics"][1]["claims"][0])
    problems = check_claim(item, saved.sources, saved.input, saved.as_of_date)
    assert any("currency" in p for p in problems)
    assert any("passage is absent" in p for p in problems)
    assert item.financial_context.currency == "USD"  # never silently 'correct' a currency
    assert "Publication date unknown" in item.uncertainty
    assert item.financial_context.publication_date.casefold() == "unknown"


def test_unrelated_recorded_financial_reports_excluded_but_official_reports_remain(saved):
    lead = saved.stages[0].output["lead"]
    for sid in ("S_aea5dffdf508", "S_b25f99e1332d", "S_bd3c093d1619"):
        assert not is_issuer_document(saved.sources[sid], lead["company"], lead["domain"])
    for sid in ("S_33b8ac06b265", "S_be24a66cec55"):
        assert is_issuer_document(saved.sources[sid], lead["company"], lead["domain"])


def test_non_sec_mirror_needs_original_issuer_identity(source):
    source.url, source.access = "https://cdn.example/reports/annual.pdf", "inspected_pdf"
    source.text = "Other Industrial Group annual financial report."
    source.search_context = "Example Mining EMX report"  # misleading snippet cannot override body
    assert not is_issuer_document(source, "Example Mining (EMX)", "emx.example")
    source.text = "Example Mining (EMX) annual financial report."
    assert is_issuer_document(source, "Example Mining (EMX)", "emx.example")


@pytest.mark.parametrize("marker", ["[HTML excerpt at character 900; omitted text between excerpts]", "[…context omitted…]"])
def test_ellipsis_cannot_bridge_synthetic_extraction_gaps(source, marker):
    source.text = f"The investment is USD 3 billion. {marker} It supports lithium."
    quote = "USD 3 billion ... lithium"
    assert expand_verbatim(quote, source.text) == quote
    invalid = claim(quote=source.text)
    assert any("omission" in p for p in check_claim(invalid, {source.source_id: source}, "", "2026-11-06"))


def test_split_title_and_advisory_audits_keep_inspected_metadata_and_quotes(saved):
    data = {"candidates": deepcopy(saved.stages[3].output["candidates"]),
            "ai_case_comparison": deepcopy(saved.stages[3].output["ai_case_comparison"])}
    batches = audit_batches(data, saved.sources, target_tokens=1200)
    titles = []
    for batch in batches:
        for field in batch["review_fields"]:
            assert all(k in batch["quotes"] for k in field["context_quote_refs"])
            assert all(sid in batch["sources"] for sid in field["context_source_ids"])
            if field["path"].endswith(".title"):
                titles.append(field)
                assert field["source_title_matches"]
            if field["path"] == "ai_case_comparison.rationale":
                assert field["context_quote_refs"]
    assert len(titles) == 2


@pytest.mark.parametrize("text", [
    "The company is planning to run 24/7 site surveillance missions.",
    "The system provides continuous flight status updates.",
    "They expect continuous monitoring after a future rollout.",
])
def test_plans_and_telemetry_do_not_prove_operating_context(text):
    assert not operating_context_quote(text)


def test_completed_continuous_operations_are_retained():
    sentence = "The mine operates 24/7 using continuous inspection monitoring."
    assert operating_context_quote(sentence) == sentence


def test_recorded_materials_keep_unknown_dimensions_and_change_with_lead(saved):
    ids = saved.retrieval_cache["materials"]["source_ids"]
    result = material_proposals(saved, ids)
    assert result.candidates
    for candidate in result.candidates:
        for dim in candidate.dimensions:
            if not dim.matched:
                assert dim.rationale.kind == "unknown" and not dim.rationale.evidence
            if dim.dimension == "operating_context":
                assert not dim.matched
    saved.stages[0].output["lead"].update(company="Example Ports", industry="shipping", need="harbour security", referral="")
    assert not material_proposals(saved, ids).candidates


def test_recorded_partner_specialization_is_not_upgraded_to_implementation(saved):
    ids = list(dict.fromkeys([*saved.retrieval_cache["materials"]["source_ids"], *saved.retrieval_cache["partners"]["source_ids"]]))
    proposed = route_proposal(saved, ids)
    assert proposed.recommended_motion == "direct_ae" and proposed.candidates
    for candidate in proposed.candidates:
        assert "implementation integrator" not in candidate.ecosystem_evidence.text
        assert "not verified" in candidate.availability.casefold()
        for item in [candidate.ecosystem_evidence, *candidate.capabilities, candidate.geographic_coverage]:
            assert not check_claim(item, saved.sources, saved.input, saved.as_of_date)
            assert all(ref.quote in saved.sources[ref.source_id].text for ref in item.evidence)


def test_proposed_owners_are_identified_to_auditor(source):
    batches = audit_batches({"commercial_owner": "FlytBase Account Executive", "implementation_owner": "Unassigned"}, {source.source_id: source})
    assert all("proposed" in f["role"] for b in batches for f in b["review_fields"])


def test_public_reporting_period_is_not_a_buyer_deadline():
    public = claim(text="Q1 2026 results describe a pipeline investment.").model_dump()
    assert not introduces_timing_year(public, "Budget discussion Q3.")
    public["text"] = "Your project timeline is Q3 2026."
    assert introduces_timing_year(public, "Budget discussion Q3.")
    proposed = claim(text="Should we plan for Q3 2026?", sid="", kind="inference").model_dump()
    assert introduces_timing_year(proposed, "Budget discussion Q3.", "budget_clarification")


def test_handoff_does_not_promote_semantic_warning_to_verified(source):
    output = {"topics": [{"name": "Operations", "claims": [claim().model_dump()]}],
              "groundedness": {"semantic_review": "performed", "mechanical_and_semantic_findings": [
                  {"path": "topics.0.claims.0", "severity": "warning", "origin": "semantic", "reason": "Strategy inference not explicit."}]}}
    assert not cleared_claims(output, {source.source_id: source}, "", "2026-11-06")
    output["groundedness"]["mechanical_and_semantic_findings"][0]["path"] = ""
    assert cleared_claims(output, {source.source_id: source}, "", "2026-11-06")


def test_recovery_cannot_treat_inspection_alone_as_semantic_approval(saved):
    lead = saved.stages[0].output["lead"]
    assert _verified_case_hint(lead, saved.sources, saved.input, saved.as_of_date) is None


def test_recorded_audit_requests_fit_existing_token_ceiling(saved, settings):
    from flytbase_bdr.models import Audit
    from flytbase_bdr.provider import estimate_tokens
    from flytbase_bdr.providers.groq import structured_payload
    from flytbase_bdr.prompts import AUDIT
    cfg = settings.model_copy(update={"task_aware_tokens": True, "expanded_research": True, "rate_safety_margin": .9})
    examples = [{k: saved.stages[1].output.get(k, [])
                 for k in ("topics", "positioning", "stakeholder_hypothesis", "conflicts")},
                saved.retrieval_cache["_structured"]["email drafts"]["output"]]
    examples.append(material_proposals(saved, saved.retrieval_cache["materials"]["source_ids"]).model_dump())
    examples.append(route_proposal(saved, saved.retrieval_cache["materials"]["source_ids"]).model_dump())
    for data in examples:
        for batch in audit_batches(data, saved.sources, target_tokens=2800):
            payload, limit = structured_payload(Audit, AUDIT,
                {"as_of_date": saved.as_of_date, "enquiry": saved.input, **batch}, cfg, "audit:regression", max_tokens=1800)
            size = estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            ceiling = min(cfg.max_request_tokens, int(cfg.groq_tpm * cfg.rate_safety_margin))
            assert size + limit <= ceiling, (size, limit, ceiling)


def test_search_title_is_not_mislabelled_as_original_metadata(source):
    from flytbase_bdr.compact import audit_payload
    source.title_basis = "search-result metadata; original document title not verified"
    data = {"candidates": [{"source_id": source.source_id, "title": source.title, "relevance": claim().model_dump()}]}
    payload = audit_payload(data, {source.source_id: source})
    title = next(row for row in payload["review_fields"] if row["path"].endswith(".title"))
    assert "not verified" in title["title_provenance"]
    assert title["source_title_matches"]  # label equality is kept separate from provenance
    assert title["context_quote_refs"]


def test_parent_candidate_error_and_semantic_caveat_reject_selection(source):
    from conftest import make_material
    from flytbase_bdr.models import Materials
    from flytbase_bdr.selection import select_materials
    material = Materials(candidates=[make_material()], referral_findings=[], gaps=[])
    for path, severity in (("candidates", "error"), ("candidates.0.relevance", "warning")):
        result = select_materials(material, {source.source_id: source}, "inspection", "2026-11-06",
            [{"path": path, "severity": severity, "origin": "semantic", "reason": "Evidence unresolved."}])
        assert result["primary"] is None


def test_search_gap_cannot_become_universal_organisation_fact(source):
    item = claim(text="The overview does not name a Northern Division or its head in public filings.")
    assert any("absence from all public" in p for p in check_claim(item, {source.source_id: source}, "", "2026-11-06"))
    item = claim(text="The reporting line was not established in this run.", sid="", kind="unknown")
    assert not check_claim(item, {}, "", "2026-11-06")


def test_case_narrative_precedes_promotional_navigation_in_matching(saved):
    result = material_proposals(saved, saved.retrieval_cache["materials"]["source_ids"])
    referral = next(c for c in result.candidates if any(d.dimension == "referral" and d.matched for d in c.dimensions))
    dimension = next(d for d in referral.dimensions if d.dimension == "referral")
    assert "successfully deployed" in dimension.rationale.evidence[0].quote
    assert "0% Reduced Travel" not in dimension.rationale.evidence[0].quote
