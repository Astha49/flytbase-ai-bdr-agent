from flytbase_bdr.qualification import qualify
from flytbase_bdr.models import Signal
from flytbase_bdr.evidence import derive_queries


def test_unknown_budget_and_authority_are_not_negative(lead, enquiry):
    data = qualify(lead, enquiry)
    assert data["lead"]["budget"]["status"] == "unknown"
    assert data["lead"]["authority"]["status"] == "unknown"
    assert data["qualification_completeness_percent"] == 25
    assert data["priority_score"] == 80
    assert data["priority_band"] == "prompt discovery"


def test_quarter_without_year_stays_ambiguous_even_with_unrelated_year(lead, enquiry):
    data = qualify(lead, enquiry + "\nCompany founded in 1968; news reviewed in 2026.")
    assert data["lead"]["timeline"]["status"] == "ambiguous"
    assert "year" in " ".join(data["lead"]["timeline"]["questions"])
    assert not any(b["signal"] == "dated_timeline" for b in data["score_breakdown"])


def test_model_cannot_promote_discussion_title_or_referral(lead, enquiry):
    lead.budget.status = lead.authority.status = "confirmed"
    lead.budget.evidence = ["Internal budget conversation scheduled for Q3"]
    lead.authority.evidence = [lead.title]
    lead.signals += [Signal(code="approved_budget", quote=lead.budget.evidence[0]),
                     Signal(code="confirmed_authority", quote=lead.title)]
    data = qualify(lead, enquiry)
    assert data["lead"]["budget"]["status"] == data["lead"]["authority"]["status"] == "unknown"
    assert data["priority_score"] == 80


def test_missing_or_duplicate_signal_cannot_inflate_score(lead, enquiry):
    lead.signals += [lead.signals[0], Signal(code="approved_budget", quote="Approved $1 million")]
    assert qualify(lead, enquiry)["priority_score"] == 80


def test_changed_lead_changes_queries_and_score(lead, enquiry):
    old = derive_queries(lead, "2026-11-04")
    lead.company, lead.domain, lead.geography, lead.industry, lead.need, lead.referral = (
        "Example Ports", "ports.example", "Japan", "shipping", "harbour perimeter security", "")
    new = derive_queries(lead, "2026-11-04")
    assert old != new
    assert "Japan" in new["partners"][0] and any("ports.example" in q for queries in new.values() for q in queries)
    assert "Anglo American" not in str(new)
    lead.signals = []
    lead.need_dimension.status = "unknown"
    assert qualify(lead, enquiry)["priority_score"] == 0
