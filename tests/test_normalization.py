from flytbase_bdr.normalization import publication_iso, expand_verbatim, normalize_claims
from conftest import claim


def test_rfc_date_and_unknown_date_are_not_invented_events():
    assert publication_iso("Wed, 22 Apr 2026 20:04:13 GMT") == "2026-04-22"
    data = claim().model_dump()
    data["event_date"] = "unknown"
    normalize_claims(data)
    assert data["event_date"] == ""
    data["event_date"] = "2025"
    normalize_claims(data)
    assert data["event_date"] == "" and "2025" in data["uncertainty"]


def test_ellipsis_expansion_uses_only_a_real_contiguous_span():
    body = "Inspection at 4 large-scale, continuously operating industrial sites is needed."
    result = expand_verbatim("4 large-scale ... industrial sites", body)
    assert result in body and "continuously operating" in result
    assert expand_verbatim("4 sites ... unapproved funding", body) == "4 sites ... unapproved funding"
    assert expand_verbatim("without on‑site pilots", "Works without on-site pilots.") == "without on-site pilots"
