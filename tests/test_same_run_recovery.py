"""One-time demo recovery contracts. All providers are offline fixtures."""
from flytbase_bdr.workflow import Workflow, new_run
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.provider import ProviderError
from scripts.simulate_offline import SimulationProvider, ENQUIRY


def test_interrupted_demo_can_continue_same_run_without_new_allowance(settings):
    b = ProjectBudget(settings)
    b.reserve("groq", 1, "historical synthetic usage")
    b.prepare_final_demo()
    run = new_run(ENQUIRY, settings, mode="live")
    run.stages[0].status = "running"
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo(run.run_id)
        result = Workflow(settings, provider_factory=SimulationProvider,
                          research_factory=SimulationProvider,
                          fetcher=lambda source, max_chars: None).execute(ENQUIRY, resume=run)
    assert result.run_id == run.run_id
    assert result.stages[0].status == "complete"
    assert any(x.get("event") == "same_run_demo_recovered" for x in result.logs)
    assert b.demo_summary()["state"] == "finished"
    assert b.demo_summary()["run_id"] == run.run_id


def test_interrupted_demo_cannot_use_different_run_id(settings):
    b = ProjectBudget(settings)
    b.reserve("groq", 1, "historical synthetic usage")
    b.prepare_final_demo()
    original = new_run(ENQUIRY, settings, mode="live")
    other = new_run(ENQUIRY, settings, mode="live")
    other.stages[0].status = "running"
    with approved_live_execution(True, phase="demo"):
        b.start_final_demo(original.run_id)
        try:
            Workflow(settings, provider_factory=SimulationProvider,
                     research_factory=SimulationProvider).execute(ENQUIRY, resume=other)
        except ProviderError as exc:
            assert "exact started run ID" in str(exc)
        else:
            raise AssertionError("A different run was allowed to consume the same one-time demo envelope")
    assert b.demo_summary()["state"] == "started"
