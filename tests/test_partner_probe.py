"""All HTTP responses are synthetic; these tests spend no API resources."""
import json
import httpx
import pytest
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.models import Routing
from flytbase_bdr.partner_probe import plan, execute, RECEIPT
from flytbase_bdr.provider import ProviderError, RequestTooLarge
from flytbase_bdr.providers.groq import GroqProvider, strict_schema, PARTNER_SCHEMA_PROBE
from flytbase_bdr.workflow import new_run


@pytest.fixture
def probe_budget(settings, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_offline_probe_test_key_12345678")
    settings.project_max_groq_tokens = 110000
    budget = ProjectBudget(settings)
    budget.reserve("groq", 38241, "synthetic historical usage")
    budget.authorize_groq_ceiling(110000)
    budget.reserve("groq", 21314, "synthetic earlier repair use")
    return settings, budget


def test_offline_plan_is_under_2000_with_exact_production_schema(probe_budget):
    settings, budget = probe_budget
    before = budget.path.read_bytes()
    result = plan(settings)
    assert result["schema"] == "Routing" and result["strict"]
    assert result["estimated_input_tokens"] + result["completion_token_limit"] == result["estimated_total_tokens"]
    assert result["estimated_total_tokens"] < 2000
    assert result["automatic_retries"] == 0 and result["max_requests"] == 1
    assert result["repair_allowance_available"] == 4686
    assert budget.path.read_bytes() == before
    assert not (settings.run_path() / RECEIPT).exists()


def test_no_request_or_receipt_without_explicit_approval(probe_budget, monkeypatch):
    settings, budget = probe_budget
    before = budget.path.read_bytes()
    def forbidden(*a, **k):
        raise AssertionError("No provider should be constructed before approval")
    monkeypatch.setattr("flytbase_bdr.partner_probe.GroqProvider", forbidden)
    with pytest.raises(ProviderError, match="Explicit approval"):
        execute(settings)
    assert budget.path.read_bytes() == before
    assert not (settings.run_path() / RECEIPT).exists()


def test_single_request_receipt_actual_usage_and_reserves(probe_budget):
    settings, budget = probe_budget
    before = budget.read()
    calls = []
    answer = {"recommended_motion": "direct_ae", "rationale": [], "candidates": [], "proposed_partner_name": "",
              "required_partner_type": "", "commercial_owner": "", "implementation_owner": "",
              "next_action": "Discovery", "gaps": []}
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert body["response_format"]["json_schema"]["schema"] == strict_schema(Routing)
        return httpx.Response(200, json={"id": "offline", "model": settings.groq_model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 140, "total_tokens": 1340}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = execute(settings, approved=True, client=client)
    assert len(calls) == 1 and calls[0]["max_completion_tokens"] == 320
    assert result["actual_response"] == answer and result["reported_total_tokens"] == 1340
    assert result["actual_provider_requests"] == 1 and result["status"] == "schema_accepted"
    after = budget.read()
    assert after["entries"][:-1] == before["entries"]
    assert after["ceilings"] == before["ceilings"] and after["phase_limits"] == before["phase_limits"]
    assert budget.summary()["groq"]["repair_remaining"] == 4686 - 1340
    with pytest.raises(ProviderError, match="already reserved or executed"):
        execute(settings, approved=True)
    assert len(calls) == 1 and budget.read() == after


@pytest.mark.parametrize("status", [400, 429, 503])
def test_errors_never_retry_or_refund_unknown_usage(probe_budget, status):
    settings, budget = probe_budget
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"code": "fixture_error", "message": "Synthetic error"}})
    result = execute(settings, approved=True, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(calls) == result["actual_provider_requests"] == 1
    assert result["status"] == "failed" and result["actual_response"] is None
    assert result["reported_total_tokens"] is None
    assert budget.read()["entries"][-1]["actual"] is None
    assert result["plan"]["estimated_total_tokens"] < 2000


def test_regular_partner_synthesis_cannot_bypass_completion_floor(settings, enquiry, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_offline_probe_test_key_23456789")
    def forbidden(request):
        raise AssertionError("Probe budget must not be used for business synthesis")
    provider = GroqProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(forbidden)))
    try:
        with pytest.raises(RequestTooLarge, match="minimum"):
            provider.structured(Routing, PARTNER_SCHEMA_PROBE, {"company": "Any actual enquiry"}, "probe:partner-schema", max_tokens=320)
    finally:
        provider.close()
