"""All tests are synthetic; these findings are never presented as live source research."""
from flytbase_bdr.diagnostics import assess_run, own_company_mentions, review_markdown
from flytbase_bdr.models import Run, Source


def fake_run():
    run = Run(run_id="synthetic_review", mode="live", started_at="2026-11-04T00:00:00Z", as_of_date="2026-11-04", input="Sample inbound enquiry", config={})
    run.stages[0].output = {"lead": {"company": "Example Industrial Company (EIC)"}}
    run.stages[3].output = {"candidates": [{"own_company_expansion_assessment": "No evidence EIC uses FlytBase"}], "primary": None}
    run.sources["S_public"] = Source(source_id="S_public", title="EIC webinar", url="https://flytbase.com/webinars/eic",
                                     retrieved_at="2026-11-04T00:00:00Z", access="inspected_page",
                                     text="In collaboration with FlytBase, EIC has deployed an autonomous inspection workflow.")
    run.sources["S_summary"] = Source(source_id="S_summary", title="EIC press", url="https://flytbase.com/blog/eic",
                                      retrieved_at="2026-11-04T00:00:00Z", access="search_excerpt_only",
                                      search_context="EIC and FlytBase partnership mentioned in a search snippet.")
    return run


def test_read_only_diagnostics_find_existing_customer_contradiction():
    run = fake_run()
    before = run.model_dump(mode="json")
    signals = own_company_mentions(run)
    assert len(signals) == 1 and signals[0]["source_id"] == "S_public"
    review = assess_run(run)
    assert not review["safe_to_claim_full_acceptance"]
    assert any("contradiction" in x.lower() for x in review["blocking_review_items"])
    assert "EIC" in review_markdown(review)
    assert run.model_dump(mode="json") == before


def test_search_snippet_cannot_establish_prior_customer_coverage():
    run = fake_run()
    run.sources["S_public"].access = "search_excerpt_only"
    assert not own_company_mentions(run)
