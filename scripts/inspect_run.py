"""Local, no-API acceptance inspection of actual exports."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flytbase_bdr.reporting import load_run, json_export, markdown_export
from flytbase_bdr.grounding import iter_claims, audit_mechanical


def inspect(path):
    run = load_run(path)
    unknown_ids = sorted({ref.source_id for s in run.stages for _, c in iter_claims(s.output)
                          for ref in c.evidence if ref.source_id not in run.sources})
    report_path = path.parent / "report.md"
    report_matches = report_path.exists() and report_path.read_text(encoding="utf-8") == markdown_export(run)
    return {"run_id": run.run_id, "mode": run.mode, "status": run.status,
            "all_six_have_output": all(bool(s.output) for s in run.stages),
            "stages": [{"name": s.name, "status": s.status, "origin": s.execution_origin,
                        "warning_count": len(s.warnings), "mechanical_claim_flags": len(audit_mechanical(s.output, run.sources, run.input, run.as_of_date))} for s in run.stages],
            "unknown_source_ids": unknown_ids, "json_roundtrip_matches": json.loads(json_export(run)) == run.model_dump(mode="json"),
            "markdown_matches_record": report_matches,
            "priority": run.stages[0].output.get("priority_score"),
            "completeness_percent": run.stages[0].output.get("qualification_completeness_percent"),
            "email_branches": [d["branch"] for d in run.stages[2].output.get("drafts", [])],
            "case_selected": bool(run.stages[3].output.get("primary")),
            "reported_groq_tokens_this_run": sum(u.get("total_tokens", 0) or 0 for u in run.usage if u.get("provider") == "groq"),
            "reported_tavily_credits_this_run": sum(u.get("credits", 0) or 0 for u in run.usage if u.get("provider") == "tavily"),
            "limitation": "A valid export or successful provider probe does not establish complete factual acceptance."}


if __name__ == "__main__":
    result = inspect(Path(sys.argv[1]))
    print(json.dumps(result, indent=2))
