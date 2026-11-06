"""Inspect local six-stage run readiness without calling an AI or search provider.

Usage: python scripts/acceptance_preflight.py [--json] [--run path/to/run.json]
Reads private saved state and project ledger. Does not write to run.json, start the
Streamlit app, search Tavily, or call Groq. Never prints key values.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Make `python scripts/acceptance_preflight.py` work from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import Settings, credential_status
from flytbase_bdr.diagnostics import assess_run
from flytbase_bdr.readiness import check_requirements
from flytbase_bdr.reporting import load_run


def report(saved: Path | None = None):
    settings = Settings.from_env()
    budget = ProjectBudget(settings).summary()
    result = {
        'kind': 'READ_ONLY_LOCAL_PREFLIGHT',
        'no_provider_requests': True,
        'keys_present_only': credential_status(),
        'project_budget_not_provider_quota': budget,
        'recorded_run_path': None,
        'recorded_run': None,
        'assignment_checks': None,
        'blocking_review_items': [],
        'deliverables': {
            'inspectable_source': 'included locally; Git/repo access must be supplied by the user',
            'live_run_output': 'not verified',
            'walkthrough_video_8_to_12_minutes': 'not supplied; record separately',
        },
    }
    files = sorted(settings.run_path().glob('*/run.json'), reverse=True)
    selected = saved or (files[0] if files else None)
    if selected is None or not selected.exists():
        result['blocking_review_items'] = ['No local saved run found. Copy the original private runs/ folder without resetting its ledger.']
        return result
    run = load_run(selected)
    review = assess_run(run)
    result['recorded_run_path'] = str(selected)
    result['recorded_run'] = {
        'id': run.run_id, 'mode': run.mode, 'status': run.status, 'as_of_date': run.as_of_date,
        'stage_statuses': [
            {'stage': i, 'name': s.name, 'status': s.status,
             'technical': s.technical_status, 'evidence': s.evidence_status,
             'warnings': len(s.warnings), 'has_output': bool(s.output)}
            for i, s in enumerate(run.stages, 1)
        ],
        'usage_entries': {'groq': sum(x.get('provider') == 'groq' for x in run.usage),
                          'tavily': sum(x.get('provider') == 'tavily' for x in run.usage)},
    }
    result['assignment_checks'] = check_requirements(run)
    result['blocking_review_items'] = review['blocking_review_items']
    if run.mode == 'live' and all(s.output for s in run.stages):
        result['deliverables']['live_run_output'] = 'live checkpoint exists; inspect review blockers before submission'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print complete sanitized report as JSON')
    parser.add_argument('--run', type=Path, help='Inspect a specific run.json instead of the latest')
    args = parser.parse_args()
    data = report(args.run)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    print('FLYTBASE ASSIGNMENT — LOCAL ACCEPTANCE PREFLIGHT (zero API calls)')
    print('Provider keys present:', ', '.join(f'{k}={"yes" if v else "no"}'
                                           for k, v in data['keys_present_only'].items()))
    for provider, item in data['project_budget_not_provider_quota'].items():
        print(f'{provider.upper()} application remaining: {item["remaining_for_reservation"]:,}; '
              'NOT a real-time provider balance')
    print('Saved run:', data['recorded_run_path'] or 'not found')
    run = data['recorded_run']
    if run:
        print('Recorded status:', run['status'], '| mode:', run['mode'])
        for s in run['stage_statuses']:
            print(f'  {s["stage"]}. {s["name"]}: {s["status"]} '
                  f'({s["warnings"]} warnings; has output: {s["has_output"]})')
    print('Blocking review items:', len(data['blocking_review_items']))
    for warning in data['blocking_review_items'][:15]:
        print('  -', warning)
    if len(data['blocking_review_items']) > 15:
        print(f'  ... {len(data["blocking_review_items"])-15} more; use --json')
    print('Reminder: repository access and a real 8-12 minute video are separate deliverables.')


if __name__ == '__main__':
    main()
