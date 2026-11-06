"""Offline tests for source-bound allowances, dashboard state and real exports."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json

import pytest
from streamlit.testing.v1 import AppTest

from conftest import FakeProvider, fake_fetch
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import ROOT
from flytbase_bdr.execution import approved_live_execution, LiveExecutionBlocked
from flytbase_bdr.provider import QuotaExhausted
from flytbase_bdr.reporting import save_run, handoff_export, load_run, safe_text
from flytbase_bdr.run_allowance import approve, execute, overview, plan, stamp
from flytbase_bdr.workflow import Workflow, fork_resume


@pytest.fixture
def recording(settings, enquiry):
    # Explicitly fictional provider/record for exercising a production-mode gate.
    class RecordedFixtureProvider(FakeProvider):
        def search(self, *args, **kwargs):
            output = super().search(*args, **kwargs)
            # Supply an actual case-shaped fixture independently of optional
            # private URL hints. It remains explicitly fictional test evidence.
            return json.loads(json.dumps(output).replace("/test-fixture", "/case-studies/__offline_fixture__/test-inspection"))
    run = Workflow(settings, RecordedFixtureProvider, fake_fetch, research_factory=RecordedFixtureProvider).execute(enquiry, mode="offline_test")
    run.mode = "live"
    run.usage = [{"provider": "groq", "purpose": "account research", "total_tokens": 51796}]
    folder = save_run(run, settings.run_path())
    b = ProjectBudget(settings)
    old = (stamp() - timedelta(days=1)).isoformat()
    b.write({"ceilings": {"groq": 110000, "tavily": 40},
             "entries": [{"id": "historical", "provider": "groq", "purpose": "history", "at": old, "actual": 207898, "reserved": 207898}],
             "phase_limits": {"repair_cumulative_cap": 64241, "demo_reserve_at_approval": 38000, "emergency_reserve": 7759},
             "demo_history": [{"id": "old-demo", "state": "finished"}]})
    return folder / "run.json", b


def approved(settings, path, **kwargs):
    return approve(settings, path, 63000, kwargs.pop("used_today", 0), stamp().isoformat(), approved=True, free_only=True, **kwargs)


def test_plan_distinguishes_history_and_today_without_mutation(settings, recording):
    path, budget = recording
    before = budget.path.read_bytes()
    proposal, view = plan(settings, path), overview(settings)
    assert proposal["recommended_new_run_cap"] == 63000
    assert proposal["tavily_credits"] == 0 and not proposal["execution_authorized"]
    assert view["historical_groq_reported"] == 207898 and view["local_groq_today_counted"] == 0
    assert view["new_run_allowances"] == [] and not view["provider_balance_verified"]
    assert budget.path.read_bytes() == before


@pytest.mark.parametrize("approval,free", [(False, False), (False, True), (True, False)])
def test_budget_approval_is_separate_and_default_blocked(settings, recording, approval, free):
    path, budget = recording
    before = budget.path.read_bytes()
    with pytest.raises(ValueError, match="explicit budget approval"):
        approve(settings, path, 63000, 0, stamp().isoformat(), approved=approval, free_only=free)
    assert budget.path.read_bytes() == before


def test_approval_appends_without_resetting_history_or_old_ceiling(settings, recording):
    path, budget = recording
    before = budget.read()
    item = approved(settings, path)
    after = budget.read()
    for key in before:
        assert after[key] == before[key]
    assert item["groq_tokens"] == 63000 and item["tavily_credits"] == 0
    assert len(after["execution_allowances"]) == 1
    with pytest.raises(ValueError, match="duplicate"):
        approved(settings, path)


def test_daily_and_emergency_limits_do_not_follow_legacy_ceiling(settings, recording):
    path, budget = recording
    before = budget.path.read_bytes()
    with pytest.raises(QuotaExhausted, match="headroom"):
        approved(settings, path, used_today=100000)
    assert budget.path.read_bytes() == before
    with pytest.raises(ValueError, match="15 minutes"):
        approve(settings, path, 63000, 0, (stamp()-timedelta(hours=1)).isoformat(), approved=True, free_only=True)


def test_new_reservations_bound_to_exact_run_and_no_tavily(settings, recording):
    path, budget = recording
    item = approved(settings, path)
    data = budget.read()
    data["execution_allowances"][0].update(state="started", run_id="new-id")
    budget.write(data)
    with approved_live_execution(True, phase="new_run", allowance_id=item["id"], confirmed_free_quota=True):
        with pytest.raises(QuotaExhausted, match="exact run"):
            budget.reserve("groq", 100, "test", run_id="wrong")
        with pytest.raises(QuotaExhausted, match="zero Tavily"):
            budget.reserve("tavily", 1, "search", run_id="new-id")
        ticket = budget.reserve("groq", 2000, "test", run_id="new-id")
        budget.settle(ticket, 1200)
    assert budget.read()["entries"][0] == data["entries"][0]
    assert overview(settings)["new_run_allowances"][0]["groq_remaining"] == 61800


def test_daily_quota_and_unknown_reservations_stop_dispatch(settings, recording):
    path, budget = recording
    item = approved(settings, path)
    data = budget.read()
    data["execution_allowances"][0].update(state="started", run_id="new-id")
    data["entries"].append({"provider":"groq", "at":stamp().isoformat(), "actual":None, "reserved":160000, "purpose":"outside-allowance"})
    budget.write(data)
    before = budget.path.read_bytes()
    with approved_live_execution(True, phase="new_run", allowance_id=item["id"], confirmed_free_quota=True):
        with pytest.raises(QuotaExhausted, match="daily"):
            budget.reserve("groq", 1000, "test", run_id="new-id")
    assert budget.path.read_bytes() == before


def test_new_run_context_and_tavily_probe_are_fail_closed(settings, enquiry):
    with pytest.raises(LiveExecutionBlocked):
        with approved_live_execution(True, phase="new_run"):
            pass
    from flytbase_bdr.providers.tavily import TavilyProvider
    with approved_live_execution(True, phase="new_run", allowance_id="fixture", confirmed_free_quota=True):
        with pytest.raises(QuotaExhausted, match="including quota probes"):
            TavilyProvider(settings, None)


def test_changed_source_or_expired_day_cannot_execute(settings, recording):
    path, budget = recording
    item = approved(settings, path)
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Source record changed"):
        execute(settings, item["id"], approved=True)
    assert budget.read()["execution_allowances"][0]["state"] == "approved"
    data = budget.read()
    data["execution_allowances"][0]["utc_day"] = (stamp()-timedelta(days=1)).date().isoformat()
    budget.write(data)
    with pytest.raises(QuotaExhausted, match="expired"):
        execute(settings, item["id"], approved=True)


def test_model_change_cannot_use_an_approval_for_another_model(settings, recording):
    path, budget = recording
    item = approved(settings, path)
    before = budget.path.read_bytes()
    settings.groq_model = "openai/gpt-oss-20b"
    with pytest.raises(ValueError, match="Model changed"):
        execute(settings, item["id"], approved=True)
    assert budget.path.read_bytes() == before


def test_cancellation_never_removes_history_or_refunds_usage(settings, recording):
    from flytbase_bdr.run_allowance import cancel
    path, budget = recording
    item = approved(settings, path)
    before = deepcopy(budget.read()["entries"])
    with pytest.raises(ValueError, match="confirmation"):
        cancel(settings, item["id"])
    cancel(settings, item["id"], approved=True)
    assert budget.read()["entries"] == before
    assert budget.read()["execution_allowances"][0]["state"] == "cancelled"
    with pytest.raises(ValueError, match="never-started"):
        cancel(settings, item["id"], approved=True)


def test_fork_usage_is_new_only_and_original_unchanged(settings, recording):
    path, _ = recording
    before = path.read_bytes()
    original = load_run(path)
    fork = fork_resume(original, settings)
    assert not fork.usage and original.usage
    assert fork.run_id != original.run_id
    assert fork.logs[-1]["historical_groq_tokens"] == 51796
    assert path.read_bytes() == before


def test_cache_only_execution_wrapper_uses_existing_workflow_with_mocked_ai(settings, recording, monkeypatch):
    path, budget = recording
    item = approved(settings, path)
    before, previous = path.read_bytes(), deepcopy(budget.read()["entries"])
    with pytest.raises(ValueError, match="live-launch approval"):
        execute(settings, item["id"])
    init = Workflow.__init__
    providers = []
    class MockAI(FakeProvider):
        def __init__(self, cfg, run):
            super().__init__(cfg, run)
            assert cfg.max_retries == 0
            assert "_structured" not in run.retrieval_cache
            providers.append(self)
        def search(self, *a, **k):
            raise AssertionError("No fresh search allowed")
    def mock_init(self, cfg, **kwargs):
        init(self, cfg, provider_factory=MockAI, **kwargs)
    monkeypatch.setattr(Workflow, "__init__", mock_init)
    def no_directory(*args, **kwargs):
        raise AssertionError("A cache-only allowance must not make a direct HTTP directory lookup")
    monkeypatch.setattr("flytbase_bdr.story_discovery.discover_official_stories", no_directory)
    snapshots = []
    result = execute(settings, item["id"], approved=True,
                     on_update=lambda run: snapshots.append([s.status for s in run.stages]))
    assert len(result.stages) == 6 and all(s.output for s in result.stages)
    assert snapshots[0][0] == "complete" and snapshots[0][1:] == ["pending"] * 5
    assert providers and result.run_id != load_run(path).run_id
    assert path.read_bytes() == before and budget.read()["entries"] == previous
    assert budget.read()["execution_allowances"][0]["state"] == "finished"
    with pytest.raises(ValueError, match="duplicate launch"):
        execute(settings, item["id"], approved=True)


def test_handoff_export_preserves_status_unknowns_and_citations(settings, recording):
    path, _ = recording
    run = load_run(path)
    before = run.model_dump()
    content = handoff_export(run)
    assert safe_text(run.run_id) in content and "not a new execution" in content
    assert all(s.name in content and s.status in content for s in run.stages)
    assert "Rodrigo" in content and "Which year" in content
    assert "https://" in content and run.model_dump() == before


def test_early_execution_failure_is_saved_as_failed_not_forever_running(settings, recording, monkeypatch):
    path, budget = recording
    item = approved(settings, path)
    before = path.read_bytes()
    def fail(*a, **k):
        raise RuntimeError("Synthetic constructor failure")
    monkeypatch.setattr(Workflow, "__init__", fail)
    with pytest.raises(RuntimeError):
        execute(settings, item["id"], approved=True)
    row = budget.read()["execution_allowances"][0]
    failed = load_run(settings.run_path() / row["run_id"] / "run.json")
    assert failed.status == "failed" and failed.finished_at
    assert row["state"] == "finished" and row["result_status"] == "failed"
    assert path.read_bytes() == before


def test_rule_based_case_is_exported_as_provisional_not_verified(settings, recording):
    from conftest import make_material
    from flytbase_bdr.reporting import stage_markdown
    path, _ = recording
    run = load_run(path)
    stage = run.stages[3]
    row = {"candidate": make_material().model_dump(), "eligible": True, "score": 55}
    stage.output.update(primary=row, comparison=[row], groundedness={"semantic_review": "rule_based_fallback"})
    report = stage_markdown(stage, run.sources)
    assert "Provisional: semantic review unavailable" in report
    assert "Verified eligibility" not in report


def test_all_pages_have_three_downloads_without_api_or_history_writes(settings, recording, monkeypatch):
    path, budget = recording
    before = (path.read_bytes(), budget.path.read_bytes())
    monkeypatch.setenv("RUNS_DIR", str(settings.run_path()))
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only UI must not construct any provider")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    for page in ("Command Center", "Account Intelligence", "Sales Strategy", "AE Handoff", "How It Works & Evidence"):
        next(r for r in app.radio if "Command Center" in r.options).set_value(page).run(timeout=30)
        assert not app.exception, page
        labels = [button.label for button in app.get("download_button")]
        assert any("AE handoff" in label for label in labels), (page, labels)
        assert len(labels) >= 3
    assert (path.read_bytes(), budget.path.read_bytes()) == before


def test_real_latest_partial_run_renders_all_five_pages_read_only(monkeypatch):
    path = ROOT / "runs/20261105T195016_6b3a6fb0d3/run.json"
    if not path.exists():
        pytest.skip("Private latest execution is excluded from public source")
    budget = path.parent.parent / "project_budget.json"
    before = (path.read_bytes(), budget.read_bytes())
    monkeypatch.setenv("RUNS_DIR", str(path.parent.parent))
    def forbidden(*a, **k):
        raise AssertionError("Actual saved-run rendering must not construct providers")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["run"], app.session_state["replay"] = load_run(path), True
    app.run(timeout=30)
    for page in ("Command Center", "Account Intelligence", "Sales Strategy", "AE Handoff", "How It Works & Evidence"):
        next(r for r in app.radio if "Command Center" in r.options).set_value(page).run(timeout=30)
        assert not app.exception, page
        assert len(app.get("download_button")) >= 3
        assert app.session_state["run"].status == "partial"
    assert (path.read_bytes(), budget.read_bytes()) == before
