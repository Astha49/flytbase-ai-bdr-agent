"""Revalidate saved live results after mechanical fixes; no new inference and no invented findings."""
import argparse
import json
from pathlib import Path
from .models import Lead, Materials
from .qualification import qualify
from .normalization import normalize_claims, publication_iso
from .grounding import audit_mechanical
from .selection import select_materials
from .reporting import load_run, save_run
from .config import Settings
from .providers.tavily import TavilyProvider
from .evidence import now


def repair(run, settings, inspect_candidates=False, baseline=None):
    before = run.model_copy(deep=True)
    if inspect_candidates:
        data = run.stages[3].output
        ids = list(dict.fromkeys(c["source_id"] for c in data.get("candidates", []) if c.get("source_id") in run.sources))
        pending = [sid for sid in ids if run.sources[sid].access not in {"inspected_page", "inspected_pdf"}]
        if pending:
            client = TavilyProvider(settings, run)
            try:
                result = client.extract([run.sources[sid].url for sid in pending], "extract:case verification repair")
                extracted = {item.get("url"): item.get("raw_content") or "" for item in result.get("results", [])}
                for sid in pending:
                    source = run.sources[sid]
                    if extracted.get(source.url):
                        text = extracted[source.url]
                        source.text, source.access = text[:settings.max_source_chars], "inspected_page"
                        source.inspection_method = "Tavily Extract during labelled verification repair"
                        source.truncated, source.retrieved_at = len(text) > settings.max_source_chars, now()
                client.refresh_usage()
            finally:
                client.close()
    for source in run.sources.values():
        source.publication_date = publication_iso(source.publication_date)
    for i, stage in enumerate(run.stages):
        if not stage.output:
            continue
        old_data = before.stages[i].output
        old_mechanical = {(f["path"], f["reason"]) for f in audit_mechanical(old_data, before.sources, run.input, run.as_of_date)}
        if baseline:
            old_mechanical.update((f["path"], f["reason"]) for f in audit_mechanical(baseline.stages[i].output, baseline.sources, run.input, run.as_of_date))
        normalize_claims(stage.output, run.sources)
        review = stage.output.get("groundedness")
        if review:
            semantic = [f for f in review["mechanical_and_semantic_findings"]
                        if f.get("origin") == "semantic" or (f.get("origin") != "mechanical" and (f["path"], f["reason"]) not in old_mechanical)]
            mechanical = [{**f, "origin": "mechanical"} for f in audit_mechanical(stage.output, run.sources, run.input, run.as_of_date)]
            review["mechanical_and_semantic_findings"] = mechanical + semantic
            stage.warnings = [w for w in stage.warnings if not w.startswith("Groundedness ")]
            stage.warnings += [f"Groundedness {f['path']}: {f['reason']}" for f in review["mechanical_and_semantic_findings"]]
    if run.stages[0].output:
        result = qualify(Lead.model_validate(run.stages[0].output["lead"]), run.input)
        warnings = result.pop("warnings")
        run.stages[0].output, run.stages[0].warnings = result, warnings
        run.stages[0].status = "partial" if warnings else "complete"
    material = run.stages[3].output
    if material:
        original = Materials.model_validate({k: material[k] for k in ["candidates", "referral_findings", "gaps"]})
        review = material.get("groundedness", {})
        material.update(select_materials(original, run.sources, run.input, run.as_of_date,
                                        review.get("mechanical_and_semantic_findings", [])))
        if material["primary"]:
            run.stages[3].warnings = [w for w in run.stages[3].warnings if not w.startswith("No primary case study")]
        elif not any(w.startswith("No primary case study") for w in run.stages[3].warnings):
            run.stages[3].warnings.append("No primary case study cleared the current evidence and groundedness checks.")
    run.logs.append({"event": "mechanical_revalidation", "at": now(),
                     "changes": "Unknown date sentinels cleared, RFC dates parsed, ellipses expanded only against real source text, scores/relevance recalculated. Semantic findings retained.",
                     "case_page_extraction_attempted": inspect_candidates, "no_new_inference": True})
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--inspect-candidates", action="store_true", help="Explicit live Tavily extraction for uninspected candidate pages; uses shared budget")
    parser.add_argument("--approve-live", action="store_true", help="Required in addition to --inspect-candidates")
    args = parser.parse_args()
    settings = Settings.from_env()
    run = load_run(args.run)
    history = args.run.parent / "history"
    history.mkdir(exist_ok=True)
    backup = history / "before_revalidation.json"
    if not backup.exists():
        backup.write_bytes(args.run.read_bytes())
    if args.inspect_candidates:
        if not args.approve_live:
            parser.error("Live extraction is locked; explicit --approve-live is required.")
        from .execution import approved_live_execution
        with approved_live_execution(True):
            repair(run, settings, True, load_run(backup))
    else:
        repair(run, settings, False, load_run(backup))
    save_run(run, settings.run_path())
    print("Saved labelled revalidation; no new AI synthesis. Run:", run.run_id)


if __name__ == "__main__":
    main()
