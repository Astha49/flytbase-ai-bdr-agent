"""Offline contracts for the final unused-fourth-run optimisation."""
import json
import pytest
import httpx
from streamlit.testing.v1 import AppTest
from flytbase_bdr.config import ROOT
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.final_demo import demo_settings
from flytbase_bdr.models import Audit, Topic, AccountAdvice, Research, Responses, Lead, MaterialChoice
from flytbase_bdr.provider import WindowPacer, QuotaExhausted, RequestTooLarge, ProjectWindowWait
from flytbase_bdr.providers.groq import structured_payload
from flytbase_bdr.providers.tavily import TavilyProvider
from flytbase_bdr.workflow import Workflow, new_run
from test_fourth_demo import three_finished
from scripts.simulate_offline import SimulationProvider, ENQUIRY


def test_amend_unused_fourth_is_idempotent_audited_and_not_a_fifth(settings):
    b = three_finished(settings); b.prepare_fourth_demo()
    before = b.read(); old_id = before["one_time_demo"]["id"]
    result = b.optimize_fourth_demo()
    assert json.loads(b.path.with_name("project_budget.before_fourth_optimization.json").read_text()) == before
    assert result["id"] == old_id and result["sequence"] == 4 and result["state"] == "prepared"
    assert result["limits"]["groq"] == 62000 and result["limits"]["tavily"] == 60
    assert result["amendments"][0]["previous_limits"] == before["one_time_demo"]["limits"]
    for k in ("entries", "ceilings", "demo_history"):
        assert b.read()[k] == before[k]
    b.optimize_fourth_demo(); assert len(b.read()["one_time_demo"]["amendments"]) == 1
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        b.start_final_demo("fourth")
    with pytest.raises(ValueError): b.optimize_fourth_demo()


def test_completion_policy_is_task_specific_and_evidence_aware(settings):
    cfg = demo_settings(settings, {"sequence": 4, "optimized_research": True})
    caps = {schema.__name__: structured_payload(schema, "Offline", {}, cfg, "test")[1]
            for schema in (Lead, Topic, Responses, Audit, MaterialChoice)}
    assert caps == {"Lead": 2400, "Topic": 2100, "Responses": 4000, "Audit": 600, "MaterialChoice": 950}
    assert structured_payload(Topic, "Offline", {"sources": {str(i): {} for i in range(5)}}, cfg, "test")[1] > caps["Topic"]
    assert cfg.max_output_tokens == 4800 and cfg.rate_safety_margin == .95


def test_scheduler_obeys_headers_rolls_window_and_separate_output_limit(monkeypatch):
    clock = [0.0]; waits = []
    monkeypatch.setattr("flytbase_bdr.provider.time.monotonic", lambda: clock[0])
    def wait(delay): waits.append(delay); clock[0] += delay
    monkeypatch.setattr("flytbase_bdr.provider.wait_seconds", wait)
    p = WindowPacer()
    p.observe({"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "1000",
               "x-ratelimit-reset-tokens": "7.5s", "x-ratelimit-remaining-requests": "30"})
    p.reserve(2000, 7600, 25)
    assert waits == [8.0]
    p.reserve(6000, 7600, 25)
    assert waits[-1] == 61
    with pytest.raises(RequestTooLarge):
        p.reserve(1000, 7600, 25, input_tokens=100, output_tokens=900, output_tpm=800)
    p.observe({"x-ratelimit-remaining-requests": "0"})
    with pytest.raises(QuotaExhausted, match="RPD"):
        p.reserve(100, 7600, 25)


def test_scheduler_learns_lower_tpm_and_stops_unreasonable_wait(monkeypatch):
    monkeypatch.setattr("flytbase_bdr.provider.time.monotonic", lambda: 0)
    p = WindowPacer()
    p.observe({"x-ratelimit-limit-tokens": "6000", "retry-after": "1000"}, 429)
    assert p.capacity(7600, .95) == 5700
    with pytest.raises(QuotaExhausted): p.reserve(100, 5700, 25)


