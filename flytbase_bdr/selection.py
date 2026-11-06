"""Evidence-gated decisions. Models propose; ordinary Python verifies and scores."""
from copy import deepcopy
import re
from .evidence import is_flytbase, source_family_key
from .grounding import supported, unresolved_paths, path_affects_claim
from .models import Materials, Routing, Source
from .qualification import normalise
from .review import backed_interpretation

MATCH_WEIGHTS = {"industry": 25, "use_case": 30, "operating_context": 15,
                 "geography": 10, "referral": 10, "same_company": 10}


def path_has_error(findings, prefix):
    return any(path_affects_claim(path, prefix) for path in unresolved_paths(findings))


def _global_candidate_error(findings, prefix):
    """A bad non-core dimension may be excluded without invalidating the whole article."""
    return any(
        f.get("path", "") in unresolved_paths([f]) and (
            not f.get("path") or f["path"] == prefix
            or prefix.startswith(f["path"] + ".")
            or (f["path"].startswith(prefix + ".") and not f["path"].startswith(prefix + ".dimensions."))
        )
        for f in findings
    )


def _unverified_dimension(dimension: dict) -> dict:
    """Remove an unsupported match from buyer-facing recommendations; keep raw proposal separately."""
    revised = deepcopy(dimension)
    revised["matched"] = False
    revised["rationale"] = {"text": "Match withheld: inspected evidence did not substantiate this dimension.",
                             "kind": "unknown", "evidence": [], "input_quote": "",
                             "uncertainty": "Not scored; review the original candidate and audit findings.",
                             "financial_context": None, "event_date": ""}
    return revised


def select_materials(materials: Materials, sources: dict[str, Source], enquiry: str, as_of: str, findings: list[dict], *, lead: dict | None = None) -> dict:
    cards = []
    for i, candidate in enumerate(materials.candidates):
        source = sources.get(candidate.source_id)
        reasons, excluded, points = [], [], {}
        valid_source = bool(source and is_flytbase(source.url) and source.access in {"inspected_page", "inspected_pdf"})
        if not valid_source:
            reasons.append("Candidate must come from an inspected FlytBase page/document.")
        if len(candidate.dimensions) != 6 or {x.dimension for x in candidate.dimensions} != set(MATCH_WEIGHTS):
            reasons.append("Exactly six unique match dimensions are required.")
        revised = candidate.model_dump()
        for j, dimension in enumerate(candidate.dimensions):
            key = dimension.dimension
            valid = backed_interpretation(dimension.rationale, sources, enquiry, as_of)
            tied = any(r.source_id == candidate.source_id for r in dimension.rationale.evidence)
            audit_clean = not path_has_error(findings, f"candidates.{i}.dimensions.{j}")
            # A country match must be demonstrated by the actual country in the passage.
            # Neighbouring countries or broad LATAM mentions do not establish coverage.
            country = (lead or {}).get("geography") or (enquiry.rsplit("Company:", 1)[-1].splitlines()[0].rsplit(",", 1)[-1].strip() if "Company:" in enquiry else "")
            geography_ok = key != "geography" or (bool(country) and any(
                re.search(r"(?<!\w)" + re.escape(normalise(country)) + r"(?!\w)", normalise(r.quote)) for r in dimension.rationale.evidence))
            quote_text = " ".join(r.quote for r in dimension.rationale.evidence).casefold()
            requested_need = (lead or {}).get("need") or enquiry
            inspection_requested = "inspect" in requested_need.casefold()
            security_requested = any(word in requested_need.casefold() for word in ("security", "surveillance", "perimeter"))
            use_case_ok = True
            if key == "use_case" and inspection_requested:
                use_case_ok = any(word in quote_text for word in ("inspect", "inspecci", "thermal", "thermograph"))
            elif key == "use_case" and security_requested:
                use_case_ok = any(word in quote_text for word in ("secur", "surveill", "perimeter", "guard"))
            context_ok = True
            if key == "operating_context":
                from .evidence_decisions import operating_context_quote
                context_ok = bool(re.search(r"24/7|round.the.clock|continuous", requested_need, re.I)) and bool(operating_context_quote(quote_text))
            keep = dimension.matched and valid and tied and audit_clean and geography_ok and use_case_ok and context_ok
            if key in {"same_company", "referral"} and keep:
                from .diagnostics import _brand
                supplied_company = (lead or {}).get("company", "")
                if not supplied_company and "Company:" in enquiry:
                    supplied_company = enquiry.rsplit("Company:", 1)[-1].splitlines()[0].rsplit(",", 1)[0].strip()
                referral = (lead or {}).get("referral", "")
                if not referral:
                    match = re.search(r"Referred by ([^.\n]+)", enquiry, re.I)
                    referral = match.group(1).strip() if match else ""
                identity = _brand(supplied_company) if key == "same_company" else referral
                keep = bool(identity) and bool(re.search(r"(?<!\w)" + re.escape(identity.casefold()) + r"(?!\w)", quote_text))
            points[key] = MATCH_WEIGHTS[key] if keep else 0
            if dimension.matched and not keep:
                excluded.append(f"{key}: proposed match excluded (source, country, or audit evidence insufficient).")
                revised["dimensions"][j] = _unverified_dimension(revised["dimensions"][j])
        if not valid_source or _global_candidate_error(findings, f"candidates.{i}"):
            reasons.append("Material-level groundedness audit failed; review required.")
        if not backed_interpretation(candidate.relevance, sources, enquiry, as_of) or not any(
            r.source_id == candidate.source_id for r in candidate.relevance.evidence):
            reasons.append("Candidate relevance lacks inspected evidence tied to this specific article.")
        if not points.get("industry") or not points.get("use_case"):
            reasons.append("Core industry and inspection-use-case matches both require clear inspected evidence.")
        if not candidate.limitations:
            reasons.append("Transfer limitations are missing.")
        cards.append({"candidate": revised, "score": sum(points.values()), "breakdown": points,
                      "eligible": not reasons, "rejection_reasons": list(dict.fromkeys(reasons)),
                      "excluded_dimensions": excluded,
                      "selection_note": "An excluded dimension contributes zero and its unverified rationale is withheld; consult raw proposals/audit before sharing."})
    eligible = sorted((c for c in cards if c["eligible"]), key=lambda c: c["score"], reverse=True)
    independent, families = [], set()
    for card in eligible:
        family = source_family_key(sources[card["candidate"]["source_id"]].url)
        if family not in families:
            independent.append(card)
            families.add(family)
    eligible = independent
    return {**materials.model_dump(), "rubric": MATCH_WEIGHTS, "comparison": cards,
            "primary": eligible[0] if eligible else None, "supporting": eligible[1:2],
            "selection_rule": "Highest eligible inspected FlytBase material after evidence-gated dimension scoring; unsupported matches score zero. Winner and score are not outcome guarantees."}


