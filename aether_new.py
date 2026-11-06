"""New buyer enquiry, safety approval, and real six-stage progress inside AETHER."""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from aether_live import approve_enquiry, execute_enquiry, fingerprint

STAGES = ('Qualification','Deep Account Research','Response Generation',
          'Case Study and Material Matching','Partner Identification','AE Handoff Summary')


def source_root() -> Path | None:
    candidates = [os.getenv('AETHER_SOURCE_ROOT','').strip(),
                  r'F:\Downloads\Flytbase-inbound-agent',
                  str(Path.home()/'Downloads'/'Flytbase-inbound-agent')]
    for candidate in candidates:
        if candidate:
            root=Path(candidate)
            if (root/'runs'/'project_budget.json').is_file() and (root/'app.py').is_file():
                return root
    return None


def real_settings():
    from flytbase_bdr.config import Settings, credential_status
    original=source_root()
    if original is None:
        return None, {}, 'Original FlytBase project not detected. Start AETHER with START_AETHER.ps1 from a folder next to the original project.'
    # Secrets stay in the existing project's private .env file. Nothing is
    # written back to the AETHER folder or printed to the screen.
    load_dotenv(original/'.env', override=False)
    keys=credential_status()
    settings=Settings.from_env().model_copy(update={'runs_dir':str(original/'runs')})
    return settings, keys, ''


def _launch(settings, enquiry, allowance_id):
    events=queue.Queue()
    def worker():
        try:
            def on_update(item):
                events.put(('stage',{'id':item.run_id,'status':item.status,
                                      'stages':[(s.name,s.status) for s in item.stages]}))
            result=execute_enquiry(settings,enquiry,allowance_id,approved=True,on_update=on_update)
            events.put(('finished',{'id':result.run_id,'status':result.status,
                                     'stages':[(s.name,s.status) for s in result.stages]}))
        except Exception as exc:
            # Only local class/message, never provider response or credentials.
            events.put(('error',f'{type(exc).__name__}: {str(exc)[:450]}'))
    thread=threading.Thread(target=worker,name='aether-live-analysis',daemon=True)
    st.session_state['aether_job']={'thread':thread,'events':events,'latest':None,'done':None,'error':''}
    thread.start()


def _view_results():
    st.session_state['aether_page']='Overview'
    st.session_state['aether_run_index']=0
    st.session_state['aether_nav_revision']=st.session_state.get('aether_nav_revision',0)+1


@st.fragment(run_every='3s')
def progress_view():
    job=st.session_state.get('aether_job')
    if not job:return
    while True:
        try: event,item=job['events'].get_nowait()
        except queue.Empty:break
        if event=='stage':job['latest']=item
        elif event=='finished':job['done']=item;job['latest']=item
        elif event=='error':job['error']=item
    record=job.get('latest')
    st.markdown('<div class="aether-progress-title">SIX-STAGE ANALYSIS MONITOR</div>',unsafe_allow_html=True)
    if record:
        completed=sum(status in {'complete','partial','failed','skipped'} for _,status in record['stages'])
        st.progress(min(1.0,completed/6),text=f'{completed} of 6 stages processed · {record["id"]}')
        for name,s in record['stages']:
            symbol='✓' if s=='complete' else '◐' if s in {'partial','running'} else '○'
            st.markdown(f'<div class="analysis-stage"><span>{symbol} {name}</span><em>{s.replace("_"," ").title()}</em></div>',unsafe_allow_html=True)
    else:
        st.info('The approved workflow is starting. This panel updates automatically as stages are saved.')
    if job.get('done'):
        st.success('Live execution finished: '+str(job['done']['status']).replace('_',' ').title()+'. The new record is saved in your original runs folder.')
        st.button('↗ Open the latest analysis',type='primary',on_click=_view_results,key='aether_open_result')
    elif job.get('error'):
        st.error('Execution stopped: '+job['error'])
        st.caption('Saved stage checkpoints and provider receipts remain in the original project.')
    elif job['thread'].is_alive():
        st.caption('Real source research and rate-limit waits can take time. Progress is checkpointed automatically.')
    else:
        st.warning('The worker is no longer active. Inspect the latest saved run for the recorded outcome.')


