"""Regression checks for the source-search and safe retry improvements."""
import httpx
from flytbase_bdr.evidence import (
    rank_sources, source_family_key, relevant_html_excerpt, fetch_source,
)
from flytbase_bdr.models import Source
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider, fake_fetch


def _source(sid, url, title, access="search_excerpt_only"):
    return Source(source_id=sid, url=url, title=title, retrieved_at="2026-11-04T00:00:00+00:00", access=access)


def test_research_prefers_official_filing_over_financial_blog():
    sources = {
        "S_blog": _source("S_blog", "https://example.com/stock/sqm", "SQM investment analysis"),
        "S_sec": _source("S_sec", "https://www.sec.gov/Archives/edgar/data/909037/example.htm", "2025 SQM 20-F Annual Report"),
    }
    assert rank_sources(list(sources), sources, "finance", "Sociedad Quimica (SQM)", "sqm.cl")[0] == "S_sec"


def test_case_study_ranks_before_blog_and_duplicate_mirror_is_suppressed():
    sources = {
        "S_blog": _source("S_blog", "https://flytbase.com/blog/mining", "Mining drones"),
        "S_study": _source("S_study", "https://www.flytbase.com/case-studies/new-client", "New Client Mining case study"),
        "S_study_es": _source("S_study_es", "https://flytbase.com/es/case-studies/new-client", "New Client case study"),
    }
    ranked = rank_sources(list(sources), sources, "materials", "New Client", "new.example")
    assert ranked[0] == "S_study"
    assert len(ranked) == 2
    assert source_family_key(sources["S_study"].url) == source_family_key(sources["S_study_es"].url)


def test_long_report_retains_query_relevant_passages_without_fabrication(monkeypatch):
    source = _source("S_1", "https://reports.example.com/annual", "Annual 20-F")
    source.queries = ["capital expenditures investment 2025"]
    long_html = "<html><body>" + ("<p>General information about mining operations.</p>" * 500) + (
        "<h2>Capital expenditures</h2><p>Capital expenditures in 2025 reached USD 876.7 million "
        "for the entire company, not the proposed drone project.</p>"
    ) + ("<p>Other business overview details.</p>" * 200) + "</body></html>"
    monkeypatch.setattr("flytbase_bdr.evidence.assert_public_url", lambda url: None)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=long_html)))
    fetch_source(source, max_chars=3200, client=client)
    assert source.access == "inspected_page"
    assert source.truncated
    assert "876.7 million" in source.text
    assert "HTML excerpt" in source.text and "not the whole page" in source.inspection_method
    assert len(source.text) <= 3200
    client.close()


def test_explicit_stage_retry_refreshes_old_research_and_regenerates_queries(settings, enquiry):
    original = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(
        enquiry, mode="offline_test")
    original.queries["finance"] = ["obsolete search"]

    class TrackingProvider(FakeProvider):
        queries_received = []
        def search(self, queries, purpose, as_of_date, domains=None):
            self.queries_received.append((purpose, list(queries)))
            return super().search(queries, purpose, as_of_date, domains)

    followup = Workflow(settings, FakeProvider, fake_fetch, research_factory=TrackingProvider).execute(
        enquiry, mode="offline_test", resume=original, rerun_stages={1}, refresh_research={"organisation", "finance", "current"})
    names = [purpose for purpose, _ in TrackingProvider.queries_received]
    assert "search:finance" in names and "search:current" in names and "search:organisation" in names
    assert "search:materials" not in names and "search:partners" not in names
    assert followup.queries["finance"] != ["obsolete search"]
    assert followup.stages[0].execution_origin.startswith("cached")
