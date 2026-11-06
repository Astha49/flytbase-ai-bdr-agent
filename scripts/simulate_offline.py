"""Exercise the existing six-stage engine with fictional, realistic evidence.

Run from the project root: python -m scripts.simulate_offline
No credentials are read, no provider balance is consulted and all sockets are
blocked. This is deliberately separate from the live application's providers.
"""
import argparse
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

from flytbase_bdr.config import ROOT, Settings
from flytbase_bdr.models import (
    Lead, Dimension, Signal, Claim, EvidenceRef, FinancialContext, Research, Topic,
    Materials, Material, MatchDimension, MaterialChoice, Routing, Partner, Responses, EmailDraft, Audit,
)
from flytbase_bdr.workflow import Workflow
from flytbase_bdr.grounding import audit_mechanical
from flytbase_bdr.diagnostics import assess_run
from flytbase_bdr.reporting import save_run, load_run, markdown_export


DISCLAIMER = "SYNTHETIC OFFLINE SIMULATION: fictional companies, people, evidence and audit responses; not live research or acceptance evidence."
ENQUIRY = """From: Elena Morales (elena@amx.example)
Title: Head of Northern Operations
Company: Altiplano Minerals (AMX), Chile
Subject: Autonomous inspection for three lithium sites
Context: Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites. Contracted crews are expensive and hazardous. Referred by Cordillera Copper. Internal budget conversation scheduled for Q3.
"""

# URL keys on the FlytBase host exercise the existing official-domain gate.
# They are intentionally NONEXISTENT fixture paths, not discovered publications.
DOCUMENTS = {
    "organisation": ("https://amx.example/governance", "Fictional AMX governance", "2026-02-18",
        "AMX has separate Northern Operations and Industrial Products divisions. The operations steering committee oversees site reliability. No individual buyer reporting line is published."),
    "finance": ("https://amx.example/investors/fy2025", "Fictional AMX FY2025 report", "2026-02-18",
        "AMX FY2025 group capital expenditure was USD 420 million and operating expenses were USD 910 million. The FY2025 technology programme invested USD 12 million in remote condition monitoring. Investor priorities are safer operations and disciplined expansion. No drone project allocation is disclosed."),
    "current": ("https://amx.example/news/remote-monitoring", "Fictional AMX strategic update", "2026-06-10",
        "AMX announced a remote condition-monitoring programme on 10 June 2026. Northern Operations remains a separate division; no merger or ownership change is described in this update."),
    "own_case": ("https://www.flytbase.com/case-studies/__offline_fixture__/amx-iodine", "SYNTHETIC: AMX iodine inspection", "2026-01-15",
        "AMX uses FlytBase thermal inspection at its iodine operations in Chile. The deployment concerns the Industrial Products division. Lithium sites are not covered by this example."),
    "referral_case": ("https://www.flytbase.com/case-studies/__offline_fixture__/cordillera-copper", "SYNTHETIC: Cordillera Copper inspection", "2026-03-12",
        "Cordillera Copper uses FlytBase for drone inspection at a remote copper mine in Chile. The mine operates 24/7 in dusty desert conditions. Its example does not establish lithium-site feasibility or guaranteed savings."),
    "ecosystem": ("https://www.flytbase.com/__offline_fixture__/andes-integrator", "SYNTHETIC: ecosystem listing", "2026-04-02",
        "Andes Field Robotics is a FlytBase integration partner. It installs industrial drone docks and integrates inspection workflows."),
    "coverage": ("https://andes-field.example/services", "Fictional integrator services", "2026-04-02",
        "Andes Field Robotics provides industrial drone installation and maintenance services in Chile. Current project capacity and availability are not published."),
}


def statement(text, sid="", quote="", kind="public", financial=None):
    return Claim(text=text, kind=kind, evidence=[EvidenceRef(source_id=sid, quote=quote)] if sid else [],
                 input_quote="", uncertainty="Recommendation/hypothesis; confirm through discovery." if kind == "inference" else "",
                 financial_context=financial, event_date="")


