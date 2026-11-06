"""Offline UI replay tests for AETHER v4. No provider calls or Streamlit server required."""
from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from aether_helpers import case_summary, group_warnings


class Context:
    def __enter__(self):return self
    def __exit__(self,*args):return False


class StubStreamlit(types.ModuleType):
    def __init__(self,page):
        super().__init__('streamlit')
        self.page=page
        self.session_state={}
        self.sidebar=Context()
        self.messages=[]
        self.links=[]
        self.buttons=[]
        self.json_values=[]
    def set_page_config(self,**kwargs):pass
    def markdown(self,content,**kwargs):self.messages.append(str(content))
    def caption(self,content,**kwargs):self.messages.append(str(content))
    def info(self,content,**kwargs):self.messages.append(str(content))
    def write(self,content,**kwargs):self.messages.append(str(content))
    def json(self,content,**kwargs):self.json_values.append(content)
    def radio(self,label,options,**kwargs):return self.page
    def selectbox(self,label,options,**kwargs):return 0
    def text_input(self,label,**kwargs):return kwargs.get('value','')
    def button(self,*args,**kwargs):
        self.buttons.append(str(args[0]) if args else str(kwargs.get('label','')))
        return False
    def link_button(self,label,url,**kwargs):self.links.append((label,url))
    def download_button(self,*args,**kwargs):pass
    def columns(self,spec,**kwargs):return [Context() for _ in range(spec if isinstance(spec,int) else len(spec))]
    def tabs(self,titles):return [Context() for _ in titles]
    def expander(self,*args,**kwargs):return Context()
    def stop(self):raise RuntimeError('Unexpected st.stop')


def run_page(page, source_run: Path):
    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'check'/ 'run.json'
        target.parent.mkdir()
        target.write_bytes(source_run.read_bytes())
        os.environ['AETHER_RUNS_DIR']=tmp
        mock=StubStreamlit(page)
        components=types.ModuleType('streamlit.components');v1=types.ModuleType('streamlit.components.v1')
        iframe=[]
        v1.html=lambda html,**kwargs:iframe.append((html,kwargs))
        before={k:sys.modules.get(k) for k in ('streamlit','streamlit.components','streamlit.components.v1')}
        try:
            sys.modules.update({'streamlit':mock,'streamlit.components':components,'streamlit.components.v1':v1})
            runpy.run_path(str(ROOT/'aether_app.py'),run_name='__main__')
        finally:
            for k,value in before.items():
                if value is None:sys.modules.pop(k,None)
                else:sys.modules[k]=value
            os.environ.pop('AETHER_RUNS_DIR',None)
        return mock,iframe


def test_human_case_summary():
    d={'candidate':{'title':'SQM study | FlytBase | FlytBase','source_id':'S_abc123abc123',
                    'dimensions':[{'dimension':'industry','matched':True},{'dimension':'geography','matched':False}]},
       'eligible':False,'score':90,'rejection_reasons':['Missing supporting passages']}
    s=case_summary(d)
    assert s['title']=='SQM study'
    assert s['eligible'] is False
    assert s['dimensions']==['Mining industry']
    assert s['reasons']==['Missing supporting passages']


def test_grouped_warnings_preserve_originals():
    notes=['S_abcdef123456: Page inspection unavailable (HTTPStatusError)',
           'Groundedness claim: no source evidence','No primary case study cleared the checks']
    groups=group_warnings(notes)
    assert sum(g['count'] for g in groups)==len(notes)
    assert 'pages' in ' '.join(g['title'] for g in groups).lower()


def test_six_page_review():
    runfile=Path('/mnt/data/run(1).json')
    if not runfile.exists():
        # This test can be run with the packaged simulated fixture independently.
        runfile=ROOT/'examples/recruiter_demo/offline_simulation/run.json'
    for page in ('Overview', 'Account intelligence', 'Outreach studio','Case studies & partners','AE handoff','Evidence & audit'):
        view,iframes=run_page(page,runfile)
        assert any('Run new analysis' in label for label in view.buttons),page
        assert not any('localhost:8501' in url for _,url in view.links),page
        assert iframes and 'stMain' in iframes[0][0]
        assert iframes[0][1]['width'] in (1,2)
        if page=='AE handoff':
            content='\n'.join(view.messages)
            assert 'CASE STUDY DECISION' in content
            assert '"candidate":' not in content  # No dumped handoff JSON
        if page=='Evidence & audit':
            text='\n'.join(view.messages)
            assert 'WHAT NEEDS VERIFICATION' in text
            assert 'NEXT STEP' in text

if __name__=='__main__':
    test_human_case_summary()
    test_grouped_warnings_preserve_originals()
    test_six_page_review()
    print('AETHER v4: helper and six-page offline replay checks passed')
