from flytbase_bdr.models import Materials, Partner, Routing
from flytbase_bdr.selection import select_materials, decide_routing
from conftest import claim, make_material


def test_case_study_selection_depends_on_inspected_evidence(source):
    materials = Materials(candidates=[make_material()], referral_findings=[], gaps=[])
    data = select_materials(materials, {source.source_id: source}, "", "2026-11-04", [])
    assert data["primary"]["score"] == 55
    source.text = "Different page with no relevant support."
    assert select_materials(materials, {source.source_id: source}, "", "2026-11-04", [])["primary"] is None


def test_case_study_semantic_flag_and_duplicate_dimensions_block_winner(source):
    materials = Materials(candidates=[make_material()], referral_findings=[], gaps=[])
    finding = [{"path": "candidates.0.dimensions.0", "severity": "error", "reason": "Quote does not entail claim."}]
    assert select_materials(materials, {source.source_id: source}, "", "2026-11-04", finding)["primary"] is None
    materials.candidates[0].dimensions.append(materials.candidates[0].dimensions[0])
    assert select_materials(materials, {source.source_id: source}, "", "2026-11-04", [])["primary"] is None


def test_partner_requires_country_capability_and_ecosystem_evidence(source):
    source.text += " Synthetic integrator is a FlytBase integration partner. Synthetic integrator installs industrial drone docks. Synthetic integrator serves Chile."
    partner = Partner(name="Synthetic integrator", partner_type="industrial drone integrator",
                      ecosystem_evidence=claim(text="Synthetic integrator is a FlytBase integration partner.", quote="Synthetic integrator is a FlytBase integration partner."),
                      capabilities=[claim(text="Synthetic integrator installs industrial drone docks.", quote="Synthetic integrator installs industrial drone docks.")], geographic_coverage=claim("Serves Chile", quote="Synthetic integrator serves Chile."),
                      availability="unverified", limitations=["Verify current availability"])
    route = Routing(recommended_motion="partner_led", rationale=[], candidates=[partner], proposed_partner_name=partner.name,
                    required_partner_type=partner.partner_type, commercial_owner="partner", implementation_owner="partner",
                    next_action="Confirm availability", gaps=[])
    kwargs = dict(sources={source.source_id: source}, enquiry="", as_of="2026-11-04", geography="Chile", findings=[])
    assert decide_routing(route, **kwargs)["recommended_motion"] == "partner_led"
    source.text = source.text.replace("Chile", "Latin America")
    partner.geographic_coverage.evidence[0].quote = "Synthetic integrator serves Latin America."
    data = decide_routing(route, **kwargs)
    assert data["recommended_motion"] == "direct_ae"
    assert data["selected_partner_name"] == ""
    assert data["commercial_owner"] == "FlytBase Account Executive"


def test_unverified_operating_context_is_excluded_without_discarding_documented_core_fit(source):
    """One hallucinated 24/7 dimension cannot win points or erase a supported case study."""
    material = make_material()
    operating = next(d for d in material.dimensions if d.dimension == "operating_context")
    operating.matched = True
    operating.rationale.text = "This case proves 24/7 mine operation."
    materials = Materials(candidates=[material], referral_findings=[], gaps=[])
    findings = [{"path": "candidates.0.dimensions.2.rationale", "severity": "error", "reason": "Unsubstantiated continuous operations"}]
    result = select_materials(materials, {source.source_id: source}, "", "2026-11-04", findings)
    assert result["primary"] is not None
    assert result["primary"]["score"] == 55
    assert result["primary"]["candidate"]["dimensions"][2]["matched"] is False
    assert result["primary"]["candidate"]["dimensions"][2]["rationale"]["kind"] == "unknown"
    assert result["candidates"][0]["dimensions"][2]["matched"] is True  # Raw AI proposal retained for audit
    assert result["primary"]["excluded_dimensions"]


def test_case_with_unverified_relevance_is_not_selected(source):
    material = make_material()
    materials = Materials(candidates=[material], referral_findings=[], gaps=[])
    findings = [{"path": "candidates.0.relevance", "severity": "error", "reason": "Guarantee not established"}]
    result = select_materials(materials, {source.source_id: source}, "", "2026-11-04", findings)
    assert result["primary"] is None


def test_country_dimension_cannot_claim_neighboring_country_coverage(source):
    material = make_material()
    item = next(d for d in material.dimensions if d.dimension == "geography")
    item.matched = True
    material.relevance.text = "The test site uses autonomous inspections."
    materials = Materials(candidates=[material], referral_findings=[], gaps=[])
    enquiry = "Company: Sample Mine, Chile\n"
    result = select_materials(materials, {source.source_id: source}, enquiry, "2026-11-04", [])
    assert result["primary"]["breakdown"]["geography"] == 0
