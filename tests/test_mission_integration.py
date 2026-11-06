"""Offline regressions from the inspected 2026-11-05 execution, not live proof."""
import json
import pytest
from streamlit.testing.v1 import AppTest
from flytbase_bdr.config import ROOT
from flytbase_bdr.cross_stage import reconcile_existing_customer_evidence
from flytbase_bdr.grounding import check_claim
from flytbase_bdr.identity import handoff_identity
from flytbase_bdr.models import Audit, FinancialContext, MaterialChoice, Research, Source, Stage
from flytbase_bdr.provider import ProviderError
from flytbase_bdr.reporting import load_run, stage_markdown
from flytbase_bdr.review import cleared_claims
from flytbase_bdr.workflow import Workflow
from scripts.simulate_offline import simulate
from scripts.validate_saved_run import validate
from conftest import FakeProvider, fake_fetch, claim
from test_cross_stage_customer_reconciliation import sample_run


def test_late_source_checked_claim_does_not_inherit_an_old_ai_audit():
    run = sample_run()
    assert reconcile_existing_customer_evidence(run)
    review = run.stages[1].output["groundedness"]
    assert review["unreviewed_claim_paths"] == ["topics.1.claims.0"]
    assert cleared_claims(run.stages[1].output, run.sources, run.input, run.as_of_date) == []
    assert review["semantic_review"] == "performed"  # historical audit, not the added claim


def test_reconciliation_preserves_narrow_current_contract_and_requested_site_unknowns():
    run = sample_run()
    gaps = run.stages[1].output["topics"][1]["gaps"]
    gaps += ["No current contract between TCOMP and FlytBase is verified.",
             "No public evidence that FlytBase covers the three proposed sites."]
    reconcile_existing_customer_evidence(run)
    assert any("current contract" in g for g in gaps)
    assert any("three proposed sites" in g for g in gaps)
    assert any("current contract" in g for g in run.stages[1].output["topics"][1]["gaps"])


def test_legacy_reconciliation_marker_is_migrated_to_pending_audit_without_duplicate_claim():
    run = sample_run()
    reconcile_existing_customer_evidence(run)
    output = run.stages[1].output
    count = len(output["topics"][1]["claims"])
    del output["groundedness"]["unreviewed_claim_paths"]
    assert reconcile_existing_customer_evidence(run)
    assert output["groundedness"]["unreviewed_claim_paths"] == ["topics.1.claims.0"]
    assert len(output["topics"][1]["claims"]) == count
    assert cleared_claims(output, run.sources, run.input, run.as_of_date) == []


@pytest.mark.parametrize("fail_delta", [False, True])
def test_late_relationship_delta_audit_is_real_scoped_and_cache_preserving(settings, enquiry, fail_delta):
    calls = []
    unavailable = [fail_delta]
    class Late(FakeProvider):
        def search(self, queries, purpose, *args, **kwargs):
            if purpose == "search:materials":
                return {"results": [{"url": "https://flytbase.com/case-studies/sqm-offline-fixture",
                                     "title": "SQM synthetic inspection story", "content": "Fictional fixture"}]}
            return super().search(queries, purpose, *args, **kwargs)
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if purpose == "audit:account-late-evidence":
                calls.append(data)
                assert all(row["path"].startswith("topics.4.claims.") for row in data["claims_with_paths"])
                if unavailable[0]:
                    raise ProviderError("Synthetic audit unavailable")
            result = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Research:
                result.topics[-1].claims = []
                result.topics[-1].gaps = ["No public evidence of an SQM FlytBase partnership."]
            return result
    def fetched(source, max_chars):
        if "sqm-offline-fixture" in source.url:
            source.access = "inspected_page"
            source.text = "SQM partnered with FlytBase to automate iodine operations inspection in Chile. " * 4
        else:
            fake_fetch(source, max_chars)
    run = Workflow(settings, Late, fetched, research_factory=Late).execute(enquiry, mode="offline_test")
    assert len(calls) == 1
    output = run.stages[1].output
    rows = cleared_claims(output, run.sources, run.input, run.as_of_date)
    assert rows  # original audited findings survive an unavailable delta audit
    relationship = [row for row in rows if row["topic"] == "Corporate changes and customer relationships"]
    assert bool(relationship) is not fail_delta
    assert bool(output["groundedness"]["unreviewed_claim_paths"]) is fail_delta
    assert not any(f["path"] == "" for f in output["groundedness"]["mechanical_and_semantic_findings"])
    if not fail_delta:
        Workflow(settings, Late, fetched, research_factory=Late).execute(enquiry, mode="offline_test", resume=run, rerun_stages={3})
        assert len(calls) == 1  # successful exact audit reused, not repeated
    else:
        unavailable[0] = False
        recovered = Workflow(settings, Late, fetched, research_factory=Late).execute(
            enquiry, mode="offline_test", resume=run, rerun_stages={2})
        assert len(calls) == 2
        assert recovered.stages[1].technical_status == "succeeded"
        assert not recovered.stages[1].output["groundedness"]["unreviewed_claim_paths"]
        assert any(row["topic"] == "Corporate changes and customer relationships" for row in cleared_claims(
            recovered.stages[1].output, recovered.sources, recovered.input, recovered.as_of_date))
        assert not any("Semantic review unavailable" in w for w in recovered.stages[1].warnings)