def test_selective_search_and_source_extraction_reuse_do_not_spend_twice(settings, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly_offline_final_optimisation_123456789")
    cfg = demo_settings(settings, {"sequence": 4, "optimized_research": True})
    bodies = []
    def reply(request):
        if request.url.path == "/usage":
            return httpx.Response(200, json={"account": {"current_plan": "Researcher", "plan_limit": 1000,
                "plan_usage": 43, "paygo_limit": 0, "paygo_usage": 0}, "key": {}})
        body = json.loads(request.content); bodies.append(body)
        if request.url.path == "/extract":
            return httpx.Response(200, json={"results": [{"url": body["urls"][0], "raw_content": "Source fixture " * 30}], "usage": {"credits": 1}})
        return httpx.Response(200, json={"results": [{"url": "https://example.com/original", "content": "Fixture only"}],
                                          "usage": {"credits": 2 if body["search_depth"] == "advanced" else 1}})
    provider = TavilyProvider(cfg, new_run(ENQUIRY, cfg, "offline_test"), httpx.Client(transport=httpx.MockTransport(reply)))
    try:
        for _ in range(2): provider.search(["Company filings"], "search:finance", "2026-11-05")
        provider.search(["Official customer stories"], "search:materials", "2026-11-05")
        for _ in range(2): provider.extract(["https://example.com/original"])
    finally: provider.close()
    assert len(bodies) == 3 and [b.get("search_depth") for b in bodies[:2]] == ["advanced", "basic"]
    assert [e["reserved"] for e in ProjectBudget(cfg).read()["entries"]] == [2, 1, 1]


def test_daily_guard_counts_unknown_usage_and_retains_emergency(settings):
    b = three_finished(settings); b.prepare_fourth_demo(); b.optimize_fourth_demo()
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        b.start_final_demo("fourth")
        data = b.read()
        data["entries"][0]["reserved"] = 195000  # Test-only unknown usage; never edit real history.
        b.write(data)
        with pytest.raises(QuotaExhausted, match="daily"):
            b.reserve("groq", 100, "generation", run_id="fourth")


def test_project_rolling_window_is_shared_across_budget_instances(settings):
    b = three_finished(settings); b.prepare_fourth_demo(); b.optimize_fourth_demo()
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        b.start_final_demo("fourth")
        ticket = b.reserve("groq", 5000, "first", run_id="fourth", request_window={"tpm": 7600, "rpm": 25})
        other = ProjectBudget(settings)
        with pytest.raises(ProjectWindowWait):
            other.reserve("groq", 4000, "second", run_id="fourth", request_window={"tpm": 7600, "rpm": 25})
        b.settle(ticket, 1000)
        other.reserve("groq", 4000, "second", run_id="fourth", request_window={"tpm": 7600, "rpm": 25})


def test_optimised_six_stage_fixture_produces_outputs_and_progress(settings):
    b = three_finished(settings); b.prepare_fourth_demo(); b.optimize_fourth_demo()
    calls = []
    class Focused(SimulationProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            calls.append(purpose)
            if schema in {Topic, AccountAdvice}:
                full = super().structured(Research, instruction, data, purpose, **kwargs)
                if schema is Topic: return next(t for t in full.topics if t.name == purpose.split(":", 1)[1])
                return AccountAdvice(positioning=full.positioning, stakeholder_hypothesis=full.stakeholder_hypothesis, conflicts=full.conflicts)
            return super().structured(schema, instruction, data, purpose, **kwargs)
    def forbidden(*a, **kw): raise AssertionError("No external research permitted in test")
    states = []
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        run = Workflow(settings, Focused, forbidden, research_factory=Focused).execute(
            ENQUIRY, on_update=lambda r: states.append([s.status for s in r.stages]))
    assert all(s.status == "complete" for s in run.stages), [(s.name, s.warnings) for s in run.stages]
    assert sum(map(len, run.queries.values())) == 16
    assert len(run.stages[2].output["drafts"]) == 5
    assert len(run.stages[5].output["top_three_research_findings"]) == 3
    assert all(any(state[i] == "running" for state in states) for i in range(6))
    assert not run.usage  # Mock responses are not a real live acceptance run.


def test_amended_limits_clear_old_streamlit_approval(settings, monkeypatch):
    b = three_finished(settings); b.prepare_fourth_demo(); b.optimize_fourth_demo()
    monkeypatch.setenv("RUNS_DIR", settings.runs_dir)
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: True)
    def forbidden(*a, **kw): raise AssertionError("No provider calls in UI verification")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    app.radio(key="execution_mode").set_value("Protected live execution").run(timeout=30)
    app.selectbox(key="live_phase_choice").set_value("Record fresh demo").run(timeout=30)
    app.checkbox(key="live_action_approval").check().run(timeout=30)
    app.checkbox(key="final_demo_quota_confirmation").check().run(timeout=30)
    record = b.read()
    record["one_time_demo"]["amendments"].append({"reason": "Test-only newer revision"})
    b.write(record)
    app.run(timeout=30)
    assert not app.checkbox(key="live_action_approval").value
    assert not app.checkbox(key="final_demo_quota_confirmation").value
    assert not app.exception


def test_empty_company_topic_uses_one_distinct_passage_followup(settings):
    b = three_finished(settings); b.prepare_fourth_demo(); b.optimize_fourth_demo()
    purposes = []
    class Gap(SimulationProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            purposes.append(purpose)
            if schema in {Topic, AccountAdvice}:
                full = super().structured(Research, instruction, data, purpose, **kwargs)
                if schema is AccountAdvice:
                    return AccountAdvice(positioning=full.positioning, stakeholder_hypothesis=full.stakeholder_hypothesis, conflicts=full.conflicts)
                item = next(t for t in full.topics if t.name == purpose.split(":", 1)[1])
                if purpose == "account topic:Budget and investment signals":
                    return Topic(name=item.name, claims=[], gaps=["Private drone funding unknown; general finding not yet extracted."])
                return item
            return super().structured(schema, instruction, data, purpose, **kwargs)
    def forbidden(*a, **kw): raise AssertionError("No external fetch")
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        run = Workflow(settings, Gap, forbidden, research_factory=Gap).execute(ENQUIRY)
    assert purposes.count("account followup:Budget and investment signals") == 1
    assert run.stages[1].output["topics"][1]["claims"]
    assert run.stages[0].output["lead"]["budget"]["status"] == "unknown"
