"""Read-only planning. Ranges are engineering estimates, never provider balances."""
import math
from .evidence import derive_queries
from .models import Lead
from .budget import ProjectBudget

# Input+output including a concise audit; estimates based on saved workload and
# compact synthesis, not measurements of the unexecuted repaired application.
TOKEN_RANGES = {0: (1000, 2500), 1: (4000, 8000), 2: (2200, 5000),
                3: (3500, 7500), 4: (2500, 6000), 5: (0, 0)}
GROUPS = {0: [], 1: ["organisation", "finance", "current"], 2: [], 3: ["materials"], 4: ["partners"], 5: []}


def affected_stages(run, requested=()):
    stages = set(requested)
    stages.update(i for i, s in enumerate(run.stages) if s.status in {"failed", "skipped", "pending"})
    if 0 in stages:
        return set(range(6))
    if stages & {1, 3, 4}:
        stages.update({2, 5})
    if 2 in stages:
        stages.add(5)
    return stages


def plan_resume(run, settings, requested=(), refresh=()):
    requested = set(requested) | {i for i, groups in GROUPS.items() if set(groups) & set(refresh)}
    stages = affected_stages(run, requested)
    queries = derive_queries(Lead.model_validate(run.stages[0].output["lead"]), run.as_of_date) if run.stages[0].output.get("lead") else run.queries
    groups = set(g for i in stages for g in GROUPS[i])
    fresh = [g for g in groups if g in set(refresh) or g not in run.retrieval_cache]
    searches = sum(len(queries.get(g, [])) for g in fresh)
    credits = min(settings.max_search_requests, searches) + min(settings.max_extract_requests, len(fresh))
    low = sum(TOKEN_RANGES[i][0] for i in stages)
    high = sum(TOKEN_RANGES[i][1] for i in stages)
    allowance = ProjectBudget(settings).summary()
    repair_available = allowance["groq"].get("repair_remaining", allowance["groq"]["remaining_for_reservation"])
    return {"run_id": run.run_id, "execution_authorized": False, "mode": "offline plan; no requests or saved-result edits",
            "rerun_stages": [{"number": i + 1, "name": run.stages[i].name} for i in sorted(stages)],
            "reuse_stages": [s.name for i, s in enumerate(run.stages) if i not in stages],
            "cached_research_groups": sorted(groups - set(fresh)), "fresh_research_groups": sorted(fresh),
            "groq_tokens_estimated": {"lower": low, "upper": high, "retry_reserve_upper": high * (1 + settings.max_retries)},
            "tavily_credits_reserved_estimate": {"without_retries": credits, "with_retries_upper": min(settings.max_tavily_credits, credits * (1 + settings.max_retries))},
            "project_allowance": allowance,
            "budget_feasible": low <= repair_available and credits <= allowance["tavily"]["remaining_for_reservation"],
            "repair_phase_available": repair_available,
            "limits": "Ranges include generation and audits, not measured future usage. Account quotas are unverified. Request/project guards remain binding; no ceiling is changed."}


def submission_resources(run, settings):
    low, high = sum(v[0] for v in TOKEN_RANGES.values()), sum(v[1] for v in TOKEN_RANGES.values())
    repair = plan_resume(run, settings, {1, 2, 3, 4, 5}, {"organisation", "finance"})
    return {"current_allowance": repair["project_allowance"], "estimates_only": True,
            "continuation_and_recording_allocation": continuation_and_recording_allocation(run, settings),
            "scenarios": [
                {"purpose": "Targeted final verification using caches", "groq_tokens": repair["groq_tokens_estimated"], "tavily_credits": repair["tavily_credits_reserved_estimate"]},
                {"purpose": "One genuine fresh recorded demonstration", "groq_tokens": {"lower": low, "upper": high}, "tavily_credits": {"lower": 10, "upper": 15}},
                {"purpose": "One optional fresh evaluator run", "groq_tokens": {"lower": low, "upper": high}, "tavily_credits": {"lower": 10, "upper": 15}},
                {"purpose": "Read-only saved demonstration", "groq_tokens": {"lower": 0, "upper": 0}, "tavily_credits": {"lower": 0, "upper": 0}}],
            "decision": "No new limits proposed or enabled. Existing allowance does not cover reliable repaired verification plus fresh recording/evaluator runs. Explicit approval and sufficient project allowance are required."}


def continuation_and_recording_allocation(run, settings):
    """Minimum planning estimate, never a guarantee or a ceiling change.

    Safety reserve is the larger of 20% of the two workloads or one configured
    maximum-size request. The lower bound is optimistic; the upper estimate is
    more prudent and still does not reserve every possible retry.
    """
    repair = plan_resume(run, settings, {1, 2, 3, 4, 5}, {"organisation", "finance"})
    fresh = {"lower": sum(v[0] for v in TOKEN_RANGES.values()),
             "upper": sum(v[1] for v in TOKEN_RANGES.values())}
    groq = repair["project_allowance"]["groq"]
    emergency = groq.get("emergency_reserve", 0)
    available = max(0, groq["remaining_for_reservation"] - emergency)
    scenarios = {}
    for bound in ("lower", "upper"):
        workload = repair["groq_tokens_estimated"][bound] + fresh[bound]
        reserve = max(math.ceil(workload * .20), settings.max_request_tokens)
        scenarios[bound] = {"workload_tokens": workload, "safety_reserve_tokens": reserve,
                            "required_headroom_tokens": workload + reserve,
                            "additional_allowance_tokens": max(0, workload + reserve - available)}
    return {"purpose": "One targeted live continuation plus one fresh recorded demonstration; optional evaluator excluded",
            "estimates_only": True, "authorization": False, "available_application_tokens": available,
            "emergency_tokens_excluded": emergency,
            "repair_phase_available": repair["repair_phase_available"],
            "reserve_rule": "max(20% of combined workload, one maximum-size configured request)",
            **scenarios,
            "limitation": "No finite estimate guarantees successful live research. Emergency tokens are excluded; repair/demo phase guards still apply independently. Does not reserve every possible retry; provider quotas and source quality remain unverified. No ceiling or usage record is changed."}
