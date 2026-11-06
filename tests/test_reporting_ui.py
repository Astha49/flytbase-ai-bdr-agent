"""Regression: long nested saved records must be concise in UI without hiding source facts."""
from flytbase_bdr.reporting import stage_markdown
from flytbase_bdr.models import Run


def test_qualification_is_not_unnamed_item_dump(settings, enquiry):
    from flytbase_bdr.workflow import Workflow
    from conftest import FakeProvider, fake_fetch
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    html = stage_markdown(run.stages[0], run.sources, include_warnings=False)
    assert "Priority score breakdown" in html
    assert "| Signal | Points | Enquiry evidence |" in html
    assert "**Item " not in html


def test_partial_case_not_rewritten_as_verified(settings, enquiry):
    from flytbase_bdr.workflow import Workflow
    from conftest import FakeProvider, fake_fetch
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    run.stages[3].output["primary"] = None
    output = stage_markdown(run.stages[3], run.sources)
    assert "No case study selected" in output
    assert "unverified case" in output