def missing(question):
    return Dimension(status="unknown", evidence=[], uncertainty="Not established by the enquiry.", questions=[question])


class SimulationProvider:
    """Deterministic fixtures, not an AI provider and never a live fallback."""
    supports_compact_material_comparison = True
    def __init__(self, settings, run):
        self.run = run

    def search(self, queries, purpose, as_of_date, domains=None):
        group = purpose.split(":")[-1]
        keys = {"organisation": ["organisation"], "finance": ["finance"], "current": ["current", "own_case"],
                "materials": ["own_case", "referral_case"], "partners": ["ecosystem", "coverage"]}[group]
        return {"results": [{"url": DOCUMENTS[k][0], "title": DOCUMENTS[k][1],
                             "published_date": DOCUMENTS[k][2],
                             "content": "Synthetic search fixture, never retrieved from the web.",
                             "retrieval_query": queries[0]} for k in keys]}

    def extract(self, urls, purpose):
        return {"results": [{"url": url, "raw_content": next(doc[3] for doc in DOCUMENTS.values() if doc[0] == url)} for url in urls]}

    def sid(self, key):
        return next(sid for sid, source in self.run.sources.items() if source.url == DOCUMENTS[key][0])

    def fact(self, key, quote, text=None, **kwargs):
        return statement(text or quote, self.sid(key), quote, **kwargs)

    def structured(self, schema, instruction, data, purpose, **kwargs):
        if schema is Lead:
            need = "Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites"
            return Lead(name="Elena Morales", email="elena@amx.example", title="Head of Northern Operations",
                        company="Altiplano Minerals (AMX)", domain="amx.example", geography="Chile", industry="mining",
                        need=need, referral="Cordillera Copper", knowns=[need],
                        budget=missing("Is there approved project funding or only a budget discussion?"),
                        authority=missing("Who owns the business case and final purchasing approval?"),
                        need_dimension=Dimension(status="confirmed", evidence=[need], uncertainty="Technical feasibility remains unverified.", questions=["Which inspections and acceptance criteria matter most?"]),
                        timeline=missing("Which year is Q3, and when would a pilot decision be made?"),
                        signals=[Signal(code=code, quote=quote) for code, quote in [
                            ("need_fit", need), ("operational_pain", "Contracted crews are expensive and hazardous"),
                            ("multiple_sites", "3 large-scale"), ("continuous_operations", "24/7"),
                            ("senior_role", "Head of Northern Operations"), ("referral", "Referred by Cordillera Copper")]],
                        fit="promising", fit_reason="Explicit operational pain and multi-site inspection need; discovery still required.")
        if schema is Audit:
            # This merely simulates a successful semantic-review response. Real
            # mechanical quote/financial/domain checks still execute in Workflow.
            return Audit(findings=[])
        if schema is Research:
            money = self.fact("finance", "AMX FY2025 group capital expenditure was USD 420 million and operating expenses were USD 910 million.",
                              financial=FinancialContext(currency="USD", units="million", reporting_period="FY2025", publication_date="2026-02-18", scope="group-wide spending, no drone project budget"))
            technology = self.fact("finance", "The FY2025 technology programme invested USD 12 million in remote condition monitoring.",
                                   financial=FinancialContext(currency="USD", units="million", reporting_period="FY2025", publication_date="2026-02-18", scope="group technology programme, no drone project allocation"))
            topics = [
                ("Organisation and reporting lines", [self.fact("organisation", "AMX has separate Northern Operations and Industrial Products divisions.")]),
                ("Budget and investment signals", [money, technology]),
                ("News and strategic announcements", [self.fact("current", "AMX announced a remote condition-monitoring programme on 10 June 2026.")]),
                ("Investor priorities", [self.fact("finance", "Investor priorities are safer operations and disciplined expansion.")]),
                ("Corporate changes and customer relationships", [self.fact("current", "Northern Operations remains a separate division; no merger or ownership change is described in this update."),
                    self.fact("own_case", "AMX uses FlytBase thermal inspection at its iodine operations in Chile.")]),
            ]
            return Research(topics=[Topic(name=name, claims=claims, gaps=[]) for name, claims in topics],
                            positioning=[statement("Position a discovery-led reliability pilot with explicit site acceptance criteria; company spending is only a signal.", kind="inference")],
                            stakeholder_hypothesis=[statement("Operations may sponsor the business case alongside reliability, IT and procurement; Elena's manager and approval authority remain unknown.", kind="inference")], conflicts=[])
        if schema is MaterialChoice:
            from flytbase_bdr.selection import MATCH_WEIGHTS
            ordered = sorted(data["cases"], key=lambda row: sum(MATCH_WEIGHTS[d["name"]] for d in row["dimensions"] if d["matched"]), reverse=True)
            return MaterialChoice(preferred_source_id=ordered[0]["source_id"] if ordered else "",
                                  ranked_source_ids=[row["source_id"] for row in ordered],
                                  rationale="Industrial inspection similarity; proposed-site feasibility still needs discovery.", gaps=[])
        if schema is Materials:
            candidates = []
            for key, matched in [("own_case", {"industry", "use_case", "geography", "same_company"}),
                                 ("referral_case", {"industry", "use_case", "operating_context", "geography", "referral"})]:
                quote = DOCUMENTS[key][3].split(". ")[0] + "."
                if key == "referral_case":
                    quote += " The mine operates in dusty desert conditions."
                candidates.append(Material(title=DOCUMENTS[key][1], source_id=self.sid(key),
                    dimensions=[MatchDimension(dimension=d, matched=d in matched,
                                rationale=self.fact(key, quote, text="Potential similarity on " + d.replace("_", " ") + ".", kind="inference"))
                                for d in ["industry", "use_case", "operating_context", "geography", "referral", "same_company"]],
                    relevance=self.fact(key, quote, text="A relevant industrial inspection comparison; transfer requires technical discovery.", kind="inference"),
                    limitations=["Fictional evidence only; a different mineral, site or outcome does not establish lithium feasibility."],
                    own_company_expansion_assessment="AMX iodine deployment does not establish lithium-site coverage; confirm whether this is an expansion."))
            return Materials(candidates=candidates, referral_findings=[self.fact("referral_case", "Cordillera Copper uses FlytBase for drone inspection at a remote copper mine in Chile.")], gaps=[])
        if schema is Routing:
            partner = Partner(name="Andes Field Robotics", partner_type="Industrial drone systems integrator",
                ecosystem_evidence=self.fact("ecosystem", "Andes Field Robotics is a FlytBase integration partner."),
                capabilities=[self.fact("ecosystem", "Andes Field Robotics is a FlytBase integration partner. It installs industrial drone docks and integrates inspection workflows.")],
                geographic_coverage=self.fact("coverage", "Andes Field Robotics provides industrial drone installation and maintenance services in Chile."),
                availability="Not verified; confirm capacity and site access before assigning work.", limitations=["Coverage does not prove present availability or site-specific capability."])
            return Routing(recommended_motion="direct_ae", rationale=[statement("Retain AE ownership for multi-site enterprise discovery; use evidenced local implementation support after capacity checks.", kind="inference")],
                candidates=[partner], proposed_partner_name="", required_partner_type="Industrial drone systems integrator",
                commercial_owner="FlytBase Account Executive", implementation_owner="Local support after validation",
                next_action="AE schedules discovery and separately verifies integrator capacity, site conditions and implementation scope.", gaps=[])
        if schema is Responses:
            # Every response after the initial draft is explicitly hypothetical.
            contexts = {
                "initial": ("Your three-site inspection enquiry", "New inbound enquiry", "Open with operational priorities and two buying-process unknowns.",
                    "Thank you, Elena. Reducing hazardous inspection work across three continuously operating sites is a useful discovery starting point.",
                    "Could we schedule 20 minutes to identify the pilot owner and clarify which year Q3 refers to?"),
                "no_reply": ("A focused inspection discovery call", "Hypothetical: five business days without a reply", "Offer a smaller next step without claiming a response.",
                    "Following up on your inspection enquiry: which recurring inspection would be most useful to review first?",
                    "If helpful, I can send a short discovery agenda before we choose a time."),
                "interested": ("Agenda for an inspection discussion", "Hypothetical: buyer expresses interest in a discussion", "Turn interest into a concrete discovery meeting.",
                    "For a discussion, I suggest reviewing inspection tasks, connectivity, safety constraints and pilot acceptance criteria.",
                    "Who from reliability and IT should join, and which time suits you?"),
                "budget_clarification": ("Aligning discovery with your budget process", "Hypothetical: buyer clarifies budget timing but funding is unapproved", "Respect the buying process without treating a meeting as funding.",
                    "We can align technical discovery with your budget discussion without assuming project approval.",
                    "Which year and approval milestone should we work toward, and who owns the business case?"),
                "stakeholder_referral": ("Connecting with the inspection project owner", "Hypothetical: buyer refers us to another stakeholder", "Establish ownership without inventing the referred person's identity.",
                    "If another colleague owns inspection transformation, I can share a short summary of the three-site need for an introduction.",
                    "Would you introduce the project owner so we can confirm pilot scope and the decision process?"),
            }
            drafts = []
            for branch, (subject, trigger, why, opening, next_step) in contexts.items():
                research = self.fact("finance", "Investor priorities are safer operations and disciplined expansion.")
                recap = statement(opening, kind="inference")
                if branch == "initial":
                    # A separate enquiry-backed paragraph exercises the same
                    # provenance split required of real generated emails.
                    recap = statement(
                        "Thank you, Elena. Your enquiry describes 3 large-scale, 24/7 lithium extraction sites.",
                        kind="supplied")
                    recap.input_quote = "Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites"
                drafts.append(EmailDraft(branch=branch, subject=subject,
                    paragraphs=[recap, research, statement(next_step, kind="inference")],
                    trigger=trigger, why_this_message=why,
                    if_buyer_responds="Replace the hypothetical branch with their actual information; update discovery questions and schedule the agreed next step.",
                    hypothetical=branch != "initial"))
            return Responses(drafts=drafts, limitations=[])
        raise AssertionError(f"Unexpected simulation schema: {schema.__name__}")


