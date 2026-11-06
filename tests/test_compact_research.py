"""Budget-efficient evidence-backed synthesis. All tests use synthetic sources."""
from conftest import FakeProvider, fake_fetch
from flytbase_bdr.models import Research
from flytbase_bdr.provider import ProviderError
from flytbase_bdr.workflow import Workflow


def test_compact_account_requires_one_model_synthesis(settings, enquiry):
    providers = []
    def factory(cfg, run):
        value = FakeProvider(cfg, run)
        providers.append(value)
        return value
    run = Workflow(settings, factory, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    purposes = [purpose for purpose, _ in providers[0].received]
    assert purposes.count("account research:compact") == 1
    assert not any(p.startswith("account topic:") for p in purposes)
    assert "account positioning" not in purposes
    assert len(run.stages[1].output["topics"]) == 5
    assert any(x.get("event") == "compact_account_research" for x in run.logs)


def test_compact_research_failure_preserves_honest_gaps(settings, enquiry):
    class NoSynthesis(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is Research:
                raise ProviderError("Synthetic quota block")
            return super().structured(schema, instruction, data, purpose, **kwargs)
    run = Workflow(settings, NoSynthesis, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    stage = run.stages[1]
    assert stage.status == "partial"
    assert len(stage.output["topics"]) == 5
    assert all(not topic["claims"] and topic["gaps"] for topic in stage.output["topics"])
    assert not run.stages[5].output["top_three_research_findings"]
