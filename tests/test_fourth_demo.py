"""Fourth recording preparation; only local fixtures and HTTP MockTransport."""
import json
from pathlib import Path
import httpx
import pytest
from streamlit.testing.v1 import AppTest
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import ROOT, Settings
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.final_demo import demo_settings
from flytbase_bdr.models import Topic, Research, AccountAdvice, Responses
from flytbase_bdr.provider import ProviderError, QuotaExhausted
from flytbase_bdr.providers.groq import structured_payload
from flytbase_bdr.providers.tavily import TavilyProvider
from flytbase_bdr.reporting import _atomic_text, RunSaveError, load_run
from flytbase_bdr.workflow import Workflow, new_run
from scripts.simulate_offline import SimulationProvider, ENQUIRY


def three_finished(settings):
    b = ProjectBudget(settings)
    b.reserve("groq", 100, "synthetic historical unknown")
    b.prepare_final_demo()
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("first"); b.finish_final_demo("first", "partial")
    b.prepare_second_demo()
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("second"); b.finish_final_demo("second", "partial")
    b.prepare_third_demo()
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("third"); b.finish_final_demo("third", "partial")
    return b


def test_fourth_preserves_all_three_allowances_and_requires_free_quota_confirmation(settings):
    b = three_finished(settings)
    before = b.path.read_bytes(); original = b.read()
    fourth = b.prepare_fourth_demo()
    now = b.read()
    assert now["entries"] == original["entries"] and now["ceilings"] == original["ceilings"]
    assert now["demo_history"] == original["demo_history"] + [original["one_time_demo"]]
    assert b.path.with_name("project_budget.before_fourth_demo.json").read_bytes() == before
    assert fourth["sequence"] == 4 and fourth["limits"]["groq"] == 62000 and fourth["limits"]["tavily"] == 32
    with pytest.raises(ValueError): b.prepare_fourth_demo()
    with approved_live_execution(True, phase="demo"):
        with pytest.raises(QuotaExhausted, match="Confirm current"):
            b.start_final_demo("fourth")
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        b.start_final_demo("fourth")
        b.reserve("groq", 62000, "bounded generation", run_id="fourth")
        with pytest.raises(QuotaExhausted): b.reserve("groq", 1, "over", run_id="fourth")
        with pytest.raises(QuotaExhausted): b.start_final_demo("fifth")


def test_fourth_profile_keeps_rate_window_and_increases_completion_and_research(settings):
    cfg = demo_settings(settings, {"sequence": 4})
    assert cfg.max_output_tokens == 4000 and cfg.max_request_tokens == 7500 and cfg.groq_tpm == 8000
    assert cfg.tavily_search_depth == "advanced" and cfg.max_results_per_query == 5
    assert not cfg.compact_account_research and cfg.max_api_requests == 30
    assert cfg.max_source_fetches == 20 and cfg.max_source_chars == 18000
    p, cap = structured_payload(Responses, "Five concise branches", {}, cfg, "email drafts")
    assert cap == 4000 and p["max_completion_tokens"] == 4000


def test_advanced_search_reserves_two_credits_and_basic_extract_one(settings, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly_offline_fourth_test_123456789")
    cfg = demo_settings(settings, {"sequence": 4})
    def response(request):
        if request.url.path == "/usage":
            return httpx.Response(200, json={"account": {"current_plan": "Researcher", "plan_limit": 1000,
                    "plan_usage": 40, "paygo_limit": 0, "paygo_usage": 0}, "key": {}})
        body = json.loads(request.content)
        if request.url.path == "/search":
            assert body["search_depth"] == "advanced" and body["max_results"] == 5 and not body["auto_parameters"]
            return httpx.Response(200, json={"results": [{"url": "https://example.com/test", "content": "Fixture"}], "usage": {"credits": 2}})
        assert body["extract_depth"] == "basic"
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})
    p = TavilyProvider(cfg, new_run(ENQUIRY, cfg, "offline_test"), httpx.Client(transport=httpx.MockTransport(response)))
    try:
        p.search(["Derived fictional enquiry query"], "search:test", "2026-11-05")
        p.extract(["https://example.com/test"])
    finally: p.close()
    entries = ProjectBudget(cfg).read()["entries"]
    assert [e["reserved"] for e in entries] == [2, 1]


