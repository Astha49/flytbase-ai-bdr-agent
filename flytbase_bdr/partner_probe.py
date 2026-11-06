"""One explicitly approved Groq schema probe; no search or full workflow.

Default invocation is a read-only plan. --approve-live permits one attempt only.
The receipt is created exclusively before dispatch and prevents repeat execution,
including after a timeout or crash. Existing provider retries are disabled locally.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .budget import ProjectBudget
from .config import Settings, credential_status
from .evidence import now
from .execution import approved_live_execution
from .models import Routing, Run
from .provider import ProviderError, estimate_tokens
from .providers.groq import (
    GroqProvider, structured_payload, PARTNER_SCHEMA_PROBE, PARTNER_PROBE_OUTPUT_TOKENS,
)
from .reporting import sanitise

LIMIT = 1999
RECEIPT = "partner_schema_probe_once.json"


def probe_settings(settings):
    # Only in-memory execution bounds change; model, project ceiling, directory
    # and all ledger/phase guards remain exactly as locally configured.
    return settings.model_copy(update={"max_retries": 0, "max_api_requests": 1,
                                      "max_output_tokens": PARTNER_PROBE_OUTPUT_TOKENS,
                                      "max_request_tokens": LIMIT})


def plan(settings):
    configured = probe_settings(settings)
    payload, output = structured_payload(Routing, PARTNER_SCHEMA_PROBE, {}, configured,
                                         "probe:partner-schema", PARTNER_PROBE_OUTPUT_TOKENS)
    input_estimate = estimate_tokens(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    total = input_estimate + output
    if total > LIMIT:
        raise ProviderError(f"Probe estimate {total} exceeds the strict {LIMIT}-token cap; no request authorised.")
    allowance = ProjectBudget(configured).summary()["groq"]
    available = allowance.get("repair_remaining", allowance["remaining_for_reservation"])
    return {"mode": "offline plan", "model": configured.groq_model, "schema": "Routing",
            "schema_sha256": hashlib.sha256(json.dumps(payload["response_format"], sort_keys=True).encode()).hexdigest(),
            "strict": True, "estimated_input_tokens": input_estimate, "completion_token_limit": output,
            "estimated_total_tokens": total, "estimated_total_limit": LIMIT,
            "max_requests": 1, "automatic_retries": 0, "tavily_requests": 0,
            "repair_allowance_available": available, "within_repair_allowance": total <= available,
            "groq_key_present": credential_status()["GROQ_API_KEY"],
            "prior_attempt_exists": (configured.run_path() / RECEIPT).exists(),
            "limitation": "Real Routing schema, deliberately empty candidates: tests compatibility only, not researched partner identification or historical root cause."}


def execute(settings, *, approved=False, client=None):
    if not approved:
        raise ProviderError("Explicit approval is required before this single live probe. No request sent.")
    settings = probe_settings(settings)
    details = plan(settings)
    if not details["within_repair_allowance"] or not details["groq_key_present"]:
        raise ProviderError("Insufficient repair allowance or missing Groq key; no probe sent.")
    receipt = settings.run_path() / RECEIPT
    report = {"started_at": now(), "status": "attempt_reserved_do_not_repeat", "plan": details,
              "actual_response": None, "usage": [], "logs": [],
              "historical_400_resolved": "Not established; this is a reduced-content schema acceptance test."}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    try:
        # No retry/reset/force option: an existing attempt requires human review.
        with receipt.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(sanitise(report), indent=2))
    except FileExistsError:
        raise ProviderError("A partner schema probe was already reserved or executed. Inspect its receipt; no second request permitted.") from None
    run = Run(run_id="partner_schema_probe", mode="live", started_at=now(),
              as_of_date=now()[:10], input="Schema compatibility check only; not an enquiry or workflow run.", config=settings.model_dump())
    provider = None
    try:
        with approved_live_execution(True, phase="repair"):
            provider = GroqProvider(settings, run, client)
            response = provider.probe_partner_schema()
        report["actual_response"] = response.model_dump()
        report["status"] = "schema_accepted"
        report["historical_400_resolved"] = (
            "Current configured model accepted the production Routing schema for this minimal request. "
            "The original failure's exact cause and full partner-stage success remain unproven.")
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc) if isinstance(exc, ProviderError) else f"{type(exc).__name__}; no raw exception/secret content retained."
    finally:
        if provider is not None:
            provider.close()
        report["finished_at"] = now()
        report["usage"], report["logs"] = run.usage, run.logs
        report["actual_provider_requests"] = sum(row.get("event") == "api_attempt" for row in run.logs)
        report["reported_total_tokens"] = sum(row.get("total_tokens", 0) or 0 for row in run.usage) if run.usage else None
        report["usage_note"] = "Provider-reported tokens only. If unavailable, the existing ledger keeps the request reservation; it is not refunded."
        report["budget_after"] = ProjectBudget(settings).summary()
        safe = sanitise(report)
        temporary = receipt.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        temporary.replace(receipt)
    return safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-live", action="store_true", help="Execute exactly one explicitly approved Groq request; do not use before approval")
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        result = execute(settings, approved=True) if args.approve_live else plan(settings)
    except ProviderError as exc:
        print(str(exc))
        return 1
    print(json.dumps(sanitise(result), ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {None, "schema_accepted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
