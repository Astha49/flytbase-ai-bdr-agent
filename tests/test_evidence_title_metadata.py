"""No-network regression: a public document title is metadata, not a case-study outcome."""
from flytbase_bdr.compact import audit_payload
from flytbase_bdr.models import Source


def test_case_title_carries_inspected_source_metadata(source):
    source.title = "Inspected mining case study"
    data = {"candidates": [{"source_id": source.source_id, "title": source.title,
                            "relevance": {"text": "Unverified until quoted", "kind": "unknown",
                                          "evidence": [], "input_quote": "", "uncertainty": "",
                                          "financial_context": None, "event_date": ""}}]}
    fields = audit_payload(data, {source.source_id: source})["review_fields"]
    title = next(v for v in fields if v["path"] == "candidates.0.title")
    assert title["source_title_matches"] is True
    assert title["inspected_source_title"] == source.title


def test_wrong_title_is_not_accepted_from_metadata(source):
    source.title = "Real source title"
    data = {"candidates": [{"source_id": source.source_id, "title": "Invented title"}]}
    fields = audit_payload(data, {source.source_id: source})["review_fields"]
    title = next(v for v in fields if v["path"] == "candidates.0.title")
    assert title["source_title_matches"] is False


def test_search_excerpt_cannot_verifiy_a_title(source):
    source.access = "search_excerpt_only"
    data = {"candidates": [{"source_id": source.source_id, "title": source.title}]}
    fields = audit_payload(data, {source.source_id: source})["review_fields"]
    title = next(v for v in fields if v["path"] == "candidates.0.title")
    assert "source_title_matches" not in title
