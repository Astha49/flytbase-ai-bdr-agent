"""Offline regression for budget-aware Groq structured-completion sizing."""
import json
import httpx
import pytest
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import Settings
from flytbase_bdr.models import Record, Run
from flytbase_bdr.provider import RequestTooLarge
from flytbase_bdr.providers.groq import GroqProvider
from flytbase_bdr.evidence import now


def new_run(enquiry, settings, mode="offline_test"):
    return Run(run_id="synthetic-regression", mode=mode, started_at=now(),
               as_of_date="2026-11-04", input=enquiry, config=settings.model_dump())


class TinyRecord(Record):
    ready: bool


def test_groq_shrinks_completion_reservation_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_offline_test_key_for_window_12345")
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "mock", "model": "openai/gpt-oss-120b",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ready":true}'}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 10, "total_tokens": 210}})
    settings = Settings(runs_dir=str(tmp_path / "runs"), groq_tpm=2500, max_request_tokens=2500,
                        max_output_tokens=2600)
    run = new_run("Valid example enquiry", settings, mode="offline_test")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GroqProvider(settings, run, client)
    try:
        assert provider.structured(TinyRecord, "Return ready", {"text": "x" * 1200}, "window regression").ready
        assert len(payloads) == 1
        assert 600 <= payloads[0]["max_completion_tokens"] < 2600
        assert ProjectBudget(settings).summary()["groq"]["actual_reported"] == 210
        assert any(x.get("event") == "output_reservation_reduced_to_available_window" for x in run.logs)
    finally:
        provider.close()


def test_groq_does_not_dispatch_if_input_exceeds_window(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_offline_test_key_for_window_54321")
    def forbidden(request):
        raise AssertionError("Oversized input must never be sent")
    settings = Settings(runs_dir=str(tmp_path / "runs"), groq_tpm=1500, max_request_tokens=1500)
    client = httpx.Client(transport=httpx.MockTransport(forbidden))
    provider = GroqProvider(settings, new_run("Valid example enquiry", settings, mode="offline_test"), client)
    try:
        with pytest.raises(RequestTooLarge):
            provider.structured(TinyRecord, "Return ready", {"text": "x" * 5000}, "too large")
    finally:
        provider.close()
