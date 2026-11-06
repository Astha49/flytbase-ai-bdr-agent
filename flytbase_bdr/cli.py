import argparse
from pathlib import Path
from .config import ROOT, Settings, has_api_key, credential_status
from .models import STAGE_NAMES
from .reporting import load_run
from .workflow import Workflow


def main():
    parser = argparse.ArgumentParser(description="FlytBase inbound workflow. Groq/Tavily free plans only; no paid fallback.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", type=Path, help="UTF-8 enquiry text file")
    group.add_argument("--example", action="store_true", help="Use supplied assignment enquiry")
    group.add_argument("--replay", type=Path, help="Read a saved run.json; no API calls")
    group.add_argument("--resume", type=Path, help="Resume failed stages; reuse saved successful stages and research with labels")
    group.add_argument("--plan-resume", type=Path, help="Preview chosen re-run stages and local allowance without API calls")
    parser.add_argument("--rerun-stage", type=int, action="append", choices=range(1, 7), help="With --resume, rerun this stage and affected downstream outputs")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--budget-status", action="store_true", help="Show local saved project allowance, no API calls")
    parser.add_argument("--set-groq-project-ceiling", type=int, metavar="TOKENS", help="Audited local-only migration to explicitly approved 110000 ceiling")
    parser.add_argument("--confirm-free-only", action="store_true", help="Required with --set-groq-project-ceiling; does not enable provider billing")
    parser.add_argument("--demo-phase", action="store_true", help="Explicitly use the separately protected fresh-recording envelope, only for a fresh live run")
    parser.add_argument("--review-run", type=Path, help="Offline requirement checklist for a saved run, no API calls")
    parser.add_argument("--approve-live", action="store_true", help="Explicitly permit provider requests for this command; project ceilings still apply")
    parser.add_argument("--refresh-research", action="append", choices=["organisation", "finance", "current", "materials", "partners"],
                        help="With an approved resume, refresh only this research group; other inspected research is reused")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.set_groq_project_ceiling is not None:
        if not args.confirm_free_only:
            parser.error("--confirm-free-only is required; no limits changed.")
        if args.set_groq_project_ceiling != 110000:
            parser.error("Only the expressly approved 110000-token ceiling is supported.")
        from .budget import ProjectBudget
        # The environment setting and ledger must be updated together. Never
        # print API key values or rewrite unrelated entries in the .env file.
        dotenv_path = ROOT / ".env"
        if not dotenv_path.exists():
            parser.error("Local .env is missing. Preserve credentials and create it first; no ledger changed.")
        text_before = dotenv_path.read_text(encoding="utf-8")
        import re
        pattern = r"(?m)^PROJECT_MAX_GROQ_TOKENS\s*=.*$"
        update = "PROJECT_MAX_GROQ_TOKENS=110000"
        text_after = (re.sub(pattern, update, text_before) if re.search(pattern, text_before)
                      else text_before.rstrip("\n") + "\n" + update + "\n")
        # Set configuration first: reserve() uses the minimum of configured and
        # persisted ceilings. The only change to .env is this one named setting.
        dotenv_path.write_text(text_after, encoding="utf-8")
        try:
            settings.project_max_groq_tokens = 110000
            result = ProjectBudget(settings).authorize_groq_ceiling(110000)
        except Exception:
            dotenv_path.write_text(text_before, encoding="utf-8")
            raise
        print("Approved local project cap:", result["new_ceiling"], "changed:", result["changed"])
        print("Repair limit and demo/emergency reserves protected; historical entries unchanged. No API calls.")
        return 0
    if args.budget_status:
        from .budget import ProjectBudget
        data = ProjectBudget(settings).summary()
        for name, record in data.items():
            print(f"{name.upper()} saved PROJECT ceiling: {record['ceiling']:,}")
            print(f"  Reported: {record['actual_reported']:,}; unknown/reserved: {record['reserved_usage_unavailable']:,}")
            print(f"  Available for app reservations: {record['remaining_for_reservation']:,}")
        if data["groq"].get("repair_remaining") is not None:
            print("Groq repair-phase remaining:", f"{data['groq']['repair_remaining']:,}")
            print("Groq demo reserve at approval:", f"{data['groq']['demo_reserve_at_approval']:,}")
            print("Groq emergency allowance protected:", f"{data['groq']['emergency_reserve']:,}")
        print("These are the application's saved limits, NOT your provider's live free-plan quota.")
        print("No keys, API requests, credits or live messages were used.")
        return 0
    if args.review_run:
        from .diagnostics import assess_run
        from .readiness import check_requirements
        saved = load_run(args.review_run)
        print(f"Saved {saved.mode} run {saved.run_id}: {saved.status}; no API calls")
        for item in check_requirements(saved):
            print(f"{item['name']}: {item['state']}\n  {item['details']}\n  Next: {item['next']}")
        issues = assess_run(saved)["blocking_review_items"]
        if issues:
            print("Remaining verification warnings:")
            for issue in issues:
                print(" -", issue)
        return 0
    if args.plan_resume:
        import json
        from .planning import plan_resume, submission_resources
        original = load_run(args.plan_resume)
        requested = {number - 1 for number in args.rerun_stage or []}
        print(json.dumps({"targeted_resume": plan_resume(original, settings, requested, args.refresh_research or []),
                          "submission_resource_estimates": submission_resources(original, settings)}, indent=2))
        return 0
    if args.check_config:
        print("Credential presence:", credential_status())
        print("Groq model:", settings.groq_model)
        print("Tavily basic Search/Extract. Provider access is verified only by live probes.")
        print("Use --budget-status to inspect the separate local project ceilings; no live balance is implied.")
        return 0
    if args.demo_phase and (args.resume or args.plan_resume or args.replay):
        parser.error("Demo phase is only for a FRESH live run; never a targeted repair or replay.")
    if args.replay:
        run = load_run(args.replay)
        print(f"REPLAY — saved {run.mode} run {run.run_id}; original status {run.status}; no API calls.")
    else:
        if not args.approve_live:
            parser.error("Live execution is locked. Use --plan-resume first. --approve-live is required for any new provider execution.")
        if not args.input and not args.example and not args.resume:
            parser.error("Choose --input enquiry.txt, --example, --replay run.json or --check-config.")
        saved = load_run(args.resume) if args.resume else None
        if saved:
            from .planning import plan_resume
            plan = plan_resume(saved, settings, {n - 1 for n in args.rerun_stage or []}, args.refresh_research or [])
            if not plan["budget_feasible"]:
                parser.error("Saved project allowance cannot cover this plan. No request sent and no limit changed; inspect --plan-resume.")
            from .workflow import fork_resume
            saved = fork_resume(saved, settings)
        path = args.input if args.input else ROOT / "examples" / "enquiry.txt"
        enquiry = saved.input if saved else path.read_text(encoding="utf-8")
        previous = {}
        def progress(run):
            for s in run.stages:
                if previous.get(s.name) != s.status:
                    print(f"{s.name}: {s.status}", flush=True)
                    previous[s.name] = s.status
        print("LIVE — executing Groq/Tavily within saved project ceilings. No paid fallback.")
        from .execution import approved_live_execution
        with approved_live_execution(args.approve_live, phase="demo" if args.demo_phase else "repair"):
            run = Workflow(settings).execute(enquiry, on_update=progress, resume=saved,
                                             rerun_stages=[n - 1 for n in args.rerun_stage or []],
                                             refresh_research=args.refresh_research or [])
    print(f"Run {run.run_id}: {run.status}")
    if run.mode == "offline_test":
        print("SYNTHETIC OFFLINE TEST: not live research or submission acceptance evidence.")
    for stage in run.stages:
        for warning in stage.warnings:
            print(f"  {stage.name}: {warning}")
    print("Results:", args.replay.resolve().parent if args.replay else settings.run_path() / run.run_id)
    return 0 if run.status == "complete" else 1 if run.status == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
