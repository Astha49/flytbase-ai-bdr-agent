import json
from pathlib import Path
from flytbase_bdr.research_candidates import candidates_for_lead
from flytbase_bdr.evidence import search_sources


def test_only_matching_account_gets_candidate_urls(tmp_path):
    pack = {"schema": "flytbase_public_research_evidence_pack_v1",
            "lead_supplied_input": {"company": "Example Industry (EX)", "email": "buyer@example.com"},
            "sources": [{"id": "S1", "url": "https://www.example.com/finance", "title": "An example"}],
            "public_facts": [{"id": "F1", "category": "financial", "source_ids": ["S1"]}]}
    (tmp_path / "company_evidence_pack.json").write_text(json.dumps(pack))
    match = {"company": "Example Industry (EX)", "domain": "example.com"}
    assert len(candidates_for_lead(match, "finance", tmp_path)) == 1
    assert not candidates_for_lead({"company":"Other Co", "domain":"other.com"}, "finance", tmp_path)
    assert not candidates_for_lead(match, "materials", tmp_path)


def test_candidate_does_not_become_verified_evidence(tmp_path):
    pack = {"schema": "flytbase_public_research_evidence_pack_v1",
            "lead_supplied_input": {"company": "Example", "email": "buyer@example.com"},
            "sources": [{"id": "S1", "url": "https://www.example.com/finance", "title": "Example results"}],
            "public_facts": [{"id": "F1", "category": "financial", "claim": "Fabricated claim should never appear",
                              "source_ids": ["S1"]}]}
    (tmp_path / "company_evidence_pack.json").write_text(json.dumps(pack))
    hints = candidates_for_lead({"company":"Example", "domain":"example.com"}, "finance", tmp_path)
    sources = {}
    ids = search_sources({"results": hints}, [], sources)
    assert ids and sources[ids[0]].access == "search_excerpt_only"
    assert not sources[ids[0]].text
    assert "Fabricated claim" not in str(sources[ids[0]].model_dump())
