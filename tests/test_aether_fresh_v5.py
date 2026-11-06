"""New-enquiry budget and provider reservations, all offline (zero API calls)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from flytbase_bdr.config import Settings
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.provider import QuotaExhausted
from flytbase_bdr.run_allowance import remaining, reserve_entry
from aether_live import approve_enquiry, fingerprint, stamp


def prepared(tmp):
    settings=Settings().model_copy(update={'runs_dir':str(tmp/'runs')})
    ledger=ProjectBudget(settings)
    ledger.path.parent.mkdir(parents=True,exist_ok=True)
    ledger.write({'created_at':stamp().isoformat(),
                  'ceilings':{'groq':110000,'tavily':40},
                  'phase_limits':{'emergency_reserve':7759,'demo_reserve_at_approval':38000},
                  'entries':[], 'execution_allowances':[]})
    return settings,ledger


def test_approval_never_sends_requests_or_changes_existing_history(tmp_path):
    settings,ledger=prepared(tmp_path)
    message='From: buyer@company.com\nCompany: Another enterprise\nLooking for autonomous drone inspections.'
    item=approve_enquiry(settings,message,35000,42000,12,free_only=True,approved_budget=True)
    saved=ledger.read()
    assert saved['entries']==[]
    assert item['kind']=='fresh_enquiry' and item['state']=='approved'
    assert item['enquiry_sha256']==fingerprint(message)
    assert item['tavily_credits']==12
    with pytest.raises(Exception):
        approve_enquiry(settings,message,35000,42000,12,free_only=True,approved_budget=True)


def test_token_guard_preserves_emergency_demo_headroom(tmp_path):
    settings,ledger=prepared(tmp_path)
    with pytest.raises(QuotaExhausted):
        approve_enquiry(settings,'Company: Test',130000,42000,12,free_only=True,approved_budget=True)
    assert ledger.read()['execution_allowances']==[]


def test_fresh_allowance_accounts_for_groq_and_tavily_separately(tmp_path):
    settings,ledger=prepared(tmp_path)
    item=approve_enquiry(settings,'New enquiry from another buyer',25000,42000,12,free_only=True,approved_budget=True)
    with ledger.locked():
        data=ledger.read()
        data['execution_allowances'][0].update({'state':'started','run_id':'actual-fresh-run'})
        reserve_entry(data,'groq',7500,'buyer extraction','actual-fresh-run',item['id'])
        reserve_entry(data,'tavily',2,'search','actual-fresh-run',item['id'])
        assert remaining(data,data['execution_allowances'][0])==34500
        with pytest.raises(QuotaExhausted):
            reserve_entry(data,'tavily',11,'search','actual-fresh-run',item['id'])
        ledger.write(data)
    assert len(ledger.read()['entries'])==2
    assert sorted(e['provider'] for e in ledger.read()['entries'])==['groq','tavily']


def test_input_bound_by_hash(tmp_path):
    settings,ledger=prepared(tmp_path)
    item=approve_enquiry(settings,'From: A\nCompany: One',26000,18000,8,free_only=True,approved_budget=True)
    assert item['enquiry_sha256'] != fingerprint('From: B\nCompany: Two')


def test_new_analysis_page_contains_real_intake_not_external_link(tmp_path, monkeypatch):
    import runpy, sys, types, os
    from test_aether_review_v4 import StubStreamlit, Context
    from pathlib import Path
    class StopScreen(Exception):pass
    mock=StubStreamlit('New analysis')
    def fragment(**_):return lambda f:f
    mock.fragment=fragment
    mock.text_area=lambda *args,**kwargs:''
    mock.number_input=lambda *args,**kwargs:kwargs['value']
    mock.checkbox=lambda *args,**kwargs:False
    mock.error=lambda *args,**kwargs:mock.messages.append(str(args))
    mock.warning=lambda *args,**kwargs:mock.messages.append(str(args))
    mock.success=lambda *args,**kwargs:mock.messages.append(str(args))
    mock.stop=lambda:(_ for _ in ()).throw(StopScreen())
    components=types.ModuleType('streamlit.components');v1=types.ModuleType('streamlit.components.v1')
    v1.html=lambda *a,**kw:None
    previous={k:sys.modules.get(k) for k in ('streamlit','streamlit.components','streamlit.components.v1')}
    old_source=os.environ.pop('AETHER_SOURCE_ROOT',None)
    old_runs=os.environ.pop('AETHER_RUNS_DIR',None)
    try:
        sys.modules.update({'streamlit':mock,'streamlit.components':components,'streamlit.components.v1':v1})
        with pytest.raises(StopScreen):
            runpy.run_path(str(Path(__file__).resolve().parents[1]/'aether_app.py'),run_name='__main__')
    finally:
        for k,v in previous.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v
        if old_source:os.environ['AETHER_SOURCE_ROOT']=old_source
        if old_runs:os.environ['AETHER_RUNS_DIR']=old_runs
    assert any('Approve one-run budget' in name for name in mock.buttons)
    assert any('Run the six-stage analysis' in name for name in mock.buttons)
    assert not any('localhost:8501' in url for _,url in mock.links)
