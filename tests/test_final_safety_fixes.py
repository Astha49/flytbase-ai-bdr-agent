"""Protect the two concrete production failures and wrong-issuer research."""
from flytbase_bdr.evidence import is_issuer_document, derive_queries
from flytbase_bdr.evidence_decisions import material_proposals, route_proposal
from flytbase_bdr.models import Source, Run
from flytbase_bdr.workflow import new_run
from flytbase_bdr.selection import select_materials, decide_routing
from flytbase_bdr.grounding import audit_mechanical
from flytbase_bdr.compact import evidence_batch
from flytbase_bdr.providers.groq import strict_schema
from flytbase_bdr.models import Materials, Routing


def mock_source(sid, url, text):
    return Source(source_id=sid, url=url, title="Realistic industrial case study fixture",
                  retrieved_at="2026-11-04T00:00:00+00:00", access="inspected_page", text=text)


def lead_run(settings, lead, enquiry):
    run = new_run(enquiry, settings, mode="offline_test")
    run.stages[0].output = {"lead": lead.model_dump()}
    return run


def test_unrelated_sec_filings_rejected(lead):
    other = mock_source("S_other", "https://www.sec.gov/Archives/edgar/data/111/other.htm",
                        "PHOENIX NEW MEDIA LIMITED annual report 2025")
    other.title = "20-F"
    assert not is_issuer_document(other, lead.company, lead.domain)
    related = mock_source("S_true", "https://www.sec.gov/Archives/edgar/data/222/filing.htm",
                          "SOCIEDAD QUÍMICA Y MINERA DE CHILE S.A. Annual report. 2025 capital expenditures.")
    assert is_issuer_document(related, lead.company, lead.domain)


def test_generated_queries_target_case_studies_dynamically(lead):
    plan = derive_queries(lead, "2026-11-04")
    assert len(plan) == 5 and sum(map(len, plan.values())) == 10
    assert all("case study" in q and "site:flytbase.com/case-studies" in q for q in plan["materials"])
    assert '"SQM"' in plan["materials"][0]
    lead.company = "Sample Operations (ABC)"
    assert '"ABC"' in derive_queries(lead, "2026-11-04")["materials"][0]


def test_fallback_refuses_to_pass_blog_as_case_study(settings, lead, enquiry):
    run = lead_run(settings, lead, enquiry)
    run.sources["S_blog"] = mock_source("S_blog", "https://flytbase.com/blog/example",
                                          "SQM mining drone inspection operations in Chile")
    assert material_proposals(run, ["S_blog"]).candidates == []


def test_case_comparison_selects_inspected_evidence_only(settings, lead, enquiry):
    run = lead_run(settings, lead, enquiry)
    run.sources["S_case"] = mock_source("S_case", "https://flytbase.com/case-studies/dynamic-record",
        "SQM operates a mining site in Chile. SQM and a local team deployed drones for inspection of iodine leaching piles. "
        "The inspection workflow sends collected images for analysis.")
    proposed = material_proposals(run, ["S_case"])
    assert len(proposed.candidates) == 1
    assert {x.dimension for x in proposed.candidates[0].dimensions} == {
        "industry", "use_case", "operating_context", "geography", "referral", "same_company"}
    findings = audit_mechanical(proposed.model_dump(), run.sources, enquiry, run.as_of_date)
    assert findings == []
    chosen = select_materials(proposed, run.sources, enquiry, run.as_of_date, findings)
    assert chosen["primary"] is not None
    assert not chosen["primary"]["breakdown"]["operating_context"]  # 24/7 unproved
    assert not chosen["primary"]["breakdown"]["referral"]  # referral unproved


def test_chile_partner_proposal_is_inspected_not_assumed(settings, lead, enquiry):
    run = lead_run(settings, lead, enquiry)
    run.sources["S_partner"] = mock_source("S_partner", "https://flytbase.com/case-studies/partner",
        "The project was delivered with Adentu, a Chile-based integrator specializing in drone autonomy.")
    proposed = route_proposal(run, ["S_partner"])
    assert proposed.recommended_motion == "direct_ae"  # enterprise commercial ownership
    assert proposed.candidates[0].name == "Adentu"
    issues = audit_mechanical(proposed.model_dump(), run.sources, enquiry, run.as_of_date)
    assert not issues
    route = decide_routing(proposed, run.sources, enquiry, run.as_of_date, "Chile", issues)
    assert route["candidate_checks"][0]["country_presence_verified"]
    assert not route["candidate_checks"][0]["country_coverage_verified"]  # domicile alone is not country-wide service coverage
    assert route["candidates"][0]["availability"].startswith("Not verified")


def test_fallback_never_injects_preselected_source(settings, lead, enquiry):
    run = lead_run(settings, lead, enquiry)
    run.sources["S_new"] = mock_source("S_new", "https://flytbase.com/case-studies/dynamic-copper",
        "A port operator uses drones for perimeter security in Canada.")
    assert not material_proposals(run, ["S_new"]).candidates


def test_compact_context_stays_small(settings):
    sources = {f"S_{i}": mock_source(f"S_{i}", f"https://flytbase.com/case-studies/{i}",
                                     "Inspection across mining facilities and operations. " * 200)
               for i in range(8)}
    batch = evidence_batch(sources, list(sources), settings, max_sources=3, max_chars=2250)
    assert len(batch) == 3
    assert sum(len(row["text"]) for row in batch.values()) <= 2250
    assert strict_schema(Materials)["additionalProperties"] is False
    assert strict_schema(Routing)["additionalProperties"] is False