def check_simulation(run):
    """Assert consequential outputs instead of simply checking for exceptions."""
    q, research, emails, cases, route, handoff = [stage.output for stage in run.stages]
    checks = {
        "six_stages_completed_in_simulation": len(run.stages) == 6 and all(
            s.status == "complete" and s.technical_status == "succeeded" and s.evidence_status == "supported" for s in run.stages),
        "unknown_budget_and_authority": q["lead"]["budget"]["status"] == q["lead"]["authority"]["status"] == "unknown",
        "ambiguous_quarter_preserved": q["lead"]["timeline"]["status"] == "ambiguous",
        "priority_separate_from_completeness": q["priority_score"] == 80 and q["qualification_completeness_percent"] == 25,
        "all_research_areas": len(research["topics"]) == 5 and all(t["claims"] for t in research["topics"]),
        "financial_scope_and_period": research["topics"][1]["claims"][0]["financial_context"]["reporting_period"] == "FY2025",
        "evidence_checks_clear": not any(audit_mechanical(s.output, run.sources, run.input, run.as_of_date) for s in run.stages),
        "two_cases_compared": len(cases["comparison"]) == 2,
        "highest_supported_case_selected": bool(cases["primary"]) and cases["primary"]["score"] == 90,
        "own_iodine_scope_preserved": any("iodine operations" in item.get("deployment_scope_evidence", "") for item in cases["possible_existing_company_relationship"]),
        "direct_ae_and_local_support": route["commercial_owner"] == "FlytBase Account Executive" and len(route["implementation_candidates"]) == 1,
        "partner_capacity_not_assumed": all(c["availability"].startswith("Not verified") for c in route["implementation_candidates"]),
        "five_distinct_email_branches": len(emails["drafts"]) == len({d["branch"] for d in emails["drafts"]}) == 5 and all(
            d["paragraphs"] and d["review_status"] == "checked" and d["trigger"] and d["if_buyer_responds"] for d in emails["drafts"]),
        "hypothetical_replies_not_fabricated": all(d["hypothetical"] for d in emails["drafts"] if d["branch"] != "initial"),
        "three_distinct_handoff_findings": len({c["text"] for c in handoff["top_three_research_findings"]}) == 3,
        "handoff_matches_upstream": handoff["qualification"] == q and handoff["recommended_case_study"] == cases["primary"] and
            handoff["routing"]["implementation_candidates"] == route["implementation_candidates"] and
            handoff["routing"]["next_action"] == route["next_action"],
        "not_live_acceptance": not assess_run(run)["safe_to_claim_full_acceptance"],
        "no_provider_usage": not run.usage,
    }
    return checks


