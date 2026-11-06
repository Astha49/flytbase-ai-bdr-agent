"""Offline regressions for research completeness and safe decision fallbacks."""
import re
from flytbase_bdr.compact import audit_batches
from flytbase_bdr.evidence_decisions import route_proposal
from flytbase_bdr.evidence import derive_queries
from flytbase_bdr.models import Source, Run, Lead
from flytbase_bdr.provider import estimate_tokens
from flytbase_bdr.workflow import new_run


def test_audit_batches_keep_every_original_claim_and_field_path():
    evidence = {"S_A": Source(source_id="S_A", title="Real source",
        url="https://example.com/article", retrieved_at="2026-01-01", access="inspected_page",
        text="Proven evidence sentence. " * 80)}
    make = lambda i: {"kind":"public", "text":f"Finding {i} references the inspected company.",
                        "evidence":[{"source_id":"S_A","quote":"Proven evidence sentence."}],
                        "input_quote":"", "uncertainty":"", "financial_context":None,"event_date":""}
    data = {"topics":[{"name":"Verified evidence", "claims":[make(i) for i in range(28)],
                      "gaps":[]}], "description":"Study all evidence without dropping findings."}
    batches = audit_batches(data, evidence, target_tokens=750)
    assert len(batches) > 1
    paths = [row["path"] for batch in batches for row in batch["claims_with_paths"]]
    assert paths == [f"topics.0.claims.{i}" for i in range(28)]
    assert any(row["path"] == "description" for batch in batches for row in batch["review_fields"])
    for batch in batches:
        for row in batch["claims_with_paths"]:
            for ref in row["claim"].get("evidence", []):
                assert batch["quotes"][ref["quote_ref"]]["source_id"] == "S_A"
        assert estimate_tokens(str(batch)) < 1500


def test_integrator_fallback_discovers_chilean_form_from_inspected_story(settings, enquiry):
    run = new_run(enquiry, settings, mode="offline_test")
    run.stages[0].output = {"lead":{"company":"Example Mining (EMX)", "geography":"Chile"}}
    sentence = "Asterra, a Chilean drone integrator, installed autonomous drone docks in Chile."
    run.sources["S_A"] = Source(source_id="S_A", url="https://flytbase.com/case-studies/example",
        title="Mining inspection", retrieved_at="2026-11-04", access="inspected_page", text=sentence)
    result = route_proposal(run, ["S_A"])
    assert result.recommended_motion == "direct_ae"
    assert result.candidates and result.candidates[0].name == "Asterra"
    assert result.candidates[0].ecosystem_evidence.evidence[0].quote in sentence
    assert "Not verified" in result.candidates[0].availability


def test_finance_query_is_company_based_without_hardcoded_case_winner(lead):
    lead.company, lead.domain, lead.industry, lead.need = "Example Ports", "ports.example", "shipping", "harbour perimeter security"
    q = derive_queries(lead, "2026-11-04")
    assert "Example Ports" in q["finance"][0]
    assert "harbour" in q["materials"][0]
    assert "sqm" not in q["finance"][0].lower()


def test_official_ir_document_ranks_before_generic_sec_search_snippet():
    from flytbase_bdr.evidence import rank_sources
    unrelated = Source(source_id="S_U", url="https://www.sec.gov/Archives/edgar/data/111111/fake.htm",
                       title="20-F", retrieved_at="2026-11-04", access="search_excerpt_only",
                       search_context="SQM capital expenditure annual report stock report")
    official = Source(source_id="S_O", url="https://ir.sqm.com/reports/annual-2025.html",
                      title="SQM 2025 Annual Report", retrieved_at="2026-11-04", access="search_excerpt_only",
                      search_context="Sociedad Quimica y Minera investment priorities")
    ordered = rank_sources(["S_U", "S_O"], {"S_U": unrelated, "S_O": official},
                           "finance", "Sociedad Quimica y Minera de Chile (SQM)", "sqm.cl")
    assert ordered[0] == "S_O"


def test_customer_story_discovery_uses_nearby_heading_for_read_link():
    from flytbase_bdr.story_discovery import story_links_from_html
    html = ("<article><h3>How Example Ports Automates Harbour Security</h3>"
            "<a href='/case-studies/example-ports-harbour'>Read story</a></article>")
    rows = story_links_from_html(html, {"company":"Example Ports", "industry":"shipping",
                                           "need":"harbour perimeter security", "referral":""})
    assert rows and rows[0]["title"].startswith("How Example Ports")
    assert rows[0]["url"].endswith("/case-studies/example-ports-harbour")