def decide_routing(routing: Routing, sources: dict[str, Source], enquiry: str, as_of: str,
                   geography: str, findings: list[dict]) -> dict:
    data = routing.model_dump()
    eligible = []
    checks = []
    for i, candidate in enumerate(routing.candidates):
        name_pattern = r"(?<!\w)" + re.escape(normalise(candidate.name)) + r"(?!\w)"
        def names_candidate(reference):
            return bool(candidate.name.strip() and re.search(name_pattern, normalise(reference.quote)))
        ecosystem_ok = supported(candidate.ecosystem_evidence, sources, enquiry, as_of) and any(
            is_flytbase(sources[r.source_id].url)
            and names_candidate(r)
            and re.search(r"partner|integrat|implement|collaborat|deploy", r.quote, re.I)
            for r in candidate.ecosystem_evidence.evidence if r.source_id in sources)
        capability_ok = any(supported(c, sources, enquiry, as_of) and any(names_candidate(r) for r in c.evidence)
                            for c in candidate.capabilities)
        # Conservative gate: the actual country must occur in the coverage passage, not just model text.
        country_presence = bool(geography.strip()) and supported(candidate.geographic_coverage, sources, enquiry, as_of) and any(
            names_candidate(r) and re.search(r"(?<!\w)" + re.escape(normalise(geography)) + r"(?!\w)", normalise(r.quote))
            for r in candidate.geographic_coverage.evidence)
        country_ok = country_presence and any(
            names_candidate(r) and re.search(r"(?<!\w)" + re.escape(normalise(geography)) + r"(?!\w)", normalise(r.quote))
            and re.search(r"\b(?:serv(?:e|es|ice|ices)|operat\w*|deploy\w*|implement\w*|cover\w*|support\w*|install\w*)\b", r.quote, re.I)
            for r in candidate.geographic_coverage.evidence)
        audit_ok = not path_has_error(findings, f"candidates.{i}")
        valid = ecosystem_ok and capability_ok and country_ok and audit_ok
        checks.append({"name": candidate.name, "ecosystem_verified": ecosystem_ok, "capability_verified": capability_ok,
                       "country_presence_verified": country_presence,
                       "country_coverage_verified": country_ok, "audit_clear": audit_ok,
                       "country_evidence_scope": "Documented country activity only; territory, requested sites and current capacity still need verification." if country_ok else "No sufficient country-activity passage tied to this candidate.",
                       "eligible_for_partner_led": valid, "availability": "Not verified; confirm current capacity before assignment."})
        if valid:
            eligible.append(candidate.name)
        else:
            data["gaps"].append(f"{candidate.name}: candidate-specific ecosystem, capability or country evidence is insufficient or flagged; no implementation assignment.")
    data["candidate_checks"] = checks
    data["proposed_availability_unverified"] = {c.name: c.availability for c in routing.candidates}
    for candidate in data["candidates"]:
        candidate["availability"] = "Not verified; confirm current capacity before assignment."
    data["implementation_candidates"] = [c for c in data["candidates"] if c["name"] in eligible]
    if routing.recommended_motion == "partner_led" and routing.proposed_partner_name not in eligible:
        data["recommended_motion"] = "direct_ae"
        data["gaps"].append("Partner-led proposal rejected: inspected ecosystem, capability and exact-country coverage evidence are all required.")
    if any(not check["eligible_for_partner_led"] for check in checks) or data["recommended_motion"] != routing.recommended_motion:
        data["proposed_next_action_unverified"] = data["next_action"]
        data["next_action"] = "AE-led discovery; verify candidate-specific capability, country activity and current capacity before implementation assignment."
    if data["recommended_motion"] == "direct_ae":
        data["selected_partner_name"] = ""
        data["commercial_owner"] = "FlytBase Account Executive"
        data["implementation_owner"] = "Local implementation support to be verified during discovery; no partner assigned."
    else:
        data["selected_partner_name"] = routing.proposed_partner_name
    data["guardrail"] = "Capability and public coverage do not establish current partner availability; confirm before assignment."
    data["motion_comparison"] = {
        "direct_ae": "FlytBase AE owns commercial discovery and the enterprise buying process.",
        "partner_assisted": "An evidence-qualified local integrator may support implementation; capacity and assignment require confirmation.",
        "partner_led": "Propose only when ecosystem membership, capability and the actual country are substantiated."}
    return data