def simulate(output: Path):
    output = output.resolve()
    if output == ROOT / "runs" or (ROOT / "runs") in output.parents:
        raise ValueError("Use a separate synthetic-demo folder, never the private runs directory.")
    def no_network(*args, **kwargs):
        raise AssertionError("This simulation forbids all network requests.")
    with TemporaryDirectory(prefix="flytbase-offline-") as temporary, ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.getaddrinfo", "socket.create_connection"):
            stack.enter_context(patch(target, side_effect=no_network))
        settings = Settings(runs_dir=str(Path(temporary) / "checkpoints"))
        run = Workflow(settings, SimulationProvider, no_network, research_factory=SimulationProvider).execute(ENQUIRY, mode="offline_test")
        # Describe extraction honestly; the live engine's access enum represents
        # what an inspected document would look like, not an actual web fetch.
        for source in run.sources.values():
            key = next(k for k, value in DOCUMENTS.items() if value[0] == source.url)
            source.inspection_method = "OFFLINE: supplied fixture text; no page/PDF or search service was accessed."
            source.publication_date = DOCUMENTS[key][2]
            source.publication_date_basis = "fictional date supplied by offline fixture"
        checks = check_simulation(run)
        if not all(checks.values()):
            details = "; ".join(f"{s.name}={s.status}: {s.warnings}" for s in run.stages if s.status != "complete")
            raise AssertionError("Simulation checks failed: " + ", ".join(k for k, v in checks.items() if not v) + ". " + details)
        run.run_id = "offline_simulation"
        run.config["runs_dir"] = "examples/recruiter_demo"
        run.warnings.insert(0, DISCLAIMER)
        run.logs.append({"event": "synthetic_submission_simulation", "description": DISCLAIMER, "network_requests": 0})
        folder = save_run(run, output)
        saved = load_run(folder / "run.json")
        checks["export_matches_saved_run"] = saved.model_dump() == run.model_dump() and (folder / "report.md").read_text(encoding="utf-8") == markdown_export(run)
        if not checks["export_matches_saved_run"]:
            raise AssertionError("Saved exports differ from simulated results")
        result = {"description": DISCLAIMER, "live_acceptance": False, "network_requests": 0,
                  "checks": checks, "stages": [{"name": s.name, "status": s.status} for s in run.stages]}
        (folder / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return folder, result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / "recruiter_demo")
    args = parser.parse_args()
    folder, result = simulate(args.output)
    print(DISCLAIMER)
    print(f"{sum(result['checks'].values())}/{len(result['checks'])} checks passed; zero network requests.")
    print("Saved synthetic demo:", folder)
