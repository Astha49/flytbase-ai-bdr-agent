import re
import pytest
import socket
from flytbase_bdr.config import Settings, ROOT
from flytbase_bdr.models import (Lead, Dimension, Signal, Claim, EvidenceRef, Source,
                                Research, Topic, Materials, Material, MatchDimension,
                                Routing, Partner, Responses, EmailDraft, Audit, AccountAdvice)
from flytbase_bdr.evidence import now


@pytest.fixture(autouse=True)
def offline_network_only(monkeypatch):
    original_connect = socket.socket.connect
    original_resolve = socket.getaddrinfo
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline tests must use fixtures or MockTransport; live network access is forbidden.")
    def local_connect(sock, address):
        # Windows asyncio builds its internal socket pair through loopback.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        return forbidden()
    def local_resolve(host, *args, **kwargs):
        if host in {"localhost", "127.0.0.1", "::1"}:
            return original_resolve(host, *args, **kwargs)
        return forbidden()
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket, "getaddrinfo", local_resolve)


@pytest.fixture
def enquiry():
    return (ROOT / "examples" / "enquiry.txt").read_text(encoding="utf-8")


def unknown(question="What needs clarification?"):
    return Dimension(status="unknown", evidence=[], uncertainty="Not established by enquiry.", questions=[question])


def make_lead(enquiry):
    name = re.search(r"From: (.*?) \(", enquiry).group(1)
    email = re.search(r"\(([^()]+@[^()]+)\)", enquiry).group(1)
    title = re.search(r"Title: (.*)", enquiry).group(1)
    company_line = re.search(r"Company: (.*)", enquiry).group(1)
    company, country = company_line.rsplit(", ", 1)
    context = re.search(r"Context: (.*)", enquiry).group(1)
    signals = [Signal(code="need_fit", quote=context.split(".")[0]),
               Signal(code="senior_role", quote=title)]
    for code, text in [("operational_pain", "Contracted crews are expensive and hazardous"),
                       ("multiple_sites", "3 large-scale"), ("continuous_operations", "24/7"),
                       ("referral", "Referred by Anglo American")]:
        if text in enquiry:
            signals.append(Signal(code=code, quote=text))
    return Lead(name=name, email=email, title=title, company=company, domain=email.split("@")[1],
                geography=country, industry="mining", need=context.split(".")[0],
                referral="Anglo American" if "Anglo American" in enquiry else "",
                knowns=[context], budget=unknown("Is funding approved?"), authority=unknown("Who signs off?"),
                need_dimension=Dimension(status="confirmed", evidence=[context.split(".")[0]], uncertainty="Technical feasibility remains unknown.", questions=["What are the pilot success criteria?"]),
                timeline=unknown("Which year and decision milestone?"), signals=signals,
                fit="promising", fit_reason="Explicit industrial inspection need; feasibility requires discovery.")


def claim(text="The test site uses autonomous inspections.", sid="S_test", quote="The test site uses autonomous inspections.", kind="public"):
    return Claim(text=text, kind=kind, evidence=[EvidenceRef(source_id=sid, quote=quote)] if sid else [],
                 input_quote="", uncertainty="Proposed recommendation; requires discovery." if kind == "inference" else "",
                 financial_context=None, event_date="")


def make_material(sid="S_test"):
    return Material(title="Synthetic fixture case", source_id=sid,
                    dimensions=[MatchDimension(dimension=d, matched=d in {"industry", "use_case"},
                                rationale=claim(sid=sid)) for d in ["industry", "use_case", "operating_context", "geography", "referral", "same_company"]],
                    relevance=claim(sid=sid), limitations=["Synthetic fixture; no outcomes transfer."],
                    own_company_expansion_assessment="Division/site coverage must be verified.")


@pytest.fixture
def lead(enquiry):
    return make_lead(enquiry)


@pytest.fixture
def source():
    return Source(source_id="S_test", url="https://www.flytbase.com/test-fixture", title="Synthetic fixture only",
                  retrieved_at=now(), publication_date="2026-01-01", access="inspected_page",
                  text="The test site uses autonomous inspections. The partner serves Chile.")


class FakeProvider:
    """Only for tests. Never exposed as a UI/CLI research mode."""
    def __init__(self, settings, run):
        self.run = run
        self.received = []

    def search(self, queries, purpose, as_of_date, domains=None):
        self.received.append((purpose, queries))
        url = "https://www.flytbase.com/test-fixture" if any(x in purpose for x in ["materials", "partners"]) else "https://company.example/filing"
        return {"text": "Synthetic fixture summary. Not live evidence.", "output": [
            {"type": "web_search_call", "action": {"type": "search", "sources": [{"url": url, "title": "Synthetic fixture"}]}},
            {"type": "message", "content": [{"annotations": [{"type": "url_citation", "url": url, "title": "Synthetic fixture"}]}]}]}

    def extract(self, urls, purpose="extract:test"):
        return {"results": []}

    def structured(self, schema, instruction, data, purpose, **kwargs):
        self.received.append((purpose, data))
        if schema is Lead:
            return make_lead(data["enquiry"])
        if schema is Audit:
            return Audit(findings=[])
        sid = next(iter(data.get("sources", {})), "S_missing")
        if schema is Topic:
            name = purpose.split(":", 1)[1]
            return Topic(name=name, claims=[claim(sid=sid)], gaps=[])
        if schema is AccountAdvice:
            return AccountAdvice(positioning=[claim(sid="", kind="inference")], stakeholder_hypothesis=[], conflicts=[])
        if schema is Research:
            return Research(topics=[Topic(name=n, claims=[claim(sid=sid)], gaps=[]) for n in [
                "Organisation and reporting lines", "Budget and investment signals", "News and strategic announcements",
                "Investor priorities", "Corporate changes and customer relationships"]],
                positioning=[claim(sid="", kind="inference")], stakeholder_hypothesis=[], conflicts=[])
        if schema is Materials:
            return Materials(candidates=[make_material(sid)], referral_findings=[], gaps=[])
        if schema is Routing:
            return Routing(recommended_motion="direct_ae", rationale=[claim(sid="", kind="inference")], candidates=[],
                           proposed_partner_name="", required_partner_type="Local industrial drone integrator",
                           commercial_owner="FlytBase AE", implementation_owner="Verify local support",
                           next_action="Confirm local implementation capability", gaps=[])
        if schema is Responses:
            return Responses(drafts=[EmailDraft(branch=b, subject="Discuss your inspection needs", paragraphs=[
                claim(text="Could we discuss pilot success criteria?", sid="", kind="inference")],
                trigger="New enquiry" if b == "initial" else "Hypothetical follow-up condition",
                why_this_message="Clarify discovery gaps", if_buyer_responds="Adjust next step to their response",
                hypothetical=b != "initial") for b in ["initial", "no_reply", "interested", "budget_clarification", "stakeholder_referral"]], limitations=[])
        raise AssertionError(schema)


def fake_fetch(source, max_chars):
    source.access = "inspected_page"
    source.text = "The test site uses autonomous inspections. The partner serves Chile."
    source.publication_date = "2026-01-01"


@pytest.fixture
def settings(tmp_path):
    return Settings(runs_dir=str(tmp_path / "runs"))
