"""Dynamic research and degraded workflow must remain honest with limited credits."""
from flytbase_bdr.evidence import derive_queries
from flytbase_bdr.workflow import Workflow
from flytbase_bdr.models import AccountAdvice
from flytbase_bdr.provider import ProviderError
from conftest import FakeProvider, fake_fetch, make_lead


def test_search_plan_is_dynamic_and_bounded(enquiry):
    lead = make_lead(enquiry)
    query_groups = derive_queries(lead, "2026-11-04")
    assert list(query_groups) == ["organisation", "finance", "current", "materials", "partners"]
    assert sum(len(v) for v in query_groups.values()) == 10
    assert any("case study" in text and '"SQM"' in text for text in query_groups["materials"])
    assert any("Anglo American" in text for text in query_groups["materials"])
    lead.company = "Example Copper (EC)"
    lead.referral = "Example Mining"
    lead.geography = "Peru"
    alt = derive_queries(lead, "2028-01-06")
    assert any('"EC"' in text for text in alt["materials"])
    assert not any("SQM" in q or "Anglo American" in q for group in alt.values() for q in group)
    assert any("2028" in q for q in alt["finance"])


def test_account_summary_limit_preserves_retrieved_topics(settings, enquiry):
    class UnableToSummarise(FakeProvider):
        def structured(self, schema, *args, **kwargs):
            if schema is AccountAdvice:
                raise ProviderError("Summary could not finish; within free tokens")
            return super().structured(schema, *args, **kwargs)

    # Exercise the legacy multi-call research path explicitly.
    settings = settings.model_copy(update={"compact_account_research": False})
    run = Workflow(settings, UnableToSummarise, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    research = run.stages[1]
    assert research.status == "partial"
    assert len(research.output["topics"]) == 5
    assert any("positioning unfinished" in w.lower() for w in research.warnings)
    assert not research.output["positioning"]
