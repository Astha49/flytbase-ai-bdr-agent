"""Zero-credit review of a saved live workflow; prints concise audit, never modifies run.json."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flytbase_bdr.diagnostics import assess_run, review_markdown
from flytbase_bdr.reporting import load_run


def main():
    parser = argparse.ArgumentParser(description="Read-only acceptance review; no provider requests.")
    parser.add_argument("run", type=Path, help="Path to an existing runs/<id>/run.json")
    parser.add_argument("--output", type=Path, help="Optional Markdown report path (avoid sharing raw run if sensitive)")
    args = parser.parse_args()
    data = assess_run(load_run(args.run))
    report = review_markdown(data)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0 if data["safe_to_claim_full_acceptance"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