def render():
    st.markdown('<div class="new-hero-kicker">AETHER / LIVE INBOUND INTELLIGENCE <span>✦ FRESH LEAD</span></div>',unsafe_allow_html=True)
    st.markdown('<div class="new-hero"><div class="new-hero-orbit" aria-hidden="true">✦</div>'
                '<div class="new-hero-type">YOUR NEXT OPPORTUNITY STARTS HERE</div>'
                '<h1>One inquiry.<br><span>Six intelligent moves.</span></h1>'
                '<p>Paste an inbound email from any prospective FlytBase buyer. The system qualifies the lead, researches the company, prepares outreach, matches proof, recommends routing, and hands the opportunity to sales.</p>'
                '</div>',unsafe_allow_html=True)
    col1,col2=st.columns([1.45,1],gap='large')
    with col1:
        st.markdown('<div class="aether-form-label">01 / YOUR BUYER’S MESSAGE</div>',unsafe_allow_html=True)
        if st.button('↘ Insert original FlytBase assignment enquiry',key='aether_load_sample'):
            st.session_state['aether_new_enquiry']=(Path(__file__).resolve().parent/'examples'/'enquiry.txt').read_text(encoding='utf-8')
            st.session_state.pop('aether_approved_fresh',None)
            st.rerun()
        enquiry=st.text_area('Inbound enquiry',key='aether_new_enquiry',height=240,
                             placeholder='From: ...\nTitle: ...\nCompany: ...\nSubject: ...\nContext: ...',
                             help='Paste one original inbound buyer email. Up to 16,000 characters.')
        st.caption(f'{len(enquiry.strip()):,} / 16,000 characters · The complete message is the only buyer input.')
        st.markdown('<div class="workflow-lanes"><span>01 QUALIFY</span><span>02 RESEARCH</span><span>03 RESPOND</span><span>04 MATCH</span><span>05 ROUTE</span><span>06 HANDOFF</span></div>',unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="aether-form-label">02 / LIVE-RUN READINESS</div>',unsafe_allow_html=True)
        settings, keys, issue=real_settings()
        if issue:
            st.error(issue)
        else:
            st.markdown('<div class="readiness-row"><span>Original project</span><strong>Connected</strong></div>',unsafe_allow_html=True)
            st.markdown(f'<div class="readiness-row"><span>Groq / Tavily credentials</span><strong>{"Available" if all(keys.values()) else "Needs setup"}</strong></div>',unsafe_allow_html=True)
            st.markdown('<div class="readiness-row"><span>Research mode</span><strong>Live public sources</strong></div>',unsafe_allow_html=True)
            st.markdown('<div class="readiness-row"><span>Billing</span><strong>Free only · approved caps</strong></div>',unsafe_allow_html=True)
        st.caption('Results are generated by the real Python workflow. Stage status may be partial when evidence cannot be confirmed.')
        st.markdown('<div class="aether-form-label">03 / PROTECTED PROVIDER BUDGET</div>',unsafe_allow_html=True)
        usage_text=st.text_input('Groq tokens used today (UTC)',placeholder='Enter refreshed dashboard total, e.g. 90725',key='aether_groq_used',
                                 help='Check GroqCloud → Organisation Usage for the current UTC date. This is a user attestation, not an automated balance check.')
        a,b=st.columns(2)
        with a: groq_cap=st.number_input('Max Groq tokens',min_value=8000,max_value=63000,value=42000,step=1000,key='aether_groq_cap')
        with b: tavily_cap=st.number_input('Max Tavily credits',min_value=1,max_value=16,value=12,step=1,key='aether_tavily_cap')
        confirmed=st.checkbox('I checked current Free quotas for Groq and Tavily; paid billing is disabled.',key='aether_free_confirmation')
        approve_budget=st.checkbox('I approve this one-run budget. Only explicit launch may use it.',key='aether_budget_confirmation')
    settings,keys,issue=real_settings()
    running=bool(st.session_state.get('aether_job') and st.session_state['aether_job']['thread'].is_alive())
    valid_input=bool(enquiry.strip()) and len(enquiry)<=16000
    ready=bool(settings and all(keys.values()) and valid_input)
    active=st.session_state.get('aether_approved_fresh') or {}
    if active and active.get('fingerprint') != fingerprint(enquiry):
        active={}
        st.session_state.pop('aether_approved_fresh',None)
    st.markdown('<div class="aether-form-label">04 / APPROVE, THEN EXECUTE</div>',unsafe_allow_html=True)
    actions=st.columns([1,1.35],gap='medium')
    with actions[0]:
        if st.button('1 · Approve one-run budget',disabled=not(ready and confirmed and approve_budget and not running and usage_text.isdecimal()) or bool(active),key='aether_approve',use_container_width=True):
            try:
                item=approve_enquiry(settings,enquiry,int(usage_text),int(groq_cap),int(tavily_cap),free_only=confirmed,approved_budget=approve_budget)
                st.session_state['aether_approved_fresh']={'id':item['id'],'fingerprint':fingerprint(enquiry),
                                                              'groq_cap':item['groq_tokens'], 'tavily_cap':item['tavily_credits']}
                st.session_state['aether_started_once']=False
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with actions[1]:
        if st.button('2 · Run the six-stage analysis →',type='primary',use_container_width=True,
                     disabled=not(ready and active and not running and not st.session_state.get('aether_started_once')),
                     key='aether_run_live'):
            _launch(settings,enquiry,active['id'])
            st.session_state['aether_started_once']=True
            st.rerun()
    if active:
        st.success('Budget approved: '+active['id']+' · '+str(active.get('groq_cap','?'))+' Groq tokens / '+str(active.get('tavily_cap','?'))+' Tavily credits. Launch is separately controlled above.')
    if not valid_input:
        st.caption('Paste an enquiry to begin. The original SQM example is optional.')
    elif not all(keys.values()) and settings:
        st.warning('Groq and Tavily Free API credentials are required for fresh account research. Configure them in the original private .env file.')
    if st.session_state.get('aether_job'):progress_view()
    st.markdown('<div class="new-safety-note">SECURITY & INTEGRITY · No emails are sent automatically. Research claims require cited evidence. Outputs, usage receipts, and approval history are retained in the original project.</div>',unsafe_allow_html=True)
