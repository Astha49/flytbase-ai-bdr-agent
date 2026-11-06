"""Offline regressions for the November saved-run failures and evidence leaks."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from flytbase_bdr import prompts
from flytbase_bdr.config import ROOT
from flytbase_bdr.compact import audit_payload
from flytbase_bdr.diagnostics import own_company_mentions
from flytbase_bdr.evidence import fetch_source, now
from flytbase_bdr.evidence_decisions import route_proposal
from flytbase_bdr.grounding import check_claim
from flytbase_bdr.models import Audit, AuditFinding, Claim, Materials, Research, Routing, Source, Responses
from flytbase_bdr.provider import ProviderError, RequestTooLarge, estimate_tokens
from flytbase_bdr.providers.groq import GroqProvider, strict_schema, structured_payload
from flytbase_bdr.reporting import load_run, json_export
from flytbase_bdr.selection import decide_routing
from flytbase_bdr.workflow import Workflow, new_run
from conftest import FakeProvider, fake_fetch, claim


def test_400_diagnostics_preserve_cause_without_retry_or_secret(settings, enquiry, monkeypatch):
    secret = "gsk_synthetic_private_key_400_regression"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, headers={"x-request-id": "offline-request"}, json={"error": {
            "type": "invalid_request_error", "code": "json_validate_failed", "param": "response_format",
            "message": "Schema validation failed. " + secret,
            "failed_generation": "THIS SERVER FIELD MUST NOT BE LOGGED"}})
    run = new_run(enquiry, settings, "offline_test")
    provider = GroqProvider(settings, run, httpx.Client(transport=httpx.MockTransport(handler)))
    provider.pacer = type("NoWait", (), {"reserve": lambda *a: [], "settle": lambda *a: None})()
    try:
        with pytest.raises(ProviderError, match="json_validate_failed"):
            provider.structured(Routing, prompts.ROUTING, {"sources": {}}, "partner routing", max_tokens=2300)
    finally:
        provider.close()
    assert len(calls) == 1 and calls[0]["response_format"]["json_schema"]["strict"] is True
    assert calls[0]["model"] == "openai/gpt-oss-120b" and calls[0]["reasoning_effort"] == "low"
    assert not {"tools", "temperature", "max_tokens", "reasoning_format"} & calls[0].keys()
    error = next(row for row in run.logs if row["event"] == "api_error")
    assert error["error_details"]["param"] == "response_format"
    assert secret not in json_export(run) and "THIS SERVER FIELD" not in json_export(run)
    assert error["request_id"] == "offline-request"
    assert next(row for row in run.logs if row["event"] == "structured_request_preflight")["minimum_completion_tokens"] == 1600


def test_complex_schema_cannot_request_a_tiny_completion(settings, enquiry, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_offline_minimum_fixture_123456")
    def forbidden(request):
        raise AssertionError("No unusably small completion should be dispatched")
    provider = GroqProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(forbidden)))
    try:
        with pytest.raises(RequestTooLarge, match="minimum"):
            provider.structured(Routing, prompts.ROUTING, {}, "partner routing", max_tokens=900)
    finally:
        provider.close()
    assert not (settings.run_path() / "project_budget.json").exists()


def test_every_nested_routing_object_has_strict_required_fields():
    schema = strict_schema(Routing)
    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)
    inspect(schema)


def test_actual_saved_case_and_partner_requests_fit_offline(settings):
    path = ROOT / "runs" / "20261104T182119_520bf7ec5e" / "run.json"
    if not path.exists():
        pytest.skip("Private historical evidence not included in the source package")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    saved = load_run(path)
    saved.mode = "offline_test"
    captured = {}
    class Capture(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema in {Routing, Materials}:
                payload, limit = structured_payload(schema, instruction, data, settings, purpose, kwargs.get("max_tokens"))
                size = estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                captured[schema.__name__] = size + limit
                assert size + limit <= settings.max_request_tokens, (schema.__name__, size, limit)
            return super().structured(schema, instruction, data, purpose, **kwargs)
        def search(self, *args, **kwargs):
            raise AssertionError("Historical case/partner caches must be reused")
    Workflow(settings, Capture, fake_fetch, research_factory=Capture).execute(
        saved.input, mode="offline_test", resume=saved, rerun_stages={3, 4})
    assert set(captured) == {"Routing", "Materials"}
    assert all(size <= settings.max_request_tokens for size in captured.values()), captured
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_repeated_quotes_deduplicate_and_free_fields_are_audited(source):
    c = claim().model_dump()
    data = {"drafts": [{"subject": "Unverified promised outcome", "trigger": "Hypothetical interest", "paragraphs": [c, c, c]}]}
    compact = audit_payload(data, {source.source_id: source})
    assert len(compact["quotes"]) == 1
    assert len(compact["claims_with_paths"]) == 3
    assert any(row["path"] == "drafts.0.subject" for row in compact["review_fields"])
    assert compact["claims_with_paths"][2]["claim"]["evidence"][0]["quote_ref"] == "Q1"


def test_cached_wrong_issuer_is_not_sent_to_research(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    wrong = Source(source_id="S_unrelated", url="https://www.sec.gov/Archives/another-issuer.htm", title="20-F",
                   retrieved_at=now(), access="inspected_page", text="An unrelated publishing company annual report.")
    run.sources[wrong.source_id] = wrong
    run.retrieval_cache["finance"]["source_ids"].insert(0, wrong.source_id)
    class Check(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is Research:
                assert "S_unrelated" not in data["sources"]
            return super().structured(schema, instruction, data, purpose, **kwargs)
        def search(self, *args, **kwargs):
            raise AssertionError("Cache validation should not call search")
    result = Workflow(settings, Check, fake_fetch, research_factory=Check).execute(enquiry, mode="offline_test", resume=run, rerun_stages={1})
    assert result.stages[1].technical_status == "succeeded"


def test_extract_mirrors_partial_failures_and_short_text_use_safe_reader(settings, enquiry):
    fetched = []
    class Partial(FakeProvider):
        def search(self, queries, purpose, as_of_date, domains=None):
            if purpose == "search:finance":
                return {"results": [{"url": f"https://company.example/finance-{suffix}", "title": "Synthetic issuer report",
                                     "content": "Synthetic search excerpt", "retrieval_query": queries[0]} for suffix in ("a", "b", "c")]}
            return super().search(queries, purpose, as_of_date, domains)
        def extract(self, urls, purpose):
            if purpose == "extract:finance":
                return {"results": [{"url": "https://www.company.example/finance-a", "raw_content": "The test site uses autonomous inspections. " * 8},
                                    {"url": "https://company.example/finance-c", "raw_content": "Access denied"}],
                        "failed_results": [{"url": "https://company.example/finance-b", "error": "server error fixture"}]}
            return super().extract(urls, purpose)
    def reader(source, max_chars):
        fetched.append(source.url)
        fake_fetch(source, max_chars)
    run = Workflow(settings, Partial, reader, research_factory=Partial).execute(enquiry, mode="offline_test")
    first = next(source for source in run.sources.values() if source.url.endswith("finance-a"))
    assert "Tavily" in first.inspection_method
    assert "https://company.example/finance-a" not in fetched
    assert "https://company.example/finance-b" in fetched and "https://company.example/finance-c" in fetched
    assert any(log["event"] == "extract_url_failed" for log in run.logs)
    assert first.error == ""


def test_changed_industry_changes_retrieved_cases_and_recommendations(settings, enquiry):
    from conftest import make_lead, make_material
    class Industry(FakeProvider):
        seen = []
        def search(self, queries, purpose, as_of_date, domains=None):
            self.seen.append((purpose, queries))
            if purpose == "search:materials":
                story = "port" if "shipping" in " ".join(queries) else "mine"
                return {"results": [{"url": "https://flytbase.com/case-studies/fictional-" + story,
                                     "title": "Synthetic " + story + " customer story", "content": "Fictional fixture", "retrieval_query": queries[0]}]}
            return super().search(queries, purpose, as_of_date, domains)
        def extract(self, urls, purpose):
            results = []
            for url in urls:
                if "fictional-port" in url:
                    text = "The port uses autonomous perimeter security in Canada."
                elif "fictional-mine" in url:
                    text = "The mine uses autonomous inspection in Chile."
                else:
                    continue
                results.append({"url": url, "raw_content": (text + " ") * 6})
            return {"results": results}
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema.__name__ == "Lead":
                lead = make_lead(data["enquiry"])
                if "Example Ports" in data["enquiry"]:
                    lead.industry = "shipping"
                return lead
            if schema is Materials:
                sid = next(sid for sid in data["sources"] if "fictional-" in self.run.sources[sid].url)
                source = self.run.sources[sid]
                quote = source.text.split(".")[0] + "."
                material = make_material(sid)
                material.title = source.title
                for dimension in material.dimensions:
                    dimension.rationale = claim(text="Potential source-backed similarity.", sid=sid, quote=quote, kind="inference")
                material.relevance = claim(text="A related industrial operational example.", sid=sid, quote=quote, kind="inference")
                return Materials(candidates=[material], referral_findings=[], gaps=[])
            return super().structured(schema, instruction, data, purpose, **kwargs)
    first = Workflow(settings, Industry, fake_fetch, research_factory=Industry).execute(enquiry, mode="offline_test")
    changed = enquiry.replace("Sociedad Quimica y Minera de Chile (SQM), Chile", "Example Ports, Canada").replace(
        "Looking for drone-based inspection for 3 large-scale, 24/7 lithium extraction sites in the Atacama Desert", "Looking for autonomous perimeter security for 3 large-scale harbour sites")
    second = Workflow(settings, Industry, fake_fetch, research_factory=Industry).execute(changed, mode="offline_test")
    assert first.queries != second.queries
    first_case = first.stages[3].output["primary"]["candidate"]
    second_case = second.stages[3].output["primary"]["candidate"]
    assert first_case["source_id"] != second_case["source_id"]
    assert "mine" in first_case["title"] and "port" in second_case["title"]
    assert any("shipping" in " ".join(queries) for purpose, queries in Industry.seen if purpose == "search:materials")


def test_main_article_excludes_featured_customer_navigation(monkeypatch, settings, enquiry):
    monkeypatch.setattr("flytbase_bdr.evidence.assert_public_url", lambda url: None)
    html = ('<html><title>Port operations example</title><div role="navigation">SQM uses FlytBase for mine inspection.</div>'
            '<main><h1>Port operations example</h1>' + 'The port team evaluates drone security patrols at its harbour facility. ' * 6 + '</main></html>')
    src = Source(source_id="S_port", url="https://flytbase.com/case-studies/port-demo", title="Port example", retrieved_at=now())
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"}))) as client:
        fetch_source(src, 4000, client=client)
    assert src.access == "inspected_page" and "SQM" not in src.text
    run = new_run(enquiry, settings, "offline_test")
    from conftest import make_lead
    run.stages[0].output = {"lead": make_lead(enquiry).model_dump()}
    run.sources[src.source_id] = src
    assert own_company_mentions(run) == []


def test_unrelated_case_does_not_suppress_customer_and_referral_discovery():
    from flytbase_bdr.story_discovery import missing_story_connections
    lead = {"company": "Example Mining (EXM)", "referral": "Peer Mining"}
    sources = {"S1": Source(source_id="S1", url="https://flytbase.com/case-studies/other-port", title="Other port",
                            retrieved_at=now(), access="inspected_page", text="A port uses autonomous security operations.")}
    assert missing_story_connections(sources, lead)
    sources["S1"].title = "EXM mine inspection"
    assert missing_story_connections(sources, lead)  # referral not investigated yet
    sources["S2"] = Source(source_id="S2", url="https://flytbase.com/case-studies/peer-mining", title="Peer Mining inspection",
                           retrieved_at=now(), access="inspected_page", text="A peer has a mine inspection deployment.")
    assert not missing_story_connections(sources, lead)


def test_partner_domicile_is_separate_from_documented_local_activity(settings, lead, enquiry):
    run = new_run(enquiry, settings, "offline_test")
    run.stages[0].output = {"lead": lead.model_dump()}
    src = Source(source_id="S_partner", url="https://flytbase.com/case-studies/fixture-integrator", title="Fictional implementation story",
                 retrieved_at=now(), access="inspected_page", text="Andes Field Robotics, a Chile-based integrator, evaluates industrial drone use cases.")
    run.sources[src.source_id] = src
    first = decide_routing(route_proposal(run, [src.source_id]), run.sources, enquiry, run.as_of_date, "Chile", [])
    assert first["candidates"][0]["name"] == "Andes Field Robotics"
    assert first["candidate_checks"][0]["country_presence_verified"]
    assert not first["candidate_checks"][0]["country_coverage_verified"]
    src.text += " Andes Field Robotics deployed an inspection system at a site in Chile."
    second = decide_routing(route_proposal(run, [src.source_id]), run.sources, enquiry, run.as_of_date, "Chile", [])
    assert second["implementation_candidates"][0]["name"] == "Andes Field Robotics"
    assert second["selected_partner_name"] == ""  # AE retains commercial ownership
    assert second["implementation_candidates"][0]["availability"].startswith("Not verified")


def test_partner_name_must_be_the_party_in_the_ecosystem_quote(settings, lead, enquiry):
    run = new_run(enquiry, settings, "offline_test")
    run.stages[0].output = {"lead": lead.model_dump()}
    src = Source(source_id="S_partner", url="https://flytbase.com/case-studies/fixture-integrator", title="Synthetic deployment",
                 retrieved_at=now(), access="inspected_page", text="Andes Field Robotics, a Chile-based integrator, deployed an inspection system in Chile.")
    run.sources[src.source_id] = src
    proposal = route_proposal(run, [src.source_id])
    proposal.recommended_motion = "partner_led"
    proposal.candidates[0].name = "Invented Partner"
    proposal.proposed_partner_name = "Invented Partner"
    result = decide_routing(proposal, run.sources, enquiry, run.as_of_date, "Chile", [])
    assert result["recommended_motion"] == "direct_ae" and not result["implementation_candidates"]


def test_research_gap_is_not_classified_as_provider_failure(settings, enquiry):
    class Gap(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            value = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Research:
                value.topics[0].gaps = ["Named buyer's personal reporting line is not publicly established."]
            return value
    run = Workflow(settings, Gap, fake_fetch, research_factory=Gap).execute(enquiry, mode="offline_test")
    assert run.stages[1].status == "partial"
    assert run.stages[1].technical_status == "succeeded" and run.stages[1].evidence_status == "partial"


def test_failed_partner_ai_remains_provisional_in_handoff(settings, enquiry):
    class Failed(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is Routing:
                raise ProviderError("groq: HTTP 400; invalid request fixture")
            return super().structured(schema, instruction, data, purpose, **kwargs)
    run = Workflow(settings, Failed, fake_fetch, research_factory=Failed).execute(enquiry, mode="offline_test")
    assert run.stages[4].status == "partial" and run.stages[4].technical_status == "partial"
    assert run.stages[4].output["groundedness"]["semantic_review"] == "rule_based_fallback"
    assert run.stages[5].output["routing"]["commercial_owner"] == "FlytBase Account Executive"
    assert not run.stages[5].output["routing"].get("implementation_candidates")


def test_five_email_scenarios_withhold_unsupported_copy(settings, enquiry):
    class Unsafe(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            value = super().structured(schema, instruction, data, purpose, **kwargs)
            if schema is Responses:
                value.drafts[1].paragraphs = [claim(text="FlytBase will reduce costs by 60%.", sid="", kind="inference")]
                value.drafts[1].hypothetical = False
                value.drafts[2].subject = "Guaranteed funding already approved"
            if schema is Audit and purpose == "audit:emails":
                assert any(field["path"] == "drafts.2.subject" for field in data["review_fields"])
                return Audit(findings=[AuditFinding(path="drafts.2.subject", reason="Approval is not established.", severity="error")])
            return value
    run = Workflow(settings, Unsafe, fake_fetch, research_factory=Unsafe).execute(enquiry, mode="offline_test")
    output = run.stages[2].output
    assert len(output["drafts"]) == 5 and output["drafts"][1]["hypothetical"]
    assert output["drafts"][1]["paragraphs"] == []
    assert output["drafts"][2]["subject"].startswith("Subject withheld")
    assert output["withheld_content"] and run.stages[2].status == "partial"
    assert all("60%" not in str(d["paragraphs"]) for d in output["drafts"])


def test_unknown_label_cannot_hide_positive_claim(source):
    value = claim(text="The prospect has approved a drone budget.", sid="", kind="unknown")
    assert any("positive assertion" in issue for issue in check_claim(value, {source.source_id: source}, "", "2026-11-04"))


def test_financial_metadata_cannot_invent_currency_units_or_publication_date(source):
    from flytbase_bdr.models import FinancialContext
    source.publication_date = ""
    source.text = "Capital expenditures in 2025 were USD 10 million for the company."
    value = claim(text=source.text, quote=source.text)
    value.financial_context = FinancialContext(currency="CLP", units="billion", reporting_period="2025", publication_date="2026-01-01", scope="company-wide spending")
    issues = check_claim(value, {source.source_id: source}, "", "2026-11-04")
    assert any("currency" in issue for issue in issues)
    assert any("units" in issue for issue in issues)
    assert any("publication date" in issue for issue in issues)


def test_historical_five_drafts_are_checked_without_rewriting_saved_run():
    path = ROOT / "runs" / "20261104T182119_520bf7ec5e" / "run.json"
    if not path.exists():
        pytest.skip("Private historical evidence excluded")
    from flytbase_bdr.sales_validation import checked_drafts
    before = path.read_bytes()
    run = load_run(path)
    output, warnings = checked_drafts(run.stages[2].output, run.sources, run.input, run.as_of_date)
    assert len(output["drafts"]) == 5 and warnings
    assert "demonstrates the ability to scale" not in str(output["drafts"][1]["paragraphs"])
    assert "FY2026" not in str(output["drafts"][3]["paragraphs"])
    assert "FY2027" not in str(output["drafts"][3]["paragraphs"])
    assert before == path.read_bytes()


def test_new_saved_run_all_five_pages_replay_without_providers(monkeypatch):
    path = ROOT / "runs" / "20261104T182119_520bf7ec5e" / "run.json"
    if not path.exists():
        pytest.skip("Private historical run excluded from source package")
    protected = [path, ROOT / "runs" / "project_budget.json"]
    before = {p: p.read_bytes() for p in protected}
    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must never construct providers")
    monkeypatch.setattr("flytbase_bdr.providers.groq.GroqProvider.__init__", forbidden)
    monkeypatch.setattr("flytbase_bdr.providers.tavily.TavilyProvider.__init__", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["run"] = load_run(path)
    app.session_state["replay"] = True
    app.run(timeout=30)
    for page in ["Command Center", "Account Intelligence", "Sales Strategy", "AE Handoff", "How It Works & Evidence"]:
        next(r for r in app.radio if "Command Center" in r.options).set_value(page).run(timeout=30)
        assert not app.exception, page
        assert app.session_state["run"].run_id == path.parent.name
    assert {p: p.read_bytes() for p in protected} == before
