"""Prepare/read the single real demo envelope locally. This module never calls an API."""
import argparse
import json
from .budget import ProjectBudget
from .config import Settings
from .reporting import load_run


def demo_settings(settings, envelope=None):
    """One-run limits only; do not rewrite .env or loosen normal repair controls."""
    if envelope and envelope.get("sequence") == 4:
        optimized = envelope.get("optimized_research", False)
        return Settings(**{**settings.model_dump(), "groq_model": "openai/gpt-oss-120b",
            "task_aware_tokens": optimized, "selective_search_depth": optimized,
            "rate_safety_margin": .95 if optimized else 1.0,
            "expanded_research": True, "compact_account_research": False,
            "groq_tpm": min(settings.groq_tpm, 8000), "groq_rpm": min(settings.groq_rpm, 25),
            "max_request_tokens": min(settings.max_request_tokens, 7500),
            "max_output_tokens": 4800 if optimized else 4000, "max_api_requests": 30, "max_retries": 1,
            "max_total_input_tokens": 62000, "max_total_output_tokens": 30000,
            "tavily_search_depth": "advanced", "tavily_extract_depth": "basic",
            "max_search_requests": envelope.get("limits", {}).get("search_requests", 12),
            "max_extract_requests": envelope.get("limits", {}).get("extract_requests", 8),
            "max_tavily_credits": envelope.get("limits", {}).get("tavily", 32),
            "max_results_per_query": 5, "max_source_fetches": 30 if optimized else 20, "max_source_chars": 18000,
            "evidence_chars_per_source": 2400 if optimized else 2200, "evidence_chars_per_request": 6000 if optimized else 4500})
    return settings.model_copy(update={
        "groq_model": "openai/gpt-oss-120b", "groq_tpm": min(settings.groq_tpm, 8000),
        "groq_rpm": min(settings.groq_rpm, 25), "max_request_tokens": min(settings.max_request_tokens, 7500),
        "max_api_requests": min(settings.max_api_requests, 24), "max_search_requests": min(settings.max_search_requests, 10),
        "max_extract_requests": min(settings.max_extract_requests, 5), "max_tavily_credits": min(settings.max_tavily_credits, 16),
        "max_retries": min(settings.max_retries, 1), "max_output_tokens": min(settings.max_output_tokens, 2600),
        "max_total_input_tokens": min(settings.max_total_input_tokens, 60000),
        "max_total_output_tokens": min(settings.max_total_output_tokens, 30000)})


def research_seed(settings, enquiry):
    """Choose the strongest *finished* matching source cache, not the newest partial one.

    A newer interrupted run can have only one research group and would defeat
    our cache-first demo. Count usable inspected sources per saved retrieval
    group and prefer a same-day record; never replay model responses or copy
    prior stage outputs. Cached research keeps its original inspection dates.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    best, best_score = None, None
    groups = ("organisation", "finance", "current", "materials", "partners")
    for path in settings.run_path().glob("*/run.json"):
        try:
            run = load_run(path)
        except (ValueError, OSError, KeyError):
            continue
        if (run.mode != "live" or run.input != enquiry or run.status == "running"
                or not run.sources or not run.retrieval_cache):
            continue
        eligible = 0
        inspected = 0
        for group in groups:
            cached = run.retrieval_cache.get(group, {})
            ids = cached.get("source_ids", []) if isinstance(cached, dict) else []
            valid = [sid for sid in ids if sid in run.sources and
                     run.sources[sid].access in {"inspected_page", "inspected_pdf"}]
            if valid:
                eligible += 1
                inspected += len(valid)
        if eligible == 0:
            continue
        score = (int(run.as_of_date == today), eligible, inspected, run.started_at)
        if best_score is None or score > best_score:
            best, best_score = run, score
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Prepare the user-requested 60000-token/16-credit envelope; no live execution")
    parser.add_argument("--prepare-second", action="store_true", help="Prepare one additional bounded free-only demo; no API requests")
    parser.add_argument("--prepare-third", action="store_true", help="Prepare one fresh 60000-token/16-credit free-only run; no API requests")
    parser.add_argument("--prepare-fourth", action="store_true", help="Prepare a separate fourth 62000-token/32-credit envelope; no API requests")
    parser.add_argument("--confirm-free-only", action="store_true")
    parser.add_argument("--optimize-fourth", action="store_true", help="Amend unused fourth allowance only; no provider requests")
    args = parser.parse_args()
    budget = ProjectBudget(Settings.from_env())
    if sum((args.prepare, args.prepare_second, args.prepare_third, args.prepare_fourth, args.optimize_fourth)) > 1:
        parser.error("Choose one preparation mode only.")
    if args.optimize_fourth:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only required; ledger unchanged.")
        budget.optimize_fourth_demo()
    if args.prepare_fourth:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only required; ledger unchanged.")
        budget.prepare_fourth_demo()
    if args.prepare_third:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only required; ledger unchanged.")
        budget.prepare_third_demo()
    if args.prepare_second:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only required; ledger unchanged.")
        budget.prepare_second_demo()
    if args.prepare:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only required. No allowance changed.")
        budget.prepare_final_demo()
    print(json.dumps({"no_api_requests": True, "launch_authorized": False,
                      "one_time_demo": budget.demo_summary()}, indent=2))


if __name__ == "__main__":
    main()
