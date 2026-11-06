import hashlib
import json
from streamlit.testing.v1 import AppTest
from flytbase_bdr.config import ROOT
from flytbase_bdr.planning import continuation_and_recording_allocation
from flytbase_bdr.reporting import load_run, json_export
from scripts.simulate_offline import simulate


def test_realistic_six_stage_simulation_and_export_checks(tmp_path):
    folder, result = simulate(tmp_path / "public_demo")
    assert result["network_requests"] == 0 and not result["live_acceptance"]
    assert len(result["checks"]) == 19 and all(result["checks"].values())
    run = load_run(folder / "run.json")
    assert run.mode == "offline_test" and run.status == "complete"
    assert all(stage.status == "complete" for stage in run.stages)
    assert run.stages[5].output["important_limitations"]  # valid discovery caveats survive a complete briefing
    assert run.stages[3].output["supporting"][0]["score"] == 75
    assert not list((tmp_path / "public_demo").glob("**/project_budget.json"))


def test_shareable_demo_replay_needs_no_keys_or_providers(tmp_path, monkeypatch):
    folder, _ = simulate(tmp_path / "public_demo")
    run = load_run(folder / "run.json")
    before = hashlib.sha256((folder / "run.json").read_bytes()).hexdigest()
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: False)
    monkeypatch.setattr("flytbase_bdr.config.credential_status", lambda: {"GROQ_API_KEY": False, "TAVILY_API_KEY": False})
    monkeypatch.setenv("RUNS_DIR", str(folder.parent))
    def forbidden(*args, **kwargs):
        raise AssertionError("Recruiter inspection must not construct providers")
    for module in ("groq.GroqProvider", "tavily.TavilyProvider"):
        monkeypatch.setattr(f"flytbase_bdr.providers.{module}.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    assert not app.exception
    assert any(r.value == "Read-only demonstration" for r in app.radio)
    assert any(r.value == "Command Center" for r in app.radio)
    assert any("fictional simulation" in info.value.lower() for info in app.info)
    run_button = next(b for b in app.button if "six-stage analysis" in b.label.lower())
    assert run_button.disabled
    nav = next(r for r in app.radio if "Command Center" in r.options)
    nav.set_value("AE Handoff").run(timeout=30)
    assert not app.exception and len(app.get("download_button")) >= 2
    app.run(timeout=30)
    assert not app.exception
    assert json.loads(json_export(app.session_state["run"])) == run.model_dump(mode="json")
    assert before == hashlib.sha256((folder / "run.json").read_bytes()).hexdigest()
    assert not (folder.parent / "project_budget.json").exists()


def test_two_live_run_allowance_math_is_read_only(tmp_path, settings):
    folder, _ = simulate(tmp_path / "public_demo")
    run = load_run(folder / "run.json")
    settings.runs_dir = str(tmp_path / "budget")
    settings.run_path().mkdir()
    # A saved exhausted reservation is preserved rather than optimistically refunded.
    from flytbase_bdr.budget import ProjectBudget
    budget = ProjectBudget(settings)
    budget.reserve("groq", 38241, "fictional historical usage")
    ledger = settings.run_path() / "project_budget.json"
    before = ledger.read_bytes()
    plan = continuation_and_recording_allocation(run, settings)
    assert plan["available_application_tokens"] == 1759
    assert plan["lower"] == {"workload_tokens": 25400, "safety_reserve_tokens": 7500,
                             "required_headroom_tokens": 32900, "additional_allowance_tokens": 31141}
    assert plan["upper"]["additional_allowance_tokens"] == 64841
    assert not plan["authorization"] and ledger.read_bytes() == before


def test_simulation_refuses_to_write_into_private_runs():
    import pytest
    with pytest.raises(ValueError, match="never the private runs"):
        simulate(ROOT / "runs")
