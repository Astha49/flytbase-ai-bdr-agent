"""Final evidence-rich scenarios. All sources/responses below are fictional."""
import pytest
from flytbase_bdr.models import Partner, Routing, Responses
from flytbase_bdr.selection import decide_routing
from flytbase_bdr.workflow import Workflow
from flytbase_bdr.provider import ProviderError
from scripts.simulate_offline import SimulationProvider, ENQUIRY
from conftest import FakeProvider, fake_fetch, claim


@pytest.mark.parametrize("wrong_field", ["capability", "country"])
def test_another_integrators_facts_cannot_qualify_this_candidate(source, wrong_field):
    statements = ["North Integrator is a FlytBase integration partner.",
                  "North Integrator installs industrial drone docks.", "North Integrator serves Chile.",
                  "South Integrator installs drone docks in Chile."]
    source.text = " ".join(statements)
    def fact(text):
        return claim(text=text, quote=text)
    candidate = Partner(name="North Integrator", partner_type="Industrial drone integrator",
                        ecosystem_evidence=fact(statements[0]), capabilities=[fact(statements[1])],
                        geographic_coverage=fact(statements[2]), availability="Unknown", limitations=[])
    if wrong_field == "capability":
        candidate.capabilities = [fact(statements[3])]
    else:
        candidate.geographic_coverage = fact(statements[3])
    proposed = Routing(recommended_motion="partner_led", rationale=[], candidates=[candidate],
                       proposed_partner_name=candidate.name, required_partner_type="Integrator", commercial_owner=candidate.name,
                       implementation_owner=candidate.name, next_action="Assign deployment immediately", gaps=[])
    result = decide_routing(proposed, {source.source_id: source}, "", "2026-11-04", "Chile", [])
    assert result["recommended_motion"] == "direct_ae"
    assert not result["implementation_candidates"] and result["gaps"]
    assert "verify" in result["next_action"] and result["selected_partner_name"] == ""
    assert result["proposed_next_action_unverified"] == "Assign deployment immediately"


def test_evidence_rich_bad_country_is_not_promoted_into_ae_handoff(settings):
    class CrossParty(SimulationProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            value = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Routing:
                sid = self.sid("coverage")
                text = "Other Integrator deploys industrial drones in Chile."
                self.run.sources[sid].text += " " + text
                value.candidates[0].geographic_coverage = claim(text="Andes Field Robotics serves Chile.", sid=sid, quote=text)
                value.recommended_motion = "partner_led"
                value.proposed_partner_name = value.candidates[0].name
                value.next_action = "Assign Andes Field Robotics immediately"
            return value
    run = Workflow(settings, CrossParty, fake_fetch, research_factory=CrossParty).execute(ENQUIRY, mode="offline_test")
    route, handoff = run.stages[4], run.stages[5]
    assert route.status == "partial" and route.technical_status == "succeeded"
    assert route.evidence_status == "partial"
    assert not route.output["implementation_candidates"]
    assert not handoff.output["routing"]["implementation_candidates"]
    assert "verify" in handoff.output["routing"]["next_action"]
    assert handoff.status == "partial" and handoff.output["important_limitations"]


def test_no_research_fallback_is_not_a_technically_successful_assessment(settings, enquiry):
    class NoPartnerSearch(FakeProvider):
        def search(self, queries, purpose, *args, **kwargs):
            if purpose == "search:partners":
                raise ProviderError("Synthetic partner retrieval unavailable")
            return super().search(queries, purpose, *args, **kwargs)
    run = Workflow(settings, NoPartnerSearch, fake_fetch, research_factory=NoPartnerSearch).execute(enquiry, mode="offline_test")
    assert run.stages[4].status == "partial"
    assert run.stages[4].technical_status == "partial"
    assert run.stages[4].evidence_status == "partial"
    assert run.stages[4].output["recommended_motion"] == "direct_ae"


def test_all_five_drafts_reject_fabricated_budget_labelled_as_supplied(settings, enquiry):
    class FalseSupplied(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            value = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Responses:
                for draft in value.drafts:
                    paragraph = claim(text="Your budget of USD 500000 is approved.", sid="", kind="supplied")
                    paragraph.input_quote = "Internal budget conversation scheduled for Q3"
                    draft.paragraphs = [paragraph]
            return value
    run = Workflow(settings, FalseSupplied, fake_fetch, research_factory=FalseSupplied).execute(enquiry, mode="offline_test")
    emails = run.stages[2]
    assert len(emails.output["drafts"]) == 5
    assert all(not draft["paragraphs"] for draft in emails.output["drafts"])
    assert all(draft["review_status"] == "needs_review" for draft in emails.output["drafts"])
    assert emails.status == "partial"
    assert run.stages[0].output["lead"]["budget"]["status"] == "unknown"


def test_explicit_supplied_approval_remains_supported():
    from flytbase_bdr.grounding import check_claim
    text = "Budget of USD 500000 is approved."
    value = claim(text=text, sid="", kind="supplied")
    value.input_quote = text
    assert check_claim(value, {}, text, "2026-11-04") == []
