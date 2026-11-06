"""Offline preview of the enquiry-only safe email recovery; does NOT mutate saved runs.

Usage: python scripts/preview_safe_email_recovery.py runs/<id>/run.json
"""
import argparse
import json
from pathlib import Path

from flytbase_bdr.safe_email_recovery import generate_safe_drafts


def main():
    parser = argparse.ArgumentParser(description="Preview local non-provider recovery copy from a recorded run")
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tmp/safe_email_recovery_preview.md"))
    args = parser.parse_args()
    saved = json.loads(args.run.read_text(encoding="utf-8"))
    stages = saved.get("stages", [])
    if len(stages) < 3:
        raise SystemExit("Saved run lacks a recorded email stage; no preview created.")
    qualification = stages[0].get("output") or {}
    response = stages[2].get("output") or {}
    revised, recovered = generate_safe_drafts(saved.get("input", ""), qualification.get("lead") or {},
                                               response, {}, saved.get("as_of_date", "2026-11-05"))
    text = ["# Evidence-safe email recovery — OFFLINE PREVIEW", "",
            "This is NOT a new provider run, a semantic audit, or an official accepted result.",
            "The original JSON remains unchanged. Source-limited copy requires sales review before sending.", "",
            f"Saved run: `{saved.get('run_id', '')}`", f"Locally recovered branches: {', '.join(recovered) or 'none'}", ""]
    for draft in revised.get("drafts", []):
        text.extend([f"## {draft['branch']}", f"**Subject:** {draft['subject']}", "",
                     *[p['text'] + "\n" for p in draft.get('paragraphs', [])],
                     f"Draft basis: {draft.get('review_status', '')}", ""])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(text), encoding="utf-8")
    print(f"Offline preview saved: {args.output}. No API requests. Original run unchanged.")


if __name__ == "__main__":
    main()
