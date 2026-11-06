from flytbase_bdr.cli import main
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider, fake_fetch


def test_replay_has_no_provider_call_and_partial_exit_code(settings, enquiry, monkeypatch, capsys):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    path = settings.run_path() / run.run_id / "run.json"
    monkeypatch.setattr("sys.argv", ["cli", "--replay", str(path)])
    monkeypatch.setenv("RUNS_DIR", settings.runs_dir)
    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not create provider")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    assert main() == 2
    output = capsys.readouterr().out
    assert "REPLAY" in output and run.run_id in output
    assert "SYNTHETIC OFFLINE TEST" in output
    assert f"Results: {path.parent}" in output


def test_external_saved_replay_reports_the_actual_folder(tmp_path, monkeypatch, capsys):
    from scripts.simulate_offline import simulate
    folder, _ = simulate(tmp_path / "public_demo")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "different_private_folder"))
    monkeypatch.setattr("sys.argv", ["cli", "--replay", str(folder / "run.json")])
    assert main() == 0
    assert f"Results: {folder}" in capsys.readouterr().out