def test_windows_transient_save_retries_without_losing_last_good_file(tmp_path, monkeypatch):
    path = tmp_path / "run.json"; path.write_text("old", encoding="utf-8")
    original = Path.replace; calls = []
    def locked(source, target):
        calls.append(source.name)
        if len(calls) < 3:
            assert path.read_text() == "old"
            raise PermissionError("Synthetic Windows sharing lock")
        return original(source, target)
    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("flytbase_bdr.reporting.time.sleep", lambda delay: None)
    _atomic_text(path, "new")
    assert path.read_text() == "new" and len(calls) == 3
    assert not list(tmp_path.glob("*.pending"))


def test_persistent_windows_lock_keeps_previous_json_and_recovery_content(tmp_path, monkeypatch):
    path = tmp_path / "run.json"; path.write_text("old", encoding="utf-8")
    def locked(*a): raise PermissionError("Synthetic persistent lock")
    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("flytbase_bdr.reporting.time.sleep", lambda delay: None)
    with pytest.raises(RunSaveError, match="Last good file is intact"):
        _atomic_text(path, "new")
    assert path.read_text() == "old"
    pending = list(tmp_path.glob("*.pending"))
    assert len(pending) == 1 and pending[0].read_text() == "new"


def test_fourth_six_stages_focused_topics_refresh_and_progress(settings):
    b = three_finished(settings); b.prepare_fourth_demo()
    calls, searches, states = [], [], []
    class Focused(SimulationProvider):
        def search(self, queries, purpose, *args, **kwargs):
            searches.append((purpose, queries))
            return super().search(queries, purpose, *args, **kwargs)
        def structured(self, schema, instruction, data, purpose, **kwargs):
            calls.append(purpose)
            if schema in {Topic, AccountAdvice}:
                full = super().structured(Research, instruction, data, purpose, **kwargs)
                if schema is Topic:
                    return next(t for t in full.topics if t.name == purpose.split(":", 1)[1])
                return AccountAdvice(positioning=full.positioning, stakeholder_hypothesis=full.stakeholder_hypothesis, conflicts=full.conflicts)
            return super().structured(schema, instruction, data, purpose, **kwargs)
    def forbidden(*a, **k): raise AssertionError("No external fetch in offline integration")
    with approved_live_execution(True, phase="demo", confirmed_free_quota=True):
        run = Workflow(settings, Focused, forbidden, research_factory=Focused).execute(
            ENQUIRY, on_update=lambda r: states.append([s.status for s in r.stages]))
    assert len([p for p in calls if p.startswith("account topic:")]) == 5
    assert len(run.queries["finance"]) == 3 and len(run.queries["partners"]) == 3
    assert sum(len(q) for q in run.queries.values()) == 12
    assert all(s.status == "complete" for s in run.stages), [(s.name, s.warnings) for s in run.stages]
    assert all(any(state[i] == "running" for state in states) for i in range(6))
    assert b.demo_summary()["state"] == "finished"
    assert load_run(settings.run_path() / run.run_id / "run.json").run_id == run.run_id


def test_fourth_streamlit_start_waits_for_both_approvals(settings, monkeypatch):
    b = three_finished(settings); b.prepare_fourth_demo()
    monkeypatch.setenv("RUNS_DIR", settings.runs_dir)
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: True)
    def forbidden(*a, **kw): raise AssertionError("No provider on UI replay")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    app.radio(key="execution_mode").set_value("Protected live execution").run(timeout=30)
    app.selectbox(key="live_phase_choice").set_value("Record fresh demo").run(timeout=30)
    next(x for x in app.button if "sample enquiry" in x.label.lower()).click().run(timeout=30)
    app.checkbox(key="live_action_approval").check().run(timeout=30)
    assert next(x for x in app.button if "six-stage analysis" in x.label.lower()).disabled
    app.checkbox(key="final_demo_quota_confirmation").check().run(timeout=30)
    assert not next(x for x in app.button if "six-stage analysis" in x.label.lower()).disabled
    assert not app.exception
