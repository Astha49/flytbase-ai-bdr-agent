"""Explicit, one-run cache-only allowances; no network access during planning/approval.

Legacy ceilings, entries and demo envelopes are never rewritten. Dashboard
observations are operator attestations, not independently verified balances.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math
import uuid

from .budget import ProjectBudget
from .config import Settings
from .provider import QuotaExhausted
from .reporting import load_run

GROUPS = ("organisation", "finance", "current", "materials", "partners")


class AllowanceError(ValueError):
    """Allowlisted local validation messages safe to show in the dashboard."""


def stamp():
    return datetime.now(timezone.utc)


def counted(entries):
    return sum(e["actual"] if e.get("actual") is not None else e["reserved"] for e in entries)


def reserve_floor(data):
    caps = data.get("phase_limits", {})
    return caps.get("emergency_reserve", 7759) + caps.get("demo_reserve_at_approval", 38000)


def daily_entries(data):
    day = stamp().date().isoformat()
    return [e for e in data.get("entries", []) if e.get("provider") == "groq" and e.get("at", "").startswith(day)]


def remaining(data, item):
    # Fresh-enquiry allowances also reserve Tavily credits. They must never be
    # subtracted from the Groq token allowance or daily token headroom.
    return max(0, item["groq_tokens"] - counted([e for e in data.get("entries", [])
               if e.get("allowance_id") == item["id"] and e.get("provider") == "groq"]))


def daily_count(data, observation):
    entries = daily_entries(data)
    since = [e for e in entries if datetime.fromisoformat(e["at"]) >= datetime.fromisoformat(observation["checked_at"])]
    # Snapshot may include some local records. Count the greater estimate,
    # adding all requests made since it; unknown reservations never disappear.
    return max(counted(entries), observation["used_tokens"] + counted(since))


def pending(data, exclude=""):
    return sum(remaining(data, a) for a in data.get("execution_allowances", [])
               if a["id"] != exclude and a["state"] in {"approved", "started"}
               and a["utc_day"] == stamp().date().isoformat())


def source_record(settings, path):
    path = Path(path).resolve()
    if not path.is_relative_to(settings.run_path().resolve()):
        raise AllowanceError("Continuation source must be an existing private run in the configured runs directory.")
    run = load_run(path)
    if run.mode != "live" or run.stages[0].status != "complete" or not run.stages[0].output.get("lead"):
        raise AllowanceError("A saved live run with completed lead extraction is required.")
    for group in GROUPS:
        cache = run.retrieval_cache.get(group, {})
        if not any(sid in run.sources and run.sources[sid].access in {"inspected_page", "inspected_pdf"}
                   for sid in cache.get("source_ids", [])):
            raise AllowanceError(f"Inspected {group} cache is missing; this zero-Tavily continuation is unavailable.")
    return path, run, hashlib.sha256(path.read_bytes()).hexdigest()


def plan(settings, source):
    path, run, digest = source_record(settings, source)
    # Recorded expanded-mode usage is more informative than the old compact
    # heuristic. All changed generation/audit prompts may invalidate their cache.
    observed = sum(u.get("total_tokens", 0) or 0 for u in run.usage
                   if u.get("provider") == "groq" and u.get("purpose") != "extraction")
    workload = max(26500, observed)
    recommended = math.ceil(workload * 1.20 / 1000) * 1000
    return {"execution_authorized": False, "source_run": str(path), "source_sha256": digest,
            "model": settings.groq_model,
            "source_run_id": run.run_id, "cached_groups": list(GROUPS),
            "regenerate_stages": [2, 3, 4, 5, 6], "qualification": "reuse; not fresh extraction",
            "groq_observed_comparable_tokens": observed,
            "groq_estimated_workload_tokens": workload, "recommended_new_run_cap": recommended,
            "estimate_limitations": "Historical workload plus 20% reserve, not a guarantee. Changed audit batches affect usage.",
            "tavily_credits": 0, "automatic_retries": 0, "max_requests": 24,
            "new_allowance_required": True, "provider_quota_verified": False,
            "freshness": "Original research timestamps retained; current developments are not freshly researched."}


def overview(settings):
    data = ProjectBudget(settings).read()
    today = daily_entries(data)
    return {"utc_day": stamp().date().isoformat(),
            "historical_groq_reported": sum(e["actual"] for e in data.get("entries", []) if e.get("provider") == "groq" and e.get("actual") is not None),
            "historical_groq_unknown": sum(e["reserved"] for e in data.get("entries", []) if e.get("provider") == "groq" and e.get("actual") is None),
            "legacy_project_ceiling": data["ceilings"]["groq"],
            "local_groq_today_counted": counted(today), "provider_daily_limit_planning_cap": 200000,
            "provider_balance_verified": False, "emergency_and_demo_headroom": reserve_floor(data),
            "new_run_allowances": [{"id": a["id"], "state": a["state"], "utc_day": a["utc_day"],
                                    "source_run_id": Path(a["source_run"]).parent.name,
                                    "groq_cap": a["groq_tokens"], "groq_remaining": remaining(data, a),
                                    "tavily_credits": 0} for a in data.get("execution_allowances", [])]}


def approve(settings, source, tokens, used_today, checked_at, *, approved=False, free_only=False):
    if not approved or not free_only:
        raise AllowanceError("Separate explicit budget approval and a current free-only dashboard confirmation are required.")
    proposal = plan(settings, source)
    checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    if checked.tzinfo is not None:
        checked = checked.astimezone(timezone.utc)
    if checked.tzinfo is None or not -60 <= (stamp() - checked).total_seconds() <= 900 or checked.date() != stamp().date():
        raise AllowanceError("Dashboard check must be timezone-aware, today UTC, and within 15 minutes.")
    if type(tokens) is not int or type(used_today) is not int or tokens < proposal["recommended_new_run_cap"] or used_today < 0:
        raise AllowanceError("Invalid allowance or daily usage; provide at least the read-only plan's estimated cap.")
    observation = {"checked_at": checked.isoformat(), "used_tokens": used_today,
                   "daily_limit": 200000, "tpm": 8000,
                   "basis": "operator-confirmed Free dashboard; not independently queried", "paid_billing": False}
    budget = ProjectBudget(settings)
    with budget.locked():
        data = budget.read()
        if not budget.path.exists():
            raise AllowanceError("Existing history ledger required; no replacement ledger created.")
        if any(a["source_sha256"] == proposal["source_sha256"] and a["state"] in {"approved", "started"}
               and a["utc_day"] == stamp().date().isoformat()
               for a in data.get("execution_allowances", [])):
            raise AllowanceError("An unspent/started allowance already exists for this source; no duplicate allocation.")
        if daily_count(data, observation) + pending(data) + tokens + reserve_floor(data) > 200000:
            raise QuotaExhausted("Daily free planning headroom cannot cover this allowance and protected reserves.")
        item = {"id": "run-" + uuid.uuid4().hex[:12], "state": "approved", "created_at": stamp().isoformat(),
                "utc_day": stamp().date().isoformat(), "groq_tokens": tokens, "groq_requests": 24, "tavily_credits": 0,
                "source_run": proposal["source_run"], "source_sha256": proposal["source_sha256"],
                "model": settings.groq_model,
                "run_id": "", "quota_observation": observation,
                "approval": "Explicit separate new-run budget approval; launch approval remains required"}
        data.setdefault("execution_allowances", []).append(item)
        budget.write(data)
        return item


def get_item(data, allowance_id):
    item = next((a for a in data.get("execution_allowances", []) if a["id"] == allowance_id), None)
    if item is None:
        raise QuotaExhausted("No separately approved new-run allowance found.")
    if item["utc_day"] != stamp().date().isoformat():
        raise QuotaExhausted("Allowance's UTC quota day has expired; no daily reset or automatic renewal.")
    return item


def cancel(settings, allowance_id, *, approved=False):
    """Cancel only an unused approval; preserve the record and all reservations."""
    if not approved:
        raise AllowanceError("Explicit cancellation confirmation required.")
    budget = ProjectBudget(settings)
    with budget.locked():
        data = budget.read()
        item = next((a for a in data.get("execution_allowances", []) if a["id"] == allowance_id), None)
        if not item or item["state"] != "approved" or any(e.get("allowance_id") == allowance_id for e in data["entries"]):
            raise AllowanceError("Only a never-started, unused approval can be cancelled; usage is never refunded.")
        item["state"], item["cancelled_at"] = "cancelled", stamp().isoformat()
        budget.write(data)
        return item


def reserve_entry(data, provider, amount, purpose, run_id, allowance_id, request_window=None):
    """Called inside the existing ledger's cross-process lock."""
    item = get_item(data, allowance_id)
    if item.get("kind") == "fresh_enquiry":
        # The new-input allowance is explicitly different from the historical
        # zero-Tavily continuation. It can use fresh research, but only against
        # the user's separately approved per-provider caps.
        if item["state"] != "started" or item["run_id"] != run_id or not run_id:
            raise QuotaExhausted("Fresh enquiry is not bound to an active approved run.")
        if provider not in {"groq", "tavily"}:
            raise QuotaExhausted("Unexpected provider blocked.")
        entries_for_provider = [e for e in data["entries"] if e.get("allowance_id") == allowance_id and e.get("provider") == provider]
        cap = item["groq_tokens"] if provider == "groq" else item["tavily_credits"]
        limit = item["groq_requests"] if provider == "groq" else item["tavily_requests"]
        if amount <= 0 or counted(entries_for_provider) + amount > cap or len(entries_for_provider) >= limit:
            raise QuotaExhausted(f"Fresh enquiry {provider} limit exhausted; progress saved, no automatic top-up.")
        if provider == "groq" and daily_count(data, item["quota_observation"]) + amount + pending(data, allowance_id) + reserve_floor(data) > 200000:
            raise QuotaExhausted("Daily free Groq headroom or protected reserve would be exceeded.")
        ticket = uuid.uuid4().hex
        data["entries"].append({"id": ticket, "at": stamp().isoformat(), "provider": provider,
                               "purpose": purpose, "reserved": amount, "actual": None,
                               "status": "reserved_or_usage_unavailable", "allowance_id": allowance_id,
                               "run_id": run_id, **({"request_window": request_window} if request_window else {})})
        return ticket
    if provider != "groq":
        raise QuotaExhausted("This cache-only allowance permits zero Tavily requests.")
    entries = [e for e in data["entries"] if e.get("allowance_id") == allowance_id]
    if item["state"] != "started" or item["run_id"] != run_id or not run_id:
        raise QuotaExhausted("New-run allowance is not started/bound to this exact run.")
    if amount <= 0 or amount > remaining(data, item) or len(entries) >= item["groq_requests"]:
        raise QuotaExhausted("New-run token/request cap exhausted; no automatic replenishment.")
    if (daily_count(data, item["quota_observation"]) + amount + pending(data, allowance_id) + reserve_floor(data) > 200000
            or len(daily_entries(data)) >= 990):
        raise QuotaExhausted("Conservative daily free allowance exhausted; no automatic daily retry.")
    ticket = uuid.uuid4().hex
    data["entries"].append({"id": ticket, "at": stamp().isoformat(), "provider": provider, "purpose": purpose,
                            "reserved": amount, "actual": None, "status": "reserved_or_usage_unavailable",
                            "allowance_id": allowance_id, "run_id": run_id,
                            **({"request_window": request_window} if request_window else {})})
    return ticket


