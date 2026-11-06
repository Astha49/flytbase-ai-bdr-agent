"""Regression tests for the two failed November 5 live demonstrations."""
import json
from pathlib import Path

from flytbase_bdr.evidence_decisions import material_proposals
from flytbase_bdr.models import Source, Run
from flytbase_bdr.research_candidates import candidates_for_lead
from flytbase_bdr.safe_email_recovery import generate_safe_drafts

ENQUIRY = ("From: Rodrigo Castillo (r.castillo@sqm.cl)\n"
           "Title: Head of Operations, Northern Operations Division\n"
           "Company: Sociedad Quimica y Minera de Chile (SQM), Chile\n"
           "Subject: Autonomous inspection for our Atacama lithium sites\n"
           "Context: Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites in the Atacama Desert. "
           "Contracted crews are expensive and hazardous. Referred by Anglo American. Internal budget conversation scheduled for Q3.\n")


def test_empty_ai_emails_recover_as_usable_no_public_claims():
    draft = lambda branch: dict(branch=branch, subject="Subject withheld — review required", paragraphs=[],
                                trigger="Conditional", why_this_message="Discover", if_buyer_responds="Follow up",
                                hypothetical=branch != "initial", review_status="needs_review")
    result, recovered = generate_safe_drafts(ENQUIRY, {"company":"Sociedad Quimica y Minera de Chile (SQM)"},
        {"drafts":[draft(b) for b in ("initial","no_reply","interested","budget_clarification","stakeholder_referral")]},
        {}, "2026-11-05")
    assert len(recovered) == 5
    assert all(d['subject'] and len(d['paragraphs']) >= 2 for d in result['drafts'])
    assert all(p['kind'] != 'public' for d in result['drafts'] for p in d['paragraphs'])
    assert all(d['review_status'] == 'source_limited_fallback' for d in result['drafts'])
    assert "Which calendar year" in " ".join(p['text'] for p in result['drafts'][3]['paragraphs'])
    assert "not AI" in result['safe_recovery']['origin']


def test_valid_emails_are_not_replaced():
    original = {"drafts":[{"branch":"initial", "subject":"Existing safe subject", "paragraphs":[{"text":"Hello"}],
                            "review_status":"checked"}]}
    result, recovered = generate_safe_drafts(ENQUIRY, {}, original, {}, "2026-11-05")
    assert recovered == [] and result == original


def test_customer_case_footer_does_not_make_another_customer_the_same_company(settings, lead, enquiry):
    from types import SimpleNamespace
    run = SimpleNamespace(input=enquiry, stages=[SimpleNamespace(output={'lead':lead.model_dump()})], sources={})
    body = ('Anglo American operates autonomous drones for mine inspections in Peru. '
            'Related customer stories Mining How SQM achieved inspection gains in Chile.')
    run.sources['S_A'] = Source(source_id='S_A', url='https://flytbase.com/case-studies/anglo-example',
                                title='Anglo American mining', retrieved_at='2026-11-05', access='inspected_page', text=body)
    records = material_proposals(run, ['S_A'])
    assert records.candidates
    dims = {d.dimension:d.matched for d in records.candidates[0].dimensions}
    assert not dims['same_company']


def test_research_pack_yields_news_and_investor_source_leads():
    import pytest
    from flytbase_bdr.research_candidates import PACK_DIR
    if not list(PACK_DIR.glob("*_evidence_pack.json")):
        pytest.skip("Optional private discovery-lead pack is excluded from the public package")
    lead = {'company':'Sociedad Quimica y Minera de Chile (SQM)', 'domain':'sqm.cl'}
    result = candidates_for_lead(lead,'current')
    urls = [row['url'] for row in result]
    assert any('2026earningsrelease' in u for u in urls)
    assert any('case-studies/sqm-' in u for u in urls)
    assert all('url' in item and 'retrieval_query' in item for item in result)
    assert candidates_for_lead({'company':'Unrelated', 'domain':'other.com'}, 'current') == []


def test_small_routing_advisory_has_only_scalar_partner_name():
    from flytbase_bdr.models import RouteAdvice
    from flytbase_bdr.providers.groq import strict_schema
    schema = strict_schema(RouteAdvice)
    properties = schema['properties']
    assert properties['proposed_partner_name']['type'] == 'string'
    assert 'candidates' not in properties
    assert all(key in schema['required'] for key in ('recommended_motion', 'proposed_partner_name', 'next_action', 'gaps'))


def test_automatic_recovery_integrates_with_live_capable_provider(settings, enquiry):
    """A provider declaring the capability generates usable safe drafts after a bad audit."""
    from flytbase_bdr.workflow import Workflow
    from flytbase_bdr.models import Responses
    from conftest import FakeProvider, fake_fetch, claim

    class UnsafeProductionLike(FakeProvider):
        supports_safe_email_recovery = True

        def structured(self, schema, instruction, data, purpose, **kwargs):
            output = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Responses:
                for draft in output.drafts:
                    draft.paragraphs = [claim(text="Your budget of USD 500000 is approved.", sid="", kind="supplied")]
                    draft.paragraphs[0].input_quote = "Internal budget conversation scheduled for Q3"
            return output

    run = Workflow(settings, UnsafeProductionLike, fake_fetch,
                   research_factory=UnsafeProductionLike).execute(enquiry, mode="offline_test")
    response = run.stages[2].output
    assert len(response["drafts"]) == 5
    assert all(d["paragraphs"] for d in response["drafts"])
    assert all(d["review_status"] == "source_limited_fallback" for d in response["drafts"])
    assert all("500000" not in str(d) for d in response["drafts"])
    assert response["withheld_content"]
    assert response["safe_recovery"]["origin"].startswith("deterministic")
    assert run.stages[2].status == "partial"  # no fraudulent promotion of failed AI claims
