import hashlib
import json
from pathlib import Path
import httpx
import pytest
from streamlit.testing.v1 import AppTest
from flytbase_bdr.config import ROOT, Settings
from flytbase_bdr.models import Materials, Source, FinancialContext, Partner, Routing
from flytbase_bdr.providers.groq import GroqProvider
from flytbase_bdr.execution import LiveExecutionBlocked, require_live_execution, approved_live_execution
from flytbase_bdr.workflow import new_run, Workflow, fork_resume
from flytbase_bdr.planning import plan_resume, submission_resources
from flytbase_bdr.evidence import derive_queries, source_family_key
from flytbase_bdr.selection import select_materials, decide_routing
from flytbase_bdr.grounding import check_claim
from flytbase_bdr.diagnostics import own_company_mentions
from flytbase_bdr.reporting import load_run
from conftest import FakeProvider, fake_fetch, claim, make_material


def test_live_request_is_blocked_before_dispatch_or_reservation(settings, enquiry, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_synthetic_offline_gate_key_12345")
    client = httpx.Client()
    def forbidden(*a, **k):
        raise AssertionError("Network transport should not be reached")
    monkeypatch.setattr(client, "request", forbidden)
    provider = GroqProvider(settings, new_run(enquiry, settings), client)
    with pytest.raises(LiveExecutionBlocked):
        provider.request("GET", "models", "offline gate", before_attempt=forbidden)
    assert not (settings.run_path() / "project_budget.json").exists()
    provider.close()


def test_approval_scope_is_explicit_and_does_not_stick():
    with pytest.raises(LiveExecutionBlocked):
        require_live_execution()
    with approved_live_execution(True):
        require_live_execution()  # permission check only; no request made
    with pytest.raises(LiveExecutionBlocked):
        require_live_execution()


def test_cached_stage_retry_reuses_retrieval_and_successful_model_calls(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    class NoRepeat(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if purpose in {"account research:compact", "audit:account"}:
                raise AssertionError("Unchanged structured request must reuse its persisted successful response")
            return super().structured(schema, instruction, data, purpose, **kwargs)
        def search(self, *a, **k):
            raise AssertionError("Cache-first retry must not repeat searches")
    repaired = Workflow(settings, NoRepeat, fake_fetch, research_factory=NoRepeat).execute(enquiry, mode="offline_test", resume=run, rerun_stages={1})
    assert repaired.stages[1].status != "failed"
    assert any(x.get("event") == "structured_call_reused" for x in repaired.logs)
    assert repaired.stages[0].output == run.stages[0].output
    assert not any("Research reused" in warning for warning in repaired.stages[1].warnings)


def test_fork_preserves_original_saved_work(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    before = run.model_dump()
    continued = fork_resume(run, settings)
    assert continued.run_id != run.run_id
    assert continued.stages[0].output == run.stages[0].output
    assert run.model_dump() == before


def test_inference_case_relevance_requires_real_evidence(source):
    material = make_material()
    material.relevance.kind = "inference"
    material.relevance.uncertainty = "Similarity is a recommendation; site feasibility remains unverified."
    materials = Materials(candidates=[material], referral_findings=[], gaps=[])
    assert select_materials(materials, {source.source_id: source}, "", "2026-11-04", [])["primary"]
    material.relevance.evidence[0].quote = "Invented support"
    assert select_materials(materials, {source.source_id: source}, "", "2026-11-04", [])["primary"] is None


def test_security_guard_reduction_does_not_score_as_inspection_fit(source):
    quote = "Ground teams reduced from ten security guards to five guards."
    source.text += quote
    material = make_material()
    material.dimensions[1].rationale = claim(text="Security savings", quote=quote)
    result = select_materials(Materials(candidates=[material], referral_findings=[], gaps=[]), {source.source_id: source}, "Need drone inspection of extraction equipment", "2026-11-04", [])
    assert result["primary"] is None
    assert result["comparison"][0]["breakdown"]["use_case"] == 0


def test_financial_scope_and_commodity_cannot_be_transferred(source):
    quote = "Company capex was USD 10 million in 2025."
    source.text += quote
    c = claim(text="Approved drone project budget was USD 10 million in 2025.", quote=quote)
    c.financial_context = FinancialContext(currency="USD", units="million", reporting_period="2025", publication_date="2026-01-01", scope="company-wide investment")
    assert any("Company-wide" in issue for issue in check_claim(c, {source.source_id: source}, "", "2026-11-04"))
    source.text += "The existing deployment supports iodine operations."
    c = claim(text="The existing deployment supports lithium sites.", quote="The existing deployment supports iodine operations.")
    assert any("commodity differs" in issue for issue in check_claim(c, {source.source_id: source}, "", "2026-11-04"))


def test_existing_customer_scope_is_not_inferred_from_commodity_portfolio(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    run.stages[0].output["lead"]["company"] = "Example Mining (EXM)"
    source = Source(source_id="S_scope", title="EXM deployment", url="https://flytbase.com/case-studies/example", retrieved_at="2026-11-04", access="inspected_page",
                    text="EXM produces lithium and iodine. EXM and FlytBase have deployed thermal inspection at iodine operations.")
    run.sources = {source.source_id: source}
    scope = own_company_mentions(run)[0]
    assert "iodine operations" in scope["deployment_scope_evidence"]
    assert "lithium" not in scope["deployment_scope_evidence"]
    source.text = "EXM produces lithium and iodine. EXM has deployed inspection with FlytBase."
    assert own_company_mentions(run)[0]["deployment_scope_evidence"] == ""


def test_changed_industry_changes_research_and_document_queries(lead):
    lead.company, lead.domain, lead.industry, lead.need = "Example Ports", "ports.example", "shipping", "harbour perimeter security"
    lead.referral = "Another Port"
    queries = derive_queries(lead, "2026-11-04")
    assert "shipping" in queries["current"][0]
    assert "harbour" in queries["materials"][0]
    assert "lithium mining" not in str(queries)
    assert source_family_key("https://reports.example/view?id=2025&utm_source=x") != source_family_key("https://reports.example/view?id=2024")


def test_read_only_plan_reserves_resources_without_changing_record(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    before = run.model_dump()
    plan = plan_resume(run, settings, {1, 3, 4}, {"finance"})
    assert [r["number"] for r in plan["rerun_stages"]] == [2, 3, 4, 5, 6]
    assert run.stages[0].name in plan["reuse_stages"]
    assert plan["execution_authorized"] is False
    assert plan["fresh_research_groups"] == ["finance"]
    scenarios = submission_resources(run, settings)["scenarios"]
    assert len(scenarios) == 4 and scenarios[-1]["groq_tokens"]["upper"] == 0
    assert run.model_dump() == before


def test_actual_saved_demo_is_read_only_and_cannot_construct_providers(monkeypatch):
    path = ROOT / "runs" / "20261104T112944_ed06566acf" / "run.json"
    ledger = ROOT / "runs" / "project_budget.json"
    if not path.exists() or not ledger.exists():
        pytest.skip("Private saved acceptance record is not distributed with source")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, ledger)}
    monkeypatch.setenv("RUNS_DIR", str(ROOT / "runs"))
    def forbidden(*a, **k):
        raise AssertionError("Read-only replay must not construct a provider")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    assert not app.exception
    assert any(r.value == "Command Center" for r in app.radio)
    assert any(r.value == "Read-only demonstration" for r in app.radio)
    run_button = next(b for b in app.button if "six-stage analysis" in b.label.lower())
    assert run_button.disabled
    app.run(timeout=30)
    assert not app.exception
    mode = next(r for r in app.radio if "Protected live execution" in r.options)
    mode.set_value("Protected live execution").run(timeout=30)
    assert not app.exception
    assert not app.checkbox(key="live_action_approval").value
    app.checkbox(key="live_action_approval").check().run(timeout=30)
    assert not app.exception
    run_button = next(b for b in app.button if "six-stage analysis" in b.label.lower())
    assert run_button.disabled  # current project allowance cannot cover a fresh run
    mode = next(r for r in app.radio if "Protected live execution" in r.options)
    mode.set_value("Read-only demonstration").run(timeout=30)
    assert not app.exception
    approval = app.checkbox(key="live_action_approval")
    assert not approval.value and approval.disabled
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, ledger)}


def test_changed_operational_need_changes_selected_material(source):
    import copy
    inspection = make_material()
    other = copy.deepcopy(source)
    other.source_id, other.url = "S_security", "https://flytbase.com/case-studies/security-example"
    other.text = "The mine uses autonomous perimeter surveillance for security."
    security = make_material(other.source_id)
    security.title = "Synthetic security example"
    for dimension in security.dimensions:
        dimension.rationale = claim(text="Evidence of mine security operations.", sid=other.source_id, quote=other.text)
    security.relevance = claim(text="Potential security-use-case relevance.", sid=other.source_id, quote=other.text, kind="inference")
    materials = Materials(candidates=[inspection, security], referral_findings=[], gaps=[])
    sources = {source.source_id: source, other.source_id: other}
    first = select_materials(materials, sources, "Need autonomous inspection of extraction equipment", "2026-11-04", [])
    second = select_materials(materials, sources, "Need autonomous perimeter security", "2026-11-04", [])
    assert first["primary"]["candidate"]["source_id"] == source.source_id
    assert second["primary"]["candidate"]["source_id"] == other.source_id


def test_direct_owner_can_have_verified_implementation_candidates_without_available_capacity(source):
    source.text += " Synthetic integrator is a FlytBase integration partner. Synthetic integrator installs drone docks. Synthetic integrator serves Chile."
    candidate = Partner(name="Synthetic integrator", partner_type="drone integrator",
                        ecosystem_evidence=claim(text="Synthetic integrator is a FlytBase integration partner.", quote="Synthetic integrator is a FlytBase integration partner."),
                        capabilities=[claim(text="Synthetic integrator installs drone docks.", quote="Synthetic integrator installs drone docks.")],
                        geographic_coverage=claim(text="Serves Chile", quote="Synthetic integrator serves Chile."), availability="Available tomorrow", limitations=[])
    routing = Routing(recommended_motion="direct_ae", rationale=[], candidates=[candidate], proposed_partner_name="", required_partner_type="integrator",
                      commercial_owner="AE", implementation_owner="unassigned", next_action="Verify capacity", gaps=[])
    data = decide_routing(routing, {source.source_id: source}, "", "2026-11-04", "Chile", [])
    assert data["commercial_owner"] == "FlytBase Account Executive" and not data["selected_partner_name"]
    assert len(data["implementation_candidates"]) == 1
    assert data["candidates"][0]["availability"].startswith("Not verified")
    assert "Available tomorrow" in data["proposed_availability_unverified"].values()
