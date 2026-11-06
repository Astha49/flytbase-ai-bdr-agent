import json
import httpx
import pytest
from flytbase_bdr.models import Record
from flytbase_bdr.workflow import new_run
from flytbase_bdr.providers.groq import GroqProvider, strict_schema
from flytbase_bdr.models import Lead, Materials
from flytbase_bdr.providers.tavily import TavilyProvider
from flytbase_bdr.provider import ProviderError, QuotaExhausted, RequestTooLarge, WindowPacer
from flytbase_bdr.budget import ProjectBudget


class SmallRecord(Record):
    ready: bool


class NoWait:
    def reserve(self, *args):
        return [0, args[0]]
    def settle(self, *args):
        pass


@pytest.fixture(autouse=True)
def isolated_providers(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_synthetic_test_key_never_a_real_secret")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-synthetic_test_key_never_a_real_secret")
    for module in ["groq", "tavily"]:
        monkeypatch.setattr(f"flytbase_bdr.providers.{module}.shared_pacer", lambda *a: NoWait())
    monkeypatch.setattr("flytbase_bdr.provider.wait_seconds", lambda n: None)


def groq_reply():
    return {"id": "synthetic", "model": "openai/gpt-oss-120b", "choices": [{"finish_reason": "stop", "message": {"content": '{"ready":true}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "completion_tokens_details": {"reasoning_tokens": 5}}}


def free_usage():
    return {"account": {"current_plan": "Researcher", "plan_limit": 1000, "plan_usage": 10, "paygo_limit": 0, "paygo_usage": 0},
            "key": {"limit": 1000, "usage": 10}}


def test_groq_strict_chat_contract_no_hosted_tools_and_actual_usage(settings, enquiry):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        return httpx.Response(200, json=groq_reply())
    run = new_run(enquiry, settings, "offline_test")
    p = GroqProvider(settings, run, httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.structured(SmallRecord, "Return ready", {}, "test", max_tokens=100).ready
    body = bodies[0]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in body and "responses" not in str(body.keys())
    assert run.usage[0]["total_tokens"] == 120  # reasoning already included, never add it again
    assert ProjectBudget(settings).summary()["groq"]["actual_reported"] == 120


def test_strict_schema_preserves_business_fields_named_title():
    schema = strict_schema(Lead)
    assert "title" in schema["properties"] and "title" in schema["required"]
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(schema)
    check(strict_schema(Materials))


def test_groq_rejects_oversized_payload_without_dispatch(settings, enquiry):
    def forbidden(request):
        raise AssertionError("No oversized request may be sent")
    p = GroqProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(forbidden)))
    with pytest.raises(RequestTooLarge):
        p.structured(SmallRecord, "Return ready", {"evidence": "x" * 30000}, "test")


def test_retry_after_attempt_budgets_and_no_secret_errors(settings, enquiry, monkeypatch):
    calls, waits = [], []
    monkeypatch.setattr("flytbase_bdr.provider.wait_seconds", lambda n: waits.append(n))
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "sensitive raw message"})
        return httpx.Response(200, json=groq_reply())
    p = GroqProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.structured(SmallRecord, "Return ready", {}, "test", max_tokens=100).ready
    assert len(calls) == 2 and waits == [2]
    budget = ProjectBudget(settings).summary()["groq"]
    assert budget["reserved_usage_unavailable"] > 0


def test_invalid_credentials_not_retried_or_exposed(settings, enquiry):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "raw secret token must not leak"})
    p = GroqProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        p.structured(SmallRecord, "Return ready", {}, "test", max_tokens=100)
    assert len(calls) == 1 and "raw secret" not in str(exc.value)


def test_tavily_official_sdk_basic_search_extract_and_free_plan(settings, enquiry):
    bodies = []
    def handler(request):
        if request.url.path == "/usage":
            return httpx.Response(200, json=free_usage())
        body = json.loads(request.content)
        bodies.append((request.url.path, body))
        if request.url.path == "/search":
            return httpx.Response(200, json={"results": [{"url": "https://example.com/story", "content": "Search excerpt"}], "usage": {"credits": 1}})
        return httpx.Response(200, json={"results": [{"url": "https://example.com/story", "raw_content": "Original extracted passage"}], "usage": {"credits": 0}})
    p = TavilyProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.search(["dynamic query"], "search:test", "2026-11-04")["results"]
    assert p.extract(["https://example.com/story"])["results"]
    search = bodies[0][1]
    assert search["search_depth"] == "basic" and search["auto_parameters"] is False
    assert search["include_usage"] is True and search["include_answer"] is False
    assert "max_age_hours" not in search  # free-plan cache reuse avoids unnecessary HTTP 434 failures
    assert bodies[1][1]["extract_depth"] == "basic"
    assert ProjectBudget(settings).summary()["tavily"]["actual_reported"] == 1


@pytest.mark.parametrize("change", [{"current_plan": "Project"}, {"paygo_limit": 10}, {"paygo_usage": 1}])
def test_tavily_paid_or_paygo_account_blocked_before_search(settings, enquiry, change):
    calls = []
    usage = free_usage()
    usage["account"].update(change)
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=usage)
    p = TavilyProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError):
        p.search(["query"], "search:test", "2026-11-04")
    assert calls == ["/usage"]


def test_persistent_project_budget_cannot_reset_on_new_provider(settings):
    first = ProjectBudget(settings)
    ticket = first.reserve("groq", 39000, "test")
    with pytest.raises(QuotaExhausted):
        ProjectBudget(settings).reserve("groq", 1001, "second")
    first.settle(ticket, 100)
    assert ProjectBudget(settings).summary()["groq"]["actual_reported"] == 100
    assert ProjectBudget(settings).summary()["groq"]["remaining_for_reservation"] == 39900


def test_nullable_tavily_caps_preserve_free_plan_limit_without_inventing_paygo_state(settings, enquiry):
    usage = free_usage()
    usage["account"]["paygo_limit"] = None
    usage["key"]["limit"] = None
    p = TavilyProvider(settings, new_run(enquiry, settings), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=usage))))
    record = p.check_free_plan()
    assert record["free_credits_remaining_at_check"] == 990
    assert record["paygo_limit"] is None
    assert "unspecified" in record["billing_protection"]


def test_concurrent_reservations_cannot_exceed_project_ceiling(settings):
    from concurrent.futures import ThreadPoolExecutor
    def reserve():
        try:
            ProjectBudget(settings).reserve("groq", 30000, "concurrency test")
            return True
        except QuotaExhausted:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: reserve(), range(2)))
    assert sorted(results) == [False, True]
    assert ProjectBudget(settings).summary()["groq"]["reserved_usage_unavailable"] == 30000
