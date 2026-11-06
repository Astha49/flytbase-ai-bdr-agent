"""Preview evidence-driven case/partner recovery without API calls or edits.

This is NOT a live run and is NOT a replacement for FlytBase's required output.
It only checks what an existing run's inspected documents can substantiate.
"""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flytbase_bdr.reporting import load_run
from flytbase_bdr.evidence_decisions import material_proposals, route_proposal
from flytbase_bdr.selection import select_materials, decide_routing
from flytbase_bdr.grounding import audit_mechanical


def preview(path: Path) -> str:
    run = load_run(path)
    source_ids = list(run.sources)
    materials = material_proposals(run, source_ids)
    material_errors = audit_mechanical(materials.model_dump(), run.sources, run.input, run.as_of_date)
    chosen = select_materials(materials, run.sources, run.input, run.as_of_date, material_errors)
    routing = route_proposal(run, source_ids)
    route_errors = audit_mechanical(routing.model_dump(), run.sources, run.input, run.as_of_date)
    lead = run.stages[0].output.get('lead', {})
    route = decide_routing(routing, run.sources, run.input, run.as_of_date, lead.get('geography', ''), route_errors)
    lines = [f"# Offline evidence preview — {run.run_id}", "",
             "NOT a new live execution. No original result was modified. No API usage.",
             "This preview does not replace Groq semantic review, fresh search, or the required recorded live run.", "",
             "## Case-study evidence"]
    card = chosen.get('primary')
    if card:
        candidate = card['candidate']
        lines += [f"- Evidence-based candidate: **{candidate['title']}**", f"- Source ID: {candidate['source_id']}",
                  f"- Original: {run.sources[candidate['source_id']].url}", f"- Match score (not purchase probability): {card['score']}/100"]
    else:
        lines.append("- No eligible inspected /case-studies/ article available in this saved run. Refresh case-study search.")
    lines += ["", "## Local deployment evidence"]
    if route.get('candidates'):
        for c in route['candidates']:
            lines.append(f"- Possible local integrator: {c['name']} (availability not established)")
    else:
        lines.append("- No local integrator name cleared the available document patterns; keep AE-led discovery and verify partners.")
    lines += ["", "## Next safe action", "- Fix/re-run only missing research groups; do not increase limits or call providers automatically."]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path, help='Path to existing run.json; no API calls')
    print(preview(parser.parse_args().run))
