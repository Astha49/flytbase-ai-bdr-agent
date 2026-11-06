"""Offline-only diagnostics never emit credentials or buyer text."""
from pathlib import Path
import importlib.util
import json


def _inspect_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'inspect_latest_run.py'
    spec = importlib.util.spec_from_file_location('inspect_latest_run', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_summary_is_safe_and_explains_incomplete_stages():
    mod = _inspect_module()
    data = {'run_id': 'abc', 'mode': 'live', 'status': 'running',
            'stages': [{'status': 'complete', 'output': {'lead': {'email': 'secret@example.com'}},
                        'warnings': ['API token SECRET_123456'], 'technical_status': 'succeeded',
                        'evidence_status': 'supported'},
                       {'status': 'pending', 'output': {}, 'warnings': []}],
            'logs': [{'event': 'stage_error', 'stage': 'Research', 'type': 'ValueError',
                      'message': 'API token SECRET_123456'}],
            'usage': [{'provider': 'groq', 'api_key': 'SECRET_123456'}]}
    output = mod.summarize(data)
    assert 'Qualification: complete' in output
    assert 'Deep Account Research: pending' in output
    assert 'SECRET_123456' not in output
    assert 'secret@example.com' not in output
    assert 'Groq=1' in output


def test_latest_selection_and_safe_run_id(tmp_path):
    mod = _inspect_module()
    for name in ['a', 'b']:
        folder = tmp_path / name
        folder.mkdir()
        (folder / 'run.json').write_text(json.dumps({'run_id': name}))
    assert mod.select_run(tmp_path).parent.name == 'b'
    assert mod.select_run(tmp_path, 'a').parent.name == 'a'
    try:
        mod.select_run(tmp_path, '../secret')
    except ValueError:
        pass
    else:
        raise AssertionError('Path traversal should have been rejected')
