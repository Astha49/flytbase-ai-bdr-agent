"""One-time preparation/launch contracts. All provider responses are offline fixtures."""
import queue
import time
import pytest
from streamlit.testing.v1 import AppTest
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import ROOT
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.provider import ProviderError, QuotaExhausted
from flytbase_bdr.reporting import save_run
from flytbase_bdr.workflow import Workflow, new_run
from scripts.simulate_offline import SimulationProvider, ENQUIRY


def prepared(settings):
    b = ProjectBudget(settings)
    b.reserve("groq", 38241, "synthetic historical reservations")
    settings.project_max_groq_tokens = 110000
    b.authorize_groq_ceiling(110000)
    return b


def test_prepare_is_local_additive_idempotent_and_does_not_authorize_live(settings):
    b = prepared(settings)
    before = b.path.read_bytes()
    old = b.read()
    allowance = b.prepare_final_demo()
    assert b.path.with_name("project_budget.before_final_demo.json").read_bytes() == before
    after = b.read()
    for key in old:
        assert old[key] == after[key]
    assert allowance["limits"] == {"groq": 60000, "tavily": 16, "groq_requests": 24,
                                    "search_requests": 10, "extract_requests": 5, "control_requests": 2}
    assert b.prepare_final_demo() == allowance
    with pytest.raises(ProviderError, match="Read-only"):
        b.start_final_demo("no-approval")
    assert b.demo_summary()["state"] == "prepared"
    with approved_live_execution(True, phase="repair"):
        with pytest.raises(QuotaExhausted):
            b.start_final_demo("wrong-phase")


def test_one_run_owns_allowance_token_caps_unknown_usage_and_reserves(settings):
    b = prepared(settings)
    b.prepare_final_demo()
    old_entries = b.read()["entries"][:]
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("one")
        with pytest.raises(QuotaExhausted):
            b.start_final_demo("two")
        with pytest.raises(QuotaExhausted):
            b.reserve("groq", 100, "extraction", run_id="wrong")
        b.reserve("groq", 59999, "bounded fixture", run_id="one")
        b.reserve("groq", 1, "last fixture", run_id="one")
        with pytest.raises(QuotaExhausted):
            b.reserve("groq", 1, "exhausted", run_id="one")
        assert b.demo_summary()["groq_remaining"] == 0  # unknown usage not refunded
        b.finish_final_demo("one", "partial")
        b.prepare_final_demo()  # cannot replenish or rearm
        with pytest.raises(QuotaExhausted):
            b.start_final_demo("three")
    assert b.read()["entries"][:len(old_entries)] == old_entries
    assert b.read()["phase_limits"]["emergency_reserve"] == 7759


@pytest.mark.parametrize("provider,purpose,limit", [("groq", "generation", 24), ("tavily", "search", 10), ("tavily", "extract", 5)])
def test_actual_attempt_limits_cannot_be_bypassed(settings, provider, purpose, limit):
    b = prepared(settings)
    b.prepare_final_demo()
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("one")
        for _ in range(limit):
            b.reserve(provider, 1, purpose, run_id="one")
        with pytest.raises(QuotaExhausted):
            b.reserve(provider, 1, purpose, run_id="one")


def test_free_plan_control_requests_and_combined_tavily_credits_are_bounded(settings):
    b = prepared(settings)
    b.prepare_final_demo()
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("one")
        b.demo_control_request("one")
        b.demo_control_request("one")
        with pytest.raises(QuotaExhausted):
            b.demo_control_request("one")
        for _ in range(10):
            b.reserve("tavily", 1, "search", run_id="one")
        b.reserve("tavily", 6, "extract", run_id="one")
        with pytest.raises(QuotaExhausted):
            b.reserve("tavily", 1, "extract", run_id="one")


def test_six_stages_regenerated_with_cached_retrieval_no_saved_ai_replay(settings):
    def no_fetch(*a, **kw):
        raise AssertionError("Fixture extraction/cached text should suffice")
    seed = Workflow(settings, SimulationProvider, no_fetch, research_factory=SimulationProvider).execute(ENQUIRY, mode="offline_test")
    seed.mode = "live"  # Test-only recorded-live shape; never submitted as live evidence.
    save_run(seed, settings.run_path())
    b = prepared(settings)
    b.prepare_final_demo()
    calls, updates = [], []
    class Fresh(SimulationProvider):
        def search(self, *args, **kwargs):
            raise AssertionError("Matching research cache must be reused")
        def structured(self, schema, instruction, data, purpose, **kwargs):
            calls.append(purpose)
            return super().structured(schema, instruction, data, purpose, **kwargs)
    with approved_live_execution(True, phase="demo"):
        run = Workflow(settings, Fresh, no_fetch, research_factory=Fresh).execute(
            ENQUIRY, on_update=lambda r: updates.append([s.status for s in r.stages]))
        with pytest.raises(QuotaExhausted):
            Workflow(settings, Fresh, no_fetch, research_factory=Fresh).execute(ENQUIRY)
    assert run.run_id != seed.run_id and run.mode == "live"
    assert all(s.status == "complete" and not s.execution_origin.startswith("cached") for s in run.stages)
    assert {"extraction", "account research:compact", "material comparison", "partner routing", "email drafts"} <= set(calls)
    assert not any(row["event"] == "structured_call_reused" for row in run.logs)
    assert any(row["event"] == "retrieval_reused" for row in run.logs)
    assert any("cached research" in w for w in run.warnings)
    assert all(any(states[i] == "running" for states in updates) for i in range(6))
    assert b.demo_summary()["state"] == "finished"


def test_streamlit_prepared_allowance_requires_manual_approval_then_blocks_second_start(settings, monkeypatch):
    b = prepared(settings)
    b.prepare_final_demo()
    monkeypatch.setenv("RUNS_DIR", settings.runs_dir)
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: True)
    def forbidden(*a, **k):
        raise AssertionError("Rendering/navigation must not construct providers")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    app.radio(key="execution_mode").set_value("Protected live execution").run(timeout=30)
    app.selectbox(key="live_phase_choice").set_value("Record fresh demo").run(timeout=30)
    next(b for b in app.button if "sample enquiry" in b.label.lower()).click().run(timeout=30)
    run_button = next(b for b in app.button if "six-stage analysis" in b.label.lower())
    assert run_button.disabled
    app.checkbox(key="live_action_approval").check().run(timeout=30)
    assert not next(b for b in app.button if "six-stage analysis" in b.label.lower()).disabled
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo("already-started")
    app.run(timeout=30)
    assert next(b for b in app.button if "six-stage analysis" in b.label.lower()).disabled
    assert any("second run is blocked" in w.value for w in app.warning)
    assert not app.exception


def test_live_monitor_renders_checkpoint_and_interrupt_error_without_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    def forbidden(*a, **k):
        raise AssertionError("Monitor renders local checkpoints only")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    from flytbase_bdr.config import Settings
    run = new_run(ENQUIRY, Settings(runs_dir=str(tmp_path)))
    run.stages[0].status = "complete"
    run.stages[1].status = "running"
    class ThreadState:
        alive = True
        def is_alive(self): return self.alive
    thread = ThreadState()
    events = queue.Queue()
    events.put(("update", run))
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["job"] = {"thread": thread, "events": events, "started": time.monotonic() - 12}
    app.run(timeout=30)
    assert not app.exception
    assert app.session_state["run"].stages[1].status == "running"
    assert any("Elapsed:" in c.value for c in app.caption)
    thread.alive = False
    events.put(("error", "One-time demo request limit exhausted"))
    app.run(timeout=30)
    assert not app.exception
    assert any("request limit exhausted" in e.value for e in app.error)
