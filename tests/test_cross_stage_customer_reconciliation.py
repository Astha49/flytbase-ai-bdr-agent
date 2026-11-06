"""No credentials or API calls. Verify late case-study proof fixes false negatives."""
from flytbase_bdr.config import Settings
from flytbase_bdr.cross_stage import reconcile_existing_customer_evidence
from flytbase_bdr.models import Source
from flytbase_bdr.workflow import new_run
from flytbase_bdr.story_discovery import story_links_from_html
from flytbase_bdr.grounding import check_claim
from flytbase_bdr.models import Claim


def sample_run():
    run = new_run('From: Buyer One (buyer@example.test)\nCompany: Test Company (TCOMP), Chile\n'
                  'Subject: autonomous drone inspection of three new sites', Settings(), mode='offline_test')
    run.stages[0].output = {'lead': {'company': 'Test Company (TCOMP)'}}
    run.stages[1].status = 'partial'
    run.stages[1].warnings = [
        'Corporate changes and customer relationships: There is no public evidence of a TCOMP/FlytBase partnership.',
        'Budget and investment signals: no verified findings.',
    ]
    run.stages[1].output = {'topics': [
        {'name': 'Organisation and reporting lines', 'claims': [], 'gaps': ['Reporting line unavailable.']},
        {'name': 'Corporate changes and customer relationships', 'claims': [],
         'gaps': ['No public evidence of an existing partnership or contract between TCOMP and FlytBase.']},
    ], 'groundedness': {'semantic_review': 'performed', 'mechanical_and_semantic_findings': []}}
    run.stages[3].output = {'primary': {'candidate': {'source_id': 'S_valid'}}}
    run.sources['S_valid'] = Source(
        source_id='S_valid', url='https://flytbase.com/case-studies/tcomp-demonstration',
        title='How TCOMP implemented automated inspections',
        retrieved_at=run.started_at, access='inspected_page',
        text='TCOMP partnered with Adentu and FlytBase to automate inspection of processing equipment. ' * 3,
    )
    return run


def test_cross_stage_reconciliation_is_source_checked_and_idempotent():
    run = sample_run()
    assert reconcile_existing_customer_evidence(run)
    relationship = run.stages[1].output['topics'][1]
    assert len(relationship['claims']) == 1
    claim = Claim.model_validate(relationship['claims'][0])
    assert not check_claim(claim, run.sources, run.input, run.as_of_date)
    assert claim.evidence[0].source_id == 'S_valid'
    assert 'company-level collaboration' in claim.text
    assert not any('no public evidence' in str(x).casefold() for x in relationship['gaps'])
    assert not any('no public evidence' in w.casefold() for w in run.stages[1].warnings)
    assert run.stages[1].status == 'partial'  # unrelated financial gap not erased
    assert run.logs and run.logs[-1]['event'] == 'cross_stage_customer_evidence_reconciled'
    assert not reconcile_existing_customer_evidence(run)  # no duplicates


def test_uninspected_or_unrelated_story_never_reconciles():
    run = sample_run()
    run.sources['S_valid'].access = 'search_summary_only'
    assert not reconcile_existing_customer_evidence(run)
    run.sources['S_valid'].access = 'inspected_page'
    run.sources['S_valid'].title = 'Unrelated company case'
    run.sources['S_valid'].url = 'https://flytbase.com/case-studies/unrelated-company'
    assert not reconcile_existing_customer_evidence(run)


def test_first_party_directory_selection_changes_with_buyer_input():
    html = '''<a href="/case-studies/tcomp-mining">TCOMP mining inspection in Chile</a>
              <a href="/case-studies/anglo-peru">Anglo American mine survey in Peru</a>
              <a href="/case-studies/harbour">Harbour port security</a>'''
    mine = {'company': 'Test Company (TCOMP)', 'referral': 'Anglo American',
            'industry': 'mining', 'need': 'autonomous inspection'}
    port = {'company': 'Harbour Inc', 'referral': '', 'industry': 'ports', 'need': 'port security'}
    assert story_links_from_html(html, mine)[0]['url'].endswith('tcomp-mining')
    assert story_links_from_html(html, port)[0]['url'].endswith('harbour')


def test_runtime_does_not_call_archived_case_url_hints():
    from pathlib import Path
    import flytbase_bdr.workflow as wf
    text = Path(wf.__file__).read_text(encoding='utf-8')
    assert 'candidate_story_hints' not in text
    assert 'public_case_references' not in text
