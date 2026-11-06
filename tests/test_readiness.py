"""Acceptance guidance reflects the run and never invents completion."""
from flytbase_bdr.readiness import check_requirements, submission_checklist
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider, fake_fetch


def test_incomplete_saved_run_has_specific_user_facing_tasks(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    rows = check_requirements(run)
    assert len(rows) == 6
    assert all(row["next"] and row["details"] for row in rows)
    assert rows[0]["state"] == "ready"
    assert rows[5]["state"] != "ready"  # synthetic research has only one distinct finding
    assert len(submission_checklist(run)) == 3
    assert submission_checklist(run)[-1]["status"] == "Record yourself"


def test_partial_run_checklist_from_real_record_is_not_falsely_all_done():
    import json
    from pathlib import Path
    from flytbase_bdr.models import Run
    path = Path(__file__).resolve().parents[2] / "Flytbase-run.json"
    if not path.exists():
        return
    run = Run.model_validate_json(path.read_text(encoding="utf-8"))
    rows = check_requirements(run)
    assert rows[1]["state"] == "needs_work"
    assert rows[3]["state"] == "needs_work"
    assert rows[4]["state"] == "needs_work"
    assert rows[5]["state"] == "needs_work"
