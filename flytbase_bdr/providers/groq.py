import json
import time
import hashlib
from pydantic import ValidationError
from ..provider import HTTPProvider, ProviderError, QuotaExhausted, RequestTooLarge, estimate_tokens, shared_pacer, WindowPacer, ProjectWindowWait, wait_seconds
from ..prompts import SYSTEM
from ..budget import ProjectBudget

STRICT_FREE_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"}
PARTNER_SCHEMA_PROBE = ("Schema probe only. Return direct_ae; rationale, candidates, gaps=[]; "
                        "all string fields empty except next_action='Discovery'. No research or partner names.")
PARTNER_PROBE_OUTPUT_TOKENS = 320


def strict_schema(schema):
    data = schema.model_json_schema()
    def visit(node):
        if isinstance(node, dict):
            # A schema's title is metadata; a property named 'title' is business data.
            if isinstance(node.get("title"), str):
                node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(data)
    def validate(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and (
                node.get("additionalProperties") is not False
                or set(node.get("required", [])) != set(node.get("properties", {}))
            ):
                raise ProviderError("Local strict-schema validation failed; no request sent.")
            ref = node.get("$ref")
            if ref and (not ref.startswith("#/$defs/") or ref.split("/")[-1] not in data.get("$defs", {})):
                raise ProviderError("Local schema has an unresolved reference; no request sent.")
            for child in node.values():
                validate(child)
        elif isinstance(node, list):
            for child in node:
                validate(child)
    validate(data)
    return data


def structured_payload(schema, instruction, data, settings, purpose, max_tokens=None):
    """Pure request construction, also exercised with saved evidence offline."""
    limit = min(max_tokens or settings.max_output_tokens, settings.max_output_tokens)
    if settings.task_aware_tokens and not purpose.startswith("probe:"):
        from ..token_policy import completion_target
        limit = min(limit, completion_target(schema, data))
    if purpose.startswith("audit:"):
        limit = min(limit, 1800 if settings.task_aware_tokens else 1400 if settings.expanded_research else 1000)
    payload = {"model": settings.groq_model,
               "messages": [{"role": "system", "content": SYSTEM + "\n" + instruction},
                            {"role": "user", "content": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}],
               "response_format": {"type": "json_schema", "json_schema": {
                   "name": schema.__name__, "strict": True, "schema": strict_schema(schema)}},
               "max_completion_tokens": limit, "stream": False}
    if settings.groq_model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    return payload, limit


class GroqProvider(HTTPProvider):
    supports_compact_material_comparison = True
    supports_compact_partner_advice = True
    supports_safe_email_recovery = True
    name, key_name, base_url = "groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/"

    def __init__(self, settings, run, client=None):
        super().__init__(settings, run, client)
        if settings.groq_model not in STRICT_FREE_MODELS:
            raise ProviderError("Model is not in the documented free/strict-output allowlist; no paid-model fallback exists.")
        self.requests = 0
        self.budget = ProjectBudget(settings)
        self.pacer = shared_pacer(self.name, self.key, settings.groq_model)

    def check_model(self):
        data, _ = self.request("GET", "models", "probe:model access")
        if self.settings.groq_model not in {m.get("id") for m in data.get("data", [])}:
            raise ProviderError("Configured Groq model is not exposed to this key; no replacement selected.")
        return {"configured_model_exposed": True, "model": self.settings.groq_model,
                "billing_note": "Models endpoint does not expose billing plan; keep Groq on Free without billing."}

    def probe_partner_schema(self):
        """Compile the production Routing schema using an intentionally empty answer.

        The regular 1,600-token business-synthesis floor is unchanged. Only this
        fixed, evidence-free probe may use 320 completion tokens.
        """
        from ..models import Routing
        return self.structured(Routing, PARTNER_SCHEMA_PROBE, {}, "probe:partner-schema",
                               max_tokens=PARTNER_PROBE_OUTPUT_TOKENS)

    def structured(self, schema, instruction, data, purpose, max_tokens=None):
        payload, limit = structured_payload(schema, instruction, data, self.settings, purpose, max_tokens)
        estimated_input = estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        allowance = self.budget.summary()["groq"]
        remaining = allowance["remaining_for_reservation"]
        from ..execution import current_execution_phase
        demo = self.budget.demo_summary() if current_execution_phase() == "demo" else None
        if demo:
            remaining = demo["groq_remaining"]
        elif current_execution_phase() == "new_run":
            from ..execution import current_allowance_id
            from ..run_allowance import get_item, remaining as allowance_remaining
            record = self.budget.read()
            remaining = allowance_remaining(record, get_item(record, current_allowance_id()))
        elif current_execution_phase() == "repair":
            remaining = min(remaining, allowance.get("repair_remaining", remaining))
        else:
            remaining = max(0, remaining - allowance.get("emergency_reserve", 0))
        effective_tpm = int(self.settings.groq_tpm * self.settings.rate_safety_margin)
        if hasattr(self.pacer, "capacity"):
            effective_tpm = self.pacer.capacity(effective_tpm, self.settings.rate_safety_margin)
        ceiling = min(self.settings.max_request_tokens, effective_tpm)
        # A large context should not fail merely because the *requested* completion
        # reservation is too generous: shrink output to fit BOTH the shared project
        # ledger and the single-minute/request window. Never send a clearly unusable
        # completion budget to a complex JSON-schema task.
        available_output = int(min(remaining, ceiling) - estimated_input)
        # Strict JSON structures vary enormously in size. Never waste a free
        # request when the remaining window could not fit even a minimal record.
        minimum_for_schema = {
            "Lead": 950, "Research": 1350, "Topic": 550,
            "AccountAdvice": 550, "Materials": 1900, "MaterialChoice": 600, "Routing": 1600,
            "Responses": 1800, "RouteAdvice": 350, "Audit": 300,
        }
        minimum_useful_output = minimum_for_schema.get(schema.__name__, min(limit, 600))
        if self.settings.expanded_research and schema.__name__ == "Responses":
            minimum_useful_output = 3000  # Five fully typed branches; do not shrink into known truncation risk.
        if self.settings.task_aware_tokens and schema.__name__ == "Topic":
            minimum_useful_output = 1700
        from ..models import Routing
        if (schema is Routing and purpose == "probe:partner-schema" and instruction == PARTNER_SCHEMA_PROBE
                and data == {} and limit == PARTNER_PROBE_OUTPUT_TOKENS):
            minimum_useful_output = PARTNER_PROBE_OUTPUT_TOKENS
        if limit < minimum_useful_output:
            raise RequestTooLarge(f"Groq '{purpose}' configured completion limit {limit} is below the useful {schema.__name__} minimum {minimum_useful_output}; no request sent.")
        if available_output < minimum_useful_output:
            if estimated_input + minimum_useful_output > ceiling:
                raise RequestTooLarge(f"Groq '{purpose}' input leaves fewer than {minimum_useful_output} completion tokens under the free-tier request ceiling {ceiling}. No request sent; shorten context.")
            raise QuotaExhausted(f"Project Groq allowance cannot cover '{purpose}' input plus a useful output; progress preserved.")
        if available_output < limit:
            limit = available_output
            payload["max_completion_tokens"] = limit
            self.run.logs.append({"event": "output_reservation_reduced_to_available_window", "purpose": purpose, "max_completion_tokens": limit})
        reservation = estimated_input + limit
        self.run.logs.append({"event": "structured_request_preflight", "purpose": purpose,
                              "model": self.settings.groq_model, "schema": schema.__name__, "strict": True,
                              "schema_sha256": hashlib.sha256(json.dumps(payload["response_format"], sort_keys=True).encode()).hexdigest(),
                              "estimated_input_tokens": estimated_input, "max_completion_tokens": limit,
                              "minimum_completion_tokens": minimum_useful_output, "request_reservation_tokens": reservation})
        ticket, budget_ticket = None, None
        def before():
            nonlocal ticket, budget_ticket
            if self.requests >= self.settings.max_api_requests:
                raise QuotaExhausted("Groq per-run attempt budget exhausted; no inference or fallback.")
            used_input = sum(u.get("input_tokens", 0) or 0 for u in self.run.usage if u.get("provider") == "groq")
            used_output = sum(u.get("output_tokens", 0) or 0 for u in self.run.usage if u.get("provider") == "groq")
            if used_input + estimated_input > self.settings.max_total_input_tokens or used_output + limit > self.settings.max_total_output_tokens:
                raise QuotaExhausted("Groq per-run token allowance exhausted; no request sent.")
            notify_wait = lambda delay: self.run.logs.append({"event": "rate_wait", "provider": "groq", "purpose": purpose, "seconds": round(delay, 1)})
            if isinstance(self.pacer, WindowPacer):
                ticket = self.pacer.reserve(reservation, effective_tpm, self.settings.groq_rpm, notify_wait,
                    input_tokens=estimated_input, output_tokens=limit,
                    input_tpm=self.settings.groq_input_tpm, output_tpm=self.settings.groq_output_tpm)
            else:
                ticket = self.pacer.reserve(reservation, effective_tpm, self.settings.groq_rpm, notify_wait)
            for window_attempt in range(4):
                try:
                    budget_ticket = self.budget.reserve("groq", reservation, purpose, run_id=self.run.run_id,
                        request_window={"tpm": effective_tpm, "rpm": self.settings.groq_rpm} if self.settings.task_aware_tokens else None)
                    break
                except ProjectWindowWait as exc:
                    if window_attempt == 3:
                        raise QuotaExhausted("Shared project window stayed busy; bounded scheduler stopped without dispatch.") from None
                    notify_wait(exc.seconds)
                    wait_seconds(exc.seconds)
            self.requests += 1
        started = time.monotonic()
        raw, headers = self.request("POST", "chat/completions", purpose, payload, before)
        usage = raw.get("usage") or {}
        if isinstance(usage.get("total_tokens"), int):
            self.pacer.settle(ticket, usage["total_tokens"], usage.get("prompt_tokens"), usage.get("completion_tokens"))
            self.budget.settle(budget_ticket, usage["total_tokens"])
        self.run.usage.append({"provider": "groq", "purpose": purpose, "model": raw.get("model"), "response_id": raw.get("id"),
                               "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                               "total_tokens": usage.get("total_tokens"), "details": usage,
                               "rate_limits": {k: v for k, v in headers.items() if k.startswith("x-ratelimit-")},
                               "elapsed_seconds": round(time.monotonic() - started, 2)})
        choices = raw.get("choices") or []
        if not choices or choices[0].get("finish_reason") != "stop":
            raise ProviderError(f"{purpose}: Groq output incomplete/refused; no result accepted.")
        message = choices[0].get("message") or {}
        if message.get("refusal") or not message.get("content"):
            raise ProviderError(f"{purpose}: Groq refusal/missing JSON; stage incomplete.")
        try:
            return schema.model_validate_json(message["content"])
        except (ValidationError, ValueError, TypeError):
            raise ProviderError(f"{purpose}: JSON failed local schema validation; no fabricated repair or fallback.") from None