def execute(settings, allowance_id, *, approved=False, on_update=None):
    if not approved:
        raise AllowanceError("Explicit live-launch approval is required; nothing started.")
    from .execution import approved_live_execution
    from .workflow import Workflow, fork_resume
    budget = ProjectBudget(settings)
    with budget.locked():
        data = budget.read()
        item = get_item(data, allowance_id)
        if item["state"] != "approved":
            raise AllowanceError("Allowance already started/finished. No duplicate launch permitted.")
        if item["model"] != settings.groq_model:
            raise AllowanceError("Model changed since budget approval; execution blocked.")
        if (stamp() - datetime.fromisoformat(item["quota_observation"]["checked_at"])).total_seconds() > 900:
            raise AllowanceError("Dashboard observation is stale; cancel the unused approval and obtain a fresh explicit approval.")
        _, original, digest = source_record(settings, item["source_run"])
        if digest != item["source_sha256"]:
            raise AllowanceError("Source record changed since approval; no execution.")
        if daily_count(data, item["quota_observation"]) + pending(data) + reserve_floor(data) > 200000:
            raise QuotaExhausted("Free daily headroom changed; execution blocked.")
        profile = settings.model_copy(update={"max_retries": 0, "task_aware_tokens": True, "expanded_research": True,
            "compact_account_research": False, "rate_safety_margin": min(settings.rate_safety_margin, .9), "max_output_tokens": 4800,
            "max_api_requests": min(settings.max_api_requests, 24), "groq_tpm": min(settings.groq_tpm, 8000), "groq_rpm": min(settings.groq_rpm, 25),
            "max_total_input_tokens": min(settings.max_total_input_tokens, item["groq_tokens"]),
            "max_total_output_tokens": min(settings.max_total_output_tokens, item["groq_tokens"])})
        fresh = fork_resume(original, profile)
        fresh.retrieval_cache.pop("_structured", None)
        item["state"], item["run_id"] = "started", fresh.run_id
        budget.write(data)
    def no_research(*args, **kwargs):
        raise QuotaExhausted("Cache-only continuation: fresh retrieval is forbidden; research gap retained.")
    result = None
    try:
        with approved_live_execution(True, phase="new_run", allowance_id=allowance_id, confirmed_free_quota=True):
            result = Workflow(profile, fetcher=no_research, research_factory=no_research).execute(
                fresh.input, resume=fresh, rerun_stages={1, 2, 3, 4, 5}, on_update=on_update)
            return result
    except Exception as error:
        from .reporting import save_run
        saved = settings.run_path() / fresh.run_id / "run.json"
        failed = load_run(saved) if saved.exists() else fresh
        failed.status, failed.finished_at = "failed", stamp().isoformat()
        for stage in failed.stages:
            if stage.status in {"pending", "running"}:
                stage.status = "failed" if stage.status == "running" else "skipped"
                stage.technical_status = stage.status
        failed.warnings.append(f"Execution aborted ({type(error).__name__}); no automatic retry. Prior outputs are not fresh verification.")
        save_run(failed, settings.run_path())
        raise
    finally:
        with budget.locked():
            data = budget.read()
            current = next(a for a in data["execution_allowances"] if a["id"] == allowance_id)
            current["state"], current["finished_at"] = "finished", stamp().isoformat()
            current["result_status"] = result.status if result else "failed"
            budget.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "approve"):
        sub.add_parser(action).add_argument("--source", required=True, type=Path)
    p = sub.choices["approve"]
    p.add_argument("--tokens", required=True, type=int)
    p.add_argument("--used-today", required=True, type=int)
    p.add_argument("--checked-at", required=True)
    p.add_argument("--approve-budget", action="store_true")
    p.add_argument("--confirm-free-only", action="store_true")
    p = sub.add_parser("execute")
    p.add_argument("--allowance", required=True)
    p.add_argument("--approve-live", action="store_true")
    p = sub.add_parser("cancel")
    p.add_argument("--allowance", required=True)
    p.add_argument("--confirm-cancel", action="store_true")
    args, settings = parser.parse_args(), Settings.from_env()
    if args.action == "plan":
        result = {"plan": plan(settings, args.source), "budgets": overview(settings)}
    elif args.action == "approve":
        result = approve(settings, args.source, args.tokens, args.used_today, args.checked_at,
                         approved=args.approve_budget, free_only=args.confirm_free_only)
    elif args.action == "cancel":
        result = cancel(settings, args.allowance, approved=args.confirm_cancel)
    else:
        result = execute(settings, args.allowance, approved=args.approve_live).model_dump(mode="json")
    from .reporting import sanitise
    print(json.dumps(sanitise(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
