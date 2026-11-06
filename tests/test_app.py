"""Evaluator navigation: no API calls during read-only replay or screen changes."""
from streamlit.testing.v1 import AppTest
from flytbase_bdr.config import ROOT
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider, fake_fetch


def _forbid(*args, **kwargs):
    raise AssertionError("Rendering the application must never call live providers")


def test_read_only_example_does_not_start_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: False)
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", _forbid)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=25)
    assert not app.exception
    # Main page contains the sample message control and run action.
    sample = next(b for b in app.button if "sample enquiry" in b.label.lower())
    sample.click().run(timeout=25)
    assert "Rodrigo Castillo" in app.text_area[0].value
    run_button = next(b for b in app.button if "six-stage analysis" in b.label.lower())
    assert run_button.disabled
    assert not list(tmp_path.glob("*/run.json"))


def test_five_pages_and_replay_never_call_provider(settings, enquiry, monkeypatch):
    saved = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    monkeypatch.setattr("flytbase_bdr.config.has_api_key", lambda: False)
    monkeypatch.setenv("RUNS_DIR", settings.runs_dir)
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", _forbid)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["run"] = saved
    app.session_state["replay"] = True
    app.run(timeout=30)
    assert not app.exception
    # AppTest returns a fresh widget tree after each run. Retaining an old
    # Radio object across page changes can cause AppTest to include widgets
    # removed from the active page, which triggers a false missing-state KeyError.
    sample = next(b for b in app.button if "sample enquiry" in b.label.lower())
    sample.click().run(timeout=30)
    assert "Rodrigo Castillo" in app.text_area[0].value
    for page in ["Account Intelligence", "Sales Strategy", "AE Handoff", "How It Works & Evidence"]:
        nav = next(r for r in app.radio if "Command Center" in r.options)
        nav.set_value(page).run(timeout=30)
        assert not app.exception, page
        assert app.session_state["run"].run_id == saved.run_id
    nav = next(r for r in app.radio if "Command Center" in r.options)
    nav.set_value("AE Handoff").run(timeout=30)
    assert len(app.get("download_button")) >= 2
    nav = next(r for r in app.radio if "Command Center" in r.options)
    nav.set_value("Sales Strategy").run(timeout=30)
    assert len(app.tabs) == 3
    assert not app.exception
    nav = next(r for r in app.radio if "Command Center" in r.options)
    nav.set_value("Command Center").run(timeout=30)
    assert "Rodrigo Castillo" in app.text_area[0].value  # draft survives navigation
