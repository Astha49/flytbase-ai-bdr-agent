"""Offline regressions for the reviewer experience and explicitly approved free allowance."""
import json
from pathlib import Path
import pytest
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import Settings, ROOT
from flytbase_bdr.evidence import derive_queries
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.models import Lead
from flytbase_bdr.provider import QuotaExhausted
from conftest import make_lead


def test_authorized_ceiling_preserves_usage_and_has_separate_phase_guards(tmp_path):
    settings = Settings(runs_dir=str(tmp_path))
    budget = ProjectBudget(settings)
    budget.reserve("groq", 38241, "historical saved reservations")
    old_record = json.loads(budget.path.read_text())['entries'][0]
    settings.project_max_groq_tokens = 110000
    reply = budget.authorize_groq_ceiling(110000)
    assert reply['changed'] and reply['new_ceiling'] == 110000
    assert json.loads(budget.path.read_text())['entries'][0] == old_record
    assert (tmp_path / 'project_budget.before_110k.json').exists()
    assert budget.summary()['groq']['repair_remaining'] == 26000
    assert budget.summary()['groq']['emergency_reserve'] == 7759
    # The default phase cannot borrow demo or emergency tokens.
    budget.reserve('groq', 26000, 'repair budget')
    with pytest.raises(QuotaExhausted):
        budget.reserve('groq', 1, 'repair should not touch demo reserve')
    # Recording allocation requires an explicit, separate phase approval.
    with approved_live_execution(True, phase='demo'):
        budget.reserve('groq', 38000, 'fresh recorded demonstration')
        with pytest.raises(QuotaExhausted):
            budget.reserve('groq', 1, 'emergency cannot be spent')
    assert budget.summary()['groq']['remaining_for_reservation'] == 7759
    assert budget.authorize_groq_ceiling(110000)['changed'] is False


def test_upgraded_project_rejects_other_ceiling_and_leaves_ledger_unchanged(tmp_path):
    settings = Settings(runs_dir=str(tmp_path))
    budget = ProjectBudget(settings)
    budget.reserve("groq", 1, "historical test entry")
    before = budget.path.read_bytes()
    with pytest.raises(ValueError):
        budget.authorize_groq_ceiling(180000)
    assert budget.path.read_bytes() == before


def test_flytbase_ecosystem_search_uses_real_directory_and_input_only(enquiry):
    lead = make_lead(enquiry)
    queries = derive_queries(lead, '2026-11-04')
    assert len(queries['partners']) == 2
    assert '/partner ' in queries['partners'][0]
    assert 'Chile' in queries['partners'][0]
    assert 'Anglo American' in queries['materials'][1]
    lead.company, lead.domain, lead.referral = 'Example Solar', 'solar.example', 'Solar Enterprise'
    lead.need = 'Solar asset inspections with drones'
    changed = derive_queries(lead, '2026-11-04')
    assert 'SQM' not in str(changed)
    assert 'Anglo American' not in str(changed)
    assert 'Solar Enterprise' in str(changed)


def test_source_bundle_exposes_synthetic_demo_not_private_run():
    import json
    demo = json.loads((ROOT / 'examples/recruiter_demo/offline_simulation/run.json').read_text(encoding='utf-8'))
    assert demo['mode'] == 'offline_test' and not demo['usage']
    assert 'SYNTHETIC OFFLINE SIMULATION' in str(demo['warnings'])
    guide = (ROOT / 'docs/REVIEWER_GUIDE.md').read_text(encoding='utf-8')
    assert 'fictional' in guide and 'No repaired complete live acceptance is claimed' in guide
    css = (ROOT / 'assets' / 'theme.css').read_text(encoding='utf-8')
    assert 'prefers-reduced-motion' in css
    assert 'fb-tasks-grid' in css


def test_compact_evidence_prefers_reported_financial_number_over_generic_headings():
    from flytbase_bdr.compact import evidence_batch
    from flytbase_bdr.models import Source
    src = Source(source_id='S_f', url='https://public.example/investor-report', title='Example report',
                 retrieved_at='2026-11-04', access='inspected_page',
                 text=('Generic company information about operations. ' * 120) +
                      'Capital expenditures for 2025 reached USD 876.7 million for the entire company. ' +
                      ('Other unrelated marketing text. ' * 120),
                 queries=['official 2025 capital expenditures investment plan'])
    payload = evidence_batch({'S_f': src}, ['S_f'], Settings())
    assert '876.7 million' in payload['S_f']['text']
    assert 'context_is_excerpt' in payload['S_f']