def test_main_simulation_uses_production_compact_case_contract(tmp_path):
    folder, result = simulate(tmp_path / "demo")
    run = load_run(folder / "run.json")
    assert all(result["checks"].values())
    comparison = run.stages[3].output["ai_case_comparison"]
    assert comparison["preferred_source_id"] == run.stages[3].output["primary"]["candidate"]["source_id"]
    assert run.retrieval_cache["_structured"]["material comparison"]["output"]["gaps"] == []
    assert all(s.technical_status == "succeeded" for s in run.stages)
    assert len(run.stages[2].output["drafts"]) == 5


def test_changed_shared_rules_invalidate_cached_model_responses(settings, enquiry, monkeypatch):
    from flytbase_bdr import prompts
    calls = []
    class Track(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            calls.append(purpose)
            return super().structured(schema, instruction, data, purpose, **kwargs)
    original = Workflow(settings, Track, fake_fetch, research_factory=Track).execute(enquiry, mode="offline_test")
    calls.clear()
    Workflow(settings, Track, fake_fetch, research_factory=Track).execute(
        enquiry, mode="offline_test", resume=original, rerun_stages={2})
    assert "email drafts" not in calls
    monkeypatch.setattr(prompts, "SYSTEM", prompts.SYSTEM + "\nAdditional offline regression rule.")
    Workflow(settings, Track, fake_fetch, research_factory=Track).execute(
        enquiry, mode="offline_test", resume=original, rerun_stages={2})
    assert "email drafts" in calls


def test_recording_plan_does_not_count_emergency_as_usable_headroom(settings, enquiry, monkeypatch):
    from flytbase_bdr.budget import ProjectBudget
    from flytbase_bdr.planning import continuation_and_recording_allocation
    budget = {"groq": {"remaining_for_reservation": 15645, "repair_remaining": 0, "emergency_reserve": 7759},
              "tavily": {"remaining_for_reservation": 12}}
    monkeypatch.setattr(ProjectBudget, "summary", lambda self: budget)
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    plan = continuation_and_recording_allocation(run, settings)
    assert plan["available_application_tokens"] == 7886
    assert plan["emergency_tokens_excluded"] == 7759 and plan["repair_phase_available"] == 0
    assert plan["lower"]["additional_allowance_tokens"] == 25014


def test_compact_json_truncation_stays_provisional_without_repeating_generation(settings):
    from scripts.simulate_offline import SimulationProvider, ENQUIRY
    calls = []
    class Truncated(SimulationProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is MaterialChoice:
                calls.append(purpose)
                raise ProviderError("HTTP 400 json_validate_failed: max completion tokens; missing gaps")
            return super().structured(schema, instruction, data, purpose, **kwargs)
    run = Workflow(settings, Truncated, fake_fetch, research_factory=Truncated).execute(ENQUIRY, mode="offline_test")
    assert calls == ["material comparison"]
    assert run.stages[3].status == "partial"
    assert run.stages[3].output["groundedness"]["semantic_review"] == "rule_based_fallback"
    assert run.stages[5].output["recommended_case_study"] is None
    assert run.status == "partial"


def test_latest_real_cached_case_and_partner_payloads_fit_and_reuse_original_sources(settings):
    from flytbase_bdr.models import Routing
    from flytbase_bdr.provider import estimate_tokens
    from flytbase_bdr.providers.groq import structured_payload
    path = ROOT / "runs/20261105T084634_de8c5e7e22/run.json"
    if not path.exists():
        pytest.skip("Private recorded evidence intentionally excluded from public source")
    before = path.read_bytes()
    saved = load_run(path)
    saved.mode = "offline_test"
    captured = {}
    class Capture(FakeProvider):
        supports_compact_material_comparison = True
        def search(self, *args, **kwargs):
            raise AssertionError("Recorded retrieval must be reused")
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema in {MaterialChoice, Routing}:
                payload, cap = structured_payload(schema, instruction, data, settings, purpose, kwargs.get("max_tokens"))
                size = estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) + cap
                captured[schema.__name__] = size
                assert size <= settings.max_request_tokens
                if schema is Routing:
                    assert "Adentu" in json.dumps(data) and "Chile" in json.dumps(data)
            if schema is MaterialChoice:
                return MaterialChoice(preferred_source_id=data["cases"][0]["source_id"],
                                      ranked_source_ids=[c["source_id"] for c in data["cases"]],
                                      rationale="Inspection comparison; proposed sites require discovery.", gaps=[])
            return super().structured(schema, instruction, data, purpose, **kwargs)
    result = Workflow(settings, Capture, fake_fetch, research_factory=Capture).execute(
        saved.input, mode="offline_test", resume=saved, rerun_stages={3, 4})
    assert set(captured) == {"MaterialChoice", "Routing"}
    assert result.stages[0].execution_origin.startswith("cached")
    assert result.stages[3].output["comparison"]
    assert all(row["candidate"]["source_id"] in saved.sources for row in result.stages[3].output["comparison"])
    assert path.read_bytes() == before


def test_legacy_handoff_identity_uses_qualification_without_mutating_saved_data(enquiry):
    from conftest import make_lead
    data = {"buyer_context": {"name": "Unknown", "company": "", "geography": None},
            "qualification": {"lead": make_lead(enquiry).model_dump()}}
    before = json.dumps(data)
    context, recovered = handoff_identity(data)
    assert context["name"] == "Rodrigo Castillo" and context["geography"] == "Chile"
    assert {"name", "company", "geography"} <= set(recovered)
    text = stage_markdown(Stage(name="AE Handoff Summary", output=data), {})
    assert "Rodrigo Castillo" in text and "Sociedad" in text and "saved JSON is unchanged" in text
    assert json.dumps(data) == before


def test_quote_backed_finance_keeps_publication_day_unknown_instead_of_inventing(source):
    source.publication_date = ""
    source.text = "Group capex for 2025 was USD 10 million."
    c = claim(text=source.text, quote=source.text)
    c.financial_context = FinancialContext(currency="USD", units="million", reporting_period="2025",
                                           publication_date="unknown", scope="group-wide, not drone allocation")
    c.uncertainty = "Publication date unknown; fiscal reporting period is 2025."
    assert check_claim(c, {source.source_id: source}, "", "2026-11-05") == []
    c.financial_context.reporting_period = "2024"
    assert any("reporting period" in s for s in check_claim(c, {source.source_id: source}, "", "2026-11-05"))


def test_buyer_requirements_must_not_share_the_public_case_study_citation(source):
    from flytbase_bdr.models import Claim
    enquiry = "Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites."
    source.text = "A mining company uses FlytBase to inspect iodine operations in Chile."
    mixed = claim(text="Your 24/7 lithium inspection needs align with the published iodine deployment.",
                  quote=source.text)
    assert any("Continuous-operation" in issue for issue in check_claim(
        mixed, {source.source_id: source}, enquiry, "2026-11-05"))
    recap = Claim(text="Your enquiry describes 3 large-scale, 24/7 lithium extraction sites.",
                  kind="supplied", evidence=[], input_quote=enquiry, uncertainty="", financial_context=None, event_date="")
    public = claim(text=source.text, quote=source.text)
    proposed = Claim(text="Could we confirm whether this is a separate site and agree a discovery call?",
                     kind="inference", evidence=[], input_quote="", uncertainty="Proposed discovery question.",
                     financial_context=None, event_date="")
    for paragraph in (recap, public, proposed):
        assert check_claim(paragraph, {source.source_id: source}, enquiry, "2026-11-05") == []


def test_actual_latest_saved_run_validation_and_handoff_all_pages_are_read_only(monkeypatch):
    path = ROOT / "runs/20261105T084634_de8c5e7e22/run.json"
    if not path.exists():
        pytest.skip("Private run is intentionally excluded from source distribution")
    before = path.read_bytes()
    report = validate(path)
    assert report["historical_status"] == "partial" and report["handoff_matches_qualification"]
    assert report["buyer_context"]["name"] == "Rodrigo Castillo"
    assert report["local_reconciliation_preview"]["pending_AI_audit_paths"]
    assert any("contradict" in item.lower() for item in report["review"]["blocking_review_items"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved UI must not construct a provider")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["run"] = load_run(path)
    app.session_state["replay"] = True
    app.run(timeout=30)
    for page in ("Account Intelligence", "Sales Strategy", "AE Handoff", "How It Works & Evidence", "Command Center"):
        app.radio(key="workspace_page").set_value(page).run(timeout=30)
        assert not app.exception, page
        if page == "AE Handoff":
            assert "Rodrigo Castillo" in str(app)
            assert len(app.get("download_button")) >= 2
    assert path.read_bytes() == before
