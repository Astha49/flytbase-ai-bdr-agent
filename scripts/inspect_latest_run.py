r"""Safely summarize the latest saved workflow checkpoint without provider calls.

Usage (from the project root):
    .\.venv\Scripts\python.exe scripts\inspect_latest_run.py
    .\.venv\Scripts\python.exe scripts\inspect_latest_run.py --run-id 20261104T..._

Only prints stage states and event types, never API keys, messages or source text.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
STAGE_NAMES = (
    "Qualification", "Deep Account Research", "Response Generation",
    "Case Study and Material Matching", "Partner Identification", "AE Handoff Summary",
)


def select_run(folder: Path, run_id: str | None = None) -> Path:
    if run_id:
        # Never allow an untrusted path to escape the configured run folder.
        if "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
            raise ValueError("A run ID must be a folder name, not a path.")
        path = folder / run_id / "run.json"
        if not path.is_file():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return path
    saved = list(folder.glob("*/run.json")) if folder.is_dir() else []
    if not saved:
        raise FileNotFoundError("No saved workflow checkpoint exists yet in the runs folder.")
    return sorted(saved, key=lambda p: p.parent.name)[-1]


def summarize(run: dict) -> str:
    lines = [
        f"Run ID: {str(run.get('run_id', 'unknown'))[:90]}",
        f"Mode: {run.get('mode', 'unknown')} | Overall: {run.get('status', 'unknown')}",
        f"Started: {run.get('started_at', 'unknown')} | Finished: {run.get('finished_at') or 'not yet'}",
    ]
    stages = run.get("stages", [])
    for i, stage in enumerate(stages[:6]):
        # Fixed labels prevent customer content being emitted to the terminal.
        name = STAGE_NAMES[i]
        output = stage.get("output") or {}
        lines.append(f"{i+1}. {name}: {stage.get('status', 'unknown')} | "
                     f"technical={stage.get('technical_status', 'unknown')} | "
                     f"evidence={stage.get('evidence_status', 'unknown')} | "
                     f"output={'yes' if bool(output) else 'no'} | "
                     f"warnings={len(stage.get('warnings') or [])}")
    errors = [ev for ev in run.get("logs", []) if ev.get("event") == "stage_error"]
    if errors:
        lines.append("Recorded stage errors (types only):")
        for err in errors[-6:]:
            # No exception bodies, buyer information, or credentials.
            lines.append(f"  stage={str(err.get('stage','unknown'))[:65]} | type={str(err.get('type','unknown'))[:55]}")
    groq = [u for u in run.get("usage", []) if u.get("provider") == "groq"]
    tavily = [u for u in run.get("usage", []) if u.get("provider") == "tavily"]
    lines.append(f"Recorded provider usage entries: Groq={len(groq)}, Tavily={len(tavily)}")
    lines.append("This is a saved checkpoint only; no provider request was made by this inspection.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="Optional exact saved run folder name")
    args = parser.parse_args()
    configured = os.environ.get("RUNS_DIR", "runs")
    folder = Path(configured)
    if not folder.is_absolute():
        folder = DEFAULT_ROOT / folder
    try:
        path = select_run(folder, args.run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        print(summarize(data))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not inspect run: {type(exc).__name__}. Check runs directory and run ID.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
