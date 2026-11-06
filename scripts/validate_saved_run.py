"""Validate private saved outputs without providers or editing historical results."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flytbase_bdr.config import ROOT
from flytbase_bdr.reporting import load_run, sanitise
from flytbase_bdr.diagnostics import assess_run, own_company_mentions
from flytbase_bdr.cross_stage import reconcile_existing_customer_evidence
from flytbase_bdr.identity import handoff_identity
from flytbase_bdr.sales_validation import checked_drafts
from flytbase_bdr.grounding import audit_mechanical


def validate(path):
    original = Path(path).read_bytes()
    run = load_run(Path(path))
    preview = run.model_copy(deep=True)
    changed = reconcile_existing_customer_evidence(preview)
    drafts, draft_warnings = checked_drafts(run.stages[2].output, run.sources, run.input, run.as_of_date)
    identity, recovered = handoff_identity(run.stages[5].output)
    q = run.stages[0].output.get("lead", {})
    result = {"mode": "READ_ONLY_SAVED_RUN_VALIDATION", "no_provider_requests": True,
              "run_id": run.run_id, "historical_status": run.status,
              "historical_sha256": hashlib.sha256(original).hexdigest(),
              "stages": [{"name": s.name, "status": s.status, "warnings": len(s.warnings),
                          "technical_status": s.technical_status, "evidence_status": s.evidence_status} for s in run.stages],
              "buyer_context": identity, "buyer_identity_basis": "Original enquiry/qualification; not public identity or authority verification",
              "buyer_fields_recovered_for_display": recovered,
              "handoff_matches_qualification": all(identity.get(k) == q.get(k, "") for k in identity),
              "recorded_relationship_sources": own_company_mentions(run),
              "review": assess_run(run),
              "mechanical_findings": {s.name: audit_mechanical(s.output, run.sources, run.input, run.as_of_date) for s in run.stages},
              "email_branches": [{"branch": d["branch"], "retained_paragraphs": len(d["paragraphs"]),
                                  "hypothetical": d["hypothetical"], "review_status": d.get("review_status")} for d in drafts.get("drafts", [])],
              "email_review_warnings": draft_warnings,
              "local_reconciliation_preview": {"changed_copy": changed,
                  "pending_AI_audit_paths": preview.stages[1].output.get("groundedness", {}).get("unreviewed_claim_paths", []),
                  "note": "Local source check only, not a provider run or AI re-audit. Historical outputs are unchanged."}}
    if Path(path).read_bytes() != original:
        raise RuntimeError("Historical record changed during validation")
    return sanitise(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "saved_run_validation_20261105.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "tmp").resolve()):
        parser.error("Private validation reports must stay under the ignored tmp/ directory.")
    report = validate(args.run)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {report['historical_status']} run {report['run_id']}: read-only validation; zero provider requests.")
    print("Review blockers:", len(report["review"]["blocking_review_items"]))
    print("Private validation report:", output)


if __name__ == "__main__":
    main()
