"""AETHER v4 — information-first FlytBase BDR review UI.

AETHER displays saved, genuine workflow outputs without contacting providers.
The protected live engine remains in the accompanying FlytBase source app.
Edits made to outreach drafts in the browser are local review copies only.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

from aether_helpers import case_summary, group_warnings, cached_saved_run

HERE = Path(__file__).resolve().parent
PAGES = ('Overview', 'New analysis', 'Account intelligence', 'Outreach studio', 'Case studies & partners', 'AE handoff', 'Evidence & audit')
PAGE_IDS = ('overview', 'new-analysis', 'intelligence', 'outreach', 'recommendations', 'handoff', 'evidence')

st.set_page_config(page_title='AETHER • FlytBase', page_icon='✦', layout='wide', initial_sidebar_state='expanded')
st.markdown('<style>'+(HERE/'assets'/'aether.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def arr(value: Any) -> list:
    return value if isinstance(value,list) else []


def obj(value: Any) -> dict:
    return value if isinstance(value,dict) else {}


def plain(value: Any) -> str:
    if isinstance(value,dict): return str(value.get('text') or value.get('value') or '')
    return str(value or '')


def status(value: Any) -> str:
    return str(value or 'unknown').replace('_',' ').capitalize()


def get_stage(run: dict, name: str) -> dict:
    return next((item for item in arr(run.get('stages')) if item.get('name')==name),{'name':name,'status':'unavailable','output':{},'warnings':[]})


def is_demo(run: dict) -> bool:
    return 'offline' in str(run.get('mode','')).lower() or 'offline' in str(run.get('run_id','')).lower() or str(run.get('run_id','')).startswith('synthetic')


def source_index(run: dict) -> dict:
    src=run.get('sources') or {}
    if isinstance(src,dict): return {str(k):v for k,v in src.items() if isinstance(v,dict)}
    return {str(x.get('source_id') or x.get('id') or ''):x for x in arr(src) if isinstance(x,dict)}


def default_roots() -> list[Path]:
    env=os.environ.get('AETHER_RUNS_DIR','').strip()
    candidates=[Path(env)] if env else []
    custom=st.session_state.get('aether_custom_dir','')
    if custom:candidates.append(Path(custom))
    candidates += [
        HERE/'runs',HERE.parent/'Flytbase-inbound-agent'/'runs',
        HERE.parent.parent/'Flytbase-inbound-agent'/'runs',
        Path(r'F:\Downloads\Flytbase-inbound-agent\runs'),
        Path.home()/'Downloads'/'Flytbase-inbound-agent'/'runs',
        HERE/'examples'/'recruiter_demo'/'offline_simulation',
    ]
    out=[];seen=set()
    for p in candidates:
        ident=str(p).casefold()
        if ident not in seen:seen.add(ident);out.append(p)
    return out


def load_runs():
    results={}; roots=[]
    for root in default_roots():
        if not root.exists():continue
        roots.append(str(root))
        paths=([root] if root.name=='run.json' else [root/'run.json',*root.glob('*/run.json')])
        for p in paths:
            if not p.is_file():continue
            try:
                stat=p.stat()
                run=cached_saved_run(str(p.resolve()),stat.st_mtime_ns,stat.st_size)
                ident=str(run.get('run_id') or p.parent.name)
                # Prefer first loaded path for duplicate run ids, preserving original run path.
                if ident not in results: results[ident]=(p,run)
            except (OSError,ValueError):continue
    return sorted(results.items(),key=lambda kv:(not is_demo(kv[1][1]),str(kv[1][1].get('started_at') or '')),reverse=True),roots


def sidebar_on_change():
    st.session_state['aether_nav_revision']=st.session_state.get('aether_nav_revision',0)+1


def scroll_to_top():
    """Use the main Streamlit DOM to reset navigation; no stale iframe cursor."""
    revision=st.session_state.get('aether_nav_revision',0)
    # Static, locally authored JavaScript is safe in the 1.66 parent app DOM.
    # No untrusted buyer or research text is interpolated into the script.
    payload=r"""<script>
    (() => {
      const rev=__REV__, root=document.documentElement;
      function reset(){
        const nodes=[document.scrollingElement,document.body,document.documentElement,
           ...document.querySelectorAll('section[data-testid="stMain"], [data-testid="stAppViewContainer"], .main, main')];
        for(const node of nodes){if(!node)continue;
          try{node.scrollTop=0;node.scrollTo?.({top:0,behavior:'instant'});}catch(_){}}
        try{window.scrollTo({top:0,behavior:'instant'});}catch(_){}}
      if(window.__aetherNavRevision!==rev){
        window.__aetherNavRevision=rev;
        reset();[80,180,380,700,1100,1500].forEach(t=>setTimeout(reset,t));
      }
      if(!window.__aetherV5Events){
        window.__aetherV5Events=true;
        document.addEventListener('pointerdown',e=>{
          if(e.target instanceof Element && e.target.closest('[data-testid="stSidebar"] [role="radiogroup"] label')){
            reset();[100,300,700].forEach(t=>setTimeout(reset,t));
          }
        },{passive:true,capture:true});
        if(window.matchMedia('(pointer: fine)').matches && !window.matchMedia('(prefers-reduced-motion: reduce)').matches){
          let x=-500,y=-500,targetX=-500,targetY=-500,active=false;
          document.addEventListener('pointermove',e=>{
            targetX=e.clientX;targetY=e.clientY;
            active=!!(e.target instanceof Element && e.target.closest('button,a,label,[role="tab"],summary,[role="radio"]'));
          },{passive:true});
          (function frame(){
            x+=(targetX-x)*.17;y+=(targetY-y)*.17;
            root.style.setProperty('--aether-x',x+'px');
            root.style.setProperty('--aether-y',y+'px');
            root.style.setProperty('--aether-aura-opacity',active?'.23':'.12');
            requestAnimationFrame(frame);
          })();
        }
      }
      // AETHER v7: a stable navigation toggle independent of Streamlit's toolbar layout.
      // It clicks the native Streamlit expand/collapse control rather than faking sidebar state.
      function installAetherNavigationToggle(){
        let toggle=document.getElementById('aether-navigation-toggle');
        if(!toggle){
          toggle=document.createElement('button');
          toggle.id='aether-navigation-toggle';
          toggle.type='button';
          toggle.textContent='☰';
          toggle.setAttribute('aria-controls','aether-sidebar-navigation');
          document.body.appendChild(toggle);
        }
        const nativeButton=(expanded)=>{
          const queries=expanded ? [
            '[data-testid="stSidebarHeader"] button[aria-label*="sidebar" i]',
            '[data-testid="stSidebarCollapseButton"] button',
            '[data-testid="stSidebarHeader"] button',
            '[data-testid="stSidebar"] button[aria-label*="sidebar" i]',
            '[data-testid="stSidebar"] button[title*="sidebar" i]'
          ] : [
            '[data-testid="stSidebarCollapsedControl"] button',
            '[data-testid="stSidebarCollapsedControl"] [role="button"]',
            'button[aria-label="Open sidebar"]',
            'button[aria-label="Expand sidebar"]',
            '[data-testid="stHeader"] button[aria-label*="sidebar" i]',
            '[data-testid="stHeader"] button[title*="sidebar" i]'
          ];
          for(const q of queries){
            const el=document.querySelector(q);
            if(el instanceof HTMLElement && typeof el.click==='function')return el;
          }
          return null;
        };
        const sidebarExpanded=()=>{
          const node=document.querySelector('[data-testid="stSidebar"]');
          if(!node)return false;
          const r=node.getBoundingClientRect();
          const style=getComputedStyle(node);
          return style.display!=='none' && style.visibility!=='hidden' && r.width>160 && r.right>140 && r.left<100;
        };
        function refresh(){
          const open=sidebarExpanded();
          toggle.dataset.open=String(open);
          const symbol=open?'‹':'☰';
          if(toggle.textContent!==symbol)toggle.textContent=symbol;
          toggle.setAttribute('aria-label',open?'Close navigation sidebar':'Open navigation sidebar');
          toggle.setAttribute('title',open?'Close sidebar':'Open sidebar');
          const sidebar=document.querySelector('[data-testid="stSidebar"]');
          const edge=sidebar?.getBoundingClientRect().right || 0;
          const targetLeft=(open?Math.max(12,Math.min(window.innerWidth-50,Math.round(edge)-48)):13)+'px';
          if(toggle.style.left!==targetLeft)toggle.style.left=targetLeft;
        }
        if(!toggle.dataset.bound){
          toggle.dataset.bound='1';
          toggle.addEventListener('click',()=>{
            const open=sidebarExpanded();
            const native=nativeButton(open);
            if(native){native.click();}
            else {
              // Streamlit's documented keyboard toggle is a useful fallback.
              document.dispatchEvent(new KeyboardEvent('keydown',{
                key:'s',code:'KeyS',ctrlKey:true,shiftKey:true,bubbles:true
              }));
            }
            [80,220,450,750].forEach(ms=>setTimeout(refresh,ms));
          });
        }
        refresh();
        // One listener set for the full browser session. It survives app rerenders.
        if(!window.__aetherNavigationWatcher){
          window.__aetherNavigationWatcher=true;
          window.addEventListener('resize',refresh,{passive:true});
          const observer=new MutationObserver(()=>{
            if(window.__aetherNavigationRefreshPending)return;
            window.__aetherNavigationRefreshPending=true;
            requestAnimationFrame(()=>{
              window.__aetherNavigationRefreshPending=false;refresh();
            });
          });
          observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','aria-expanded','data-state']});
        }
      }
      installAetherNavigationToggle();
      // Remove residual dot elements from earlier app versions if present.
      document.querySelectorAll('#aether-pointer-aura,#aether-pointer-core').forEach(e=>e.remove());
    })();
    </script>""".replace('__REV__',str(revision))
    try:
        st.html(payload,unsafe_allow_javascript=True)
    except (TypeError, AttributeError):
        components.html(payload,height=0,width=1,scrolling=False)


def go_to_new():
    st.session_state['aether_page']='New analysis'
    sidebar_on_change()


def eyebrow(text: str):
    st.markdown(f'<div class="eyebrow">{esc(text)}</div>',unsafe_allow_html=True)


def line(label: str, value: Any, accent=False):
    st.markdown(f'<div class="data-line"><span>{esc(label)}</span><strong class="{ "v-accent" if accent else ""}">{esc(value)}</strong></div>',unsafe_allow_html=True)


def intro(number: str, title: str, text: str):
    st.markdown(f'<div class="section-number">{esc(number)} / REVENUE INTELLIGENCE</div><h1>{esc(title)}</h1><p class="dek">{esc(text)}</p>',unsafe_allow_html=True)


def notice(text: str, kind='neutral'):
    st.markdown(f'<div class="info-note {esc(kind)}">{esc(text)}</div>',unsafe_allow_html=True)


def claims(claim_list, sources, demo=False, max_items=20):
    displayed=0
    for claim in arr(claim_list)[:max_items]:
        c=obj(claim)
        content=plain(c) if isinstance(claim,dict) else str(claim)
        if not content:continue
        displayed+=1
        kind=c.get('kind','unknown')
        st.markdown(f'<div class="claim-row"><span class="claim-type">{esc(str(kind).upper())}{" · DEMO DATA" if demo else ""}</span><p>{esc(content)}</p></div>',unsafe_allow_html=True)
        refs=[]
        for ref in arr(c.get('evidence')):
            if not isinstance(ref,dict):continue
            sid=str(ref.get('source_id') or ''); s=obj(sources.get(sid)); uri=verified_source_url(s.get('url'), s.get('title'), demo)
            if uri:refs.append(f'<a href="{esc(uri)}" target="_blank" rel="noopener noreferrer">{esc(s.get("title") or sid)[:62]} ↗</a>')
            elif sid:refs.append(f'<span>{esc(sid)}</span>')
        if refs:st.markdown('<div class="source-tags">SOURCES · '+' · '.join(refs[:3])+'</div>',unsafe_allow_html=True)
        uncertainty=c.get('uncertainty')
        if uncertainty and str(uncertainty).lower() not in ('none','n/a','unknown'):
            st.caption('Verification note: '+str(uncertainty))
    if not displayed:notice('No reviewed claims are available for this section. See the source and stage limitations below.')


# Verified navigation targets from FlytBase's public website. UI-only link correction;
# relevance scores, selection outcomes, and stored run evidence are never changed.
SQM_STORY='https://flytbase.com/case-studies/sqm-678-km2-mine-autonomous-inspection-adentu-and-flytbase'
ANGLO_STORY='https://flytbase.com/case-studies/anglo-american-autonomous-mining-drones-peru-case-study'
STORY_INDEX='https://flytbase.com/case-studies'


def verified_source_url(url, title='', demo=False):
    if demo:return ''
    name=str(title or '').lower()
    u=str(url or '').strip()
    if 'anglo american' in name and ('case' in name or 'mining' in name) and 'flytbase' in (name+' '+u):return ANGLO_STORY
    if 'sqm' in name and ('case' in name or '678' in name) and 'flytbase' in (name+' '+u):return SQM_STORY
    try:
        parsed=urlparse(u)
        if parsed.scheme in ('http','https') and parsed.netloc and parsed.netloc not in ('localhost','127.0.0.1'):
            return u
    except ValueError:pass
    return ''


def questions(items, max_items=9):
    questions=arr(items)
    if not questions:
        notice('No discovery questions were generated for this run.');return
    for idx,item in enumerate(questions[:max_items],1):
        st.markdown(f'<div class="question"><span>{idx:02d}</span><p>{esc(plain(item))}</p></div>',unsafe_allow_html=True)


def warning_sources(original: list[str], sources: dict, demo: bool, limit: int=3) -> str:
    """Find source IDs directly mentioned in warnings and link to their original documents."""
    ids=[]
    for item in original:
        for sid in re.findall(r'S_[A-Za-z0-9]{8,}',str(item)):
            if sid not in ids:ids.append(sid)
    links=[]
    for sid in ids:
        src=obj(sources.get(sid));url=verified_source_url(src.get('url'),src.get('title'),demo)
        if url:
            title=str(src.get('title') or sid)
            links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(title[:76])} ↗</a>')
        if len(links)>=limit:break
    if links:return '<div class="source-tags warning-sources">REVIEW THE ORIGINAL SOURCE · '+' · '.join(links)+'</div>'
    if ids:return '<div class="source-tags warning-sources">Source reference available in the register below; direct document access was not verified.</div>'
    return ''


def warnings_list(stages, sources=None, demo=False, open_first=False):
    """Show business-meaningful issue groups. Preserve raw notices behind optional detail."""
    sources=sources or {}
    warning_stages=[s for s in stages if arr(s.get('warnings'))]
    if not warning_stages:
        notice('This saved execution has no recorded review notes.');return
    for stage in warning_stages:
        ws=arr(stage.get('warnings'))
        grouped=group_warnings(ws)
        st.markdown(f'<div class="warning-stage-title">{esc(stage.get("name", "Stage"))} <span>{len(grouped)} topics · {len(ws)} technical checks</span></div>',unsafe_allow_html=True)
        for i,g in enumerate(grouped):
            st.markdown('<div class="audit-summary"><div class="audit-summary-head"><strong>'+esc(g['title'])+'</strong><span>'+str(g['count'])+' note'+('s' if g['count']!=1 else '')+'</span></div>'+
                        '<p>'+esc(g['meaning'])+'</p><div class="audit-next">NEXT STEP · '+esc(g['next_action'])+'</div></div>',unsafe_allow_html=True)
            linked=warning_sources(g['original'],sources,demo)
            if linked:st.markdown(linked,unsafe_allow_html=True)
            with st.expander('View original technical notes for this topic',expanded=False):
                for note in g['original']:
                    st.markdown(f'<div class="technical-note">{esc(note)}</div>',unsafe_allow_html=True)


def render_case_decision(raw: Any, sources: dict, demo: bool, rank_label='CASE STUDY ASSESSMENT') -> None:
    """Render case-study data as a decision for a human reviewer, never JSON."""
    item=case_summary(raw)
    if not item:
        notice('No validated case-study recommendation is available in this run. Review the candidates on the Case studies page.','caution');return
    approved=item['eligible']
    evidence='EVIDENCE CHECKS PASSED' if approved else 'REVIEW BEFORE RECOMMENDING'
    subtitle='Suitable for consideration after site-specific discovery.' if approved else 'This is a relevant research candidate, not an approved recommendation.'
    st.markdown(f'<div class="decision-card"><div class="decision-top"><span>{esc(rank_label)}</span><em class="{"decision-yes" if approved else "decision-review"}">{evidence}</em></div><h3>{esc(item["title"])}</h3><p>{esc(subtitle)}</p></div>',unsafe_allow_html=True)
    if item.get('dimensions'):
        st.markdown('<div class="match-chips">'+''.join('<span>✓ '+esc(k)+'</span>' for k in item['dimensions'])+'</div>',unsafe_allow_html=True)
    relevance=item.get('relevance','')
    if item.get('dimensions') and ('inspected' in relevance.lower() or 'article mentions' in relevance.lower()):
        relevance='The saved source comparison matched: '+', '.join(item['dimensions'])+'. This helps an AE choose a relevant discussion example; fit for the buyer’s exact sites still requires confirmation.'
    if relevance:st.markdown('<div class="decision-reason"><b>Why it could help</b><p>'+esc(relevance)+'</p></div>',unsafe_allow_html=True)
    reasons=item.get('reasons') or []
    if reasons:
        st.markdown('<div class="decision-reason muted"><b>What needs verification</b><p>'+esc('; '.join(reasons[:3]))+'</p></div>',unsafe_allow_html=True)
    elif not approved:
        st.markdown('<div class="decision-reason muted"><b>What needs verification</b><p>Confirm the evidence and site relevance before recommending it to the buyer.</p></div>',unsafe_allow_html=True)
    if item.get('limitations'):
        for note in item['limitations'][:2]:st.markdown(f'<div class="small-gap">{esc(note)}</div>',unsafe_allow_html=True)
    sid=item.get('source_id','');source=obj(sources.get(sid))
    url=verified_source_url(source.get('url'),source.get('title') or item.get('title'),demo)
    if url:st.link_button('↗ Read the published case study',url)
    elif not demo:st.link_button('↗ Explore official FlytBase case studies',STORY_INDEX)
    else:st.caption('Synthetic case-study example. No published link is claimed.')
    if item.get('selection_note'):st.caption(item['selection_note'])


def editor_widget(message: str, storage_key: str):
    # Local browser-side editor: no email is sent and saved run JSON stays immutable.
    payload=json.dumps(message,ensure_ascii=False).replace('</','<\\/')
    store=json.dumps(storage_key)
    # The iframe is always scrollable as a fallback.  A ResizeObserver inside
    # it asks Streamlit to resize the frame to its actual content height.
    # This prevents the final paragraphs/actions from being clipped.
    height=min(820,max(320,150+int(len(message)/55)*22+message.count('\n')*10))
    widget='''<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;color:#deebf9;background:transparent;font-family:Arial,Helvetica,sans-serif}
    .pane{border:1px solid #2a415d;border-radius:17px;background:linear-gradient(140deg,#101f33,#0d182a);overflow:hidden}
    .bar{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:13px 17px;border-bottom:1px solid #26384f}
    .hint{font:600 10px Arial;letter-spacing:1.6px;color:#9aadc4;text-transform:uppercase}
    .actions{display:flex;gap:7px}
    button{cursor:pointer;border:1px solid #547ca3;background:#183452;border-radius:8px;color:#e4f7ff;font:600 12px Arial;padding:9px 13px;transition:background .2s,transform .2s}
    button:hover{background:#2a577f;transform:translateY(-1px)} button:focus-visible{outline:2px solid #66d5f7}
    #preview{white-space:pre-wrap;overflow-wrap:anywhere;padding:18px 22px;line-height:1.78;font-size:14px;min-height:100px;overflow:visible}
    #draft{display:none;width:calc(100% - 32px);margin:16px;min-height:210px;height:295px;resize:vertical;background:#091527;border:1px solid #4b7ca9;border-radius:10px;padding:17px;color:#f6fbff;font-size:14px;line-height:1.65;font-family:inherit}
    #notice{min-height:29px;padding:0 19px 9px;color:#94b6ce;font:12px Arial}
    @media(max-width:500px){.bar{display:block}.actions{margin-top:12px}button{flex:1}}
    </style></head><body>
    <div class="pane"><div class="bar"><span class="hint">Draft for human review · editable copy</span>
    <div class="actions"><button id="edit" type="button">✎ Edit email</button><button id="copy" type="button">⧉ Copy email</button></div></div>
    <div id="preview"></div><textarea id="draft" aria-label="Edit email draft"></textarea>
    <div id="notice">Edits stay in this browser. Nothing is sent to the buyer.</div></div>
    <script>
    const original=__PAYLOAD__; const cacheKey=__STORE__;
    const preview=document.getElementById('preview'), box=document.getElementById('draft');
    const edit=document.getElementById('edit'), copy=document.getElementById('copy'), note=document.getElementById('notice');
    let current=original; try{current=localStorage.getItem(cacheKey)||original}catch(e){}
    // Streamlit's component iframe supports frame-height messages.  If this
    // client version does not resize, the Python component enables scrolling.
    function resize(){
      const pane=document.querySelector('.pane');
      const measured=Math.ceil(pane.getBoundingClientRect().height+12);
      try{window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:setFrameHeight',height:Math.min(920,Math.max(260,measured))},'*');}catch(e){}
    }
    function display(){preview.textContent=current;box.value=current;requestAnimationFrame(resize);}display();
    if(window.ResizeObserver){new ResizeObserver(resize).observe(document.querySelector('.pane'));}
    window.addEventListener('load',resize);
    let editing=false;
    edit.addEventListener('click',()=>{
      if(!editing){box.value=current;box.style.display='block';preview.style.display='none';edit.textContent='✓ Save edits';box.focus();}
      else {current=box.value;try{localStorage.setItem(cacheKey,current)}catch(e){}
        display();box.style.display='none';preview.style.display='block';edit.textContent='✎ Edit email';note.textContent='Edits saved locally in this browser. Human approval required before sending.';}
      editing=!editing;requestAnimationFrame(resize);
    });
    copy.addEventListener('click',async()=>{
      let value=editing?box.value:current;let copied=false;
      try{await navigator.clipboard.writeText(value);copied=true;}catch(e){}
      if(!copied){let temp=document.createElement('textarea');temp.value=value;temp.style.position='fixed';temp.style.opacity='0';document.body.appendChild(temp);temp.focus();temp.select();try{copied=document.execCommand('copy')}catch(e){}temp.remove();}
      if(copied){note.textContent='Copied the current email text to clipboard.';copy.textContent='✓ Copied';setTimeout(()=>copy.textContent='⧉ Copy email',1600);}
      else{note.textContent='Select the text and press Ctrl+C to copy.';box.style.display='block';preview.style.display='none';box.value=value;box.focus();box.select();}
    });
    </script></body></html>'''.replace('__PAYLOAD__',payload).replace('__STORE__',store)
    components.html(widget,height=height,scrolling=True)


options,found_roots=load_runs()
with st.sidebar:
    st.markdown('<div class="brand-glyph">✦<span></span></div><div class="brand-name">AETHER<span> / FLYTBASE</span></div><div class="brand-sub">AUTONOMOUS REVENUE INTELLIGENCE</div>',unsafe_allow_html=True)
    st.markdown('<p class="sidebar-promise">From first enquiry to the next intelligent move.</p>',unsafe_allow_html=True)
    st.markdown('<div class="side-rule"></div>',unsafe_allow_html=True)
    page=st.radio('WORKSPACE',PAGES,label_visibility='collapsed',key='aether_page',on_change=sidebar_on_change)
    st.markdown('<div class="side-rule"></div>',unsafe_allow_html=True)
    if options:
        labels=[]
        for ident,(_,record) in options:
            label=('DEMO · ' if is_demo(record) else 'LIVE · ')+str(ident)+' · '+status(record.get('status'))
            labels.append(label)
        chosen=st.selectbox('ACTIVE ANALYSIS',list(range(len(options))),format_func=lambda i:labels[i],key='aether_run_index',on_change=sidebar_on_change)
        run_path,run=options[chosen][1]
        tag='OFFLINE SIMULATION' if is_demo(run) else 'SAVED REAL EXECUTION'
        st.markdown(f'<div class="source-badge {"demo" if is_demo(run) else "live"}">{esc(tag)}</div>',unsafe_allow_html=True)
    else:run=None;run_path=None
    with st.expander('Load saved executions',expanded=not any(not is_demo(r) for _,(_,r) in options)):
        st.caption('Expected folder: F:\\Downloads\\Flytbase-inbound-agent\\runs')
        saved=st.text_input('Runs folder path',value=st.session_state.get('aether_custom_dir',''),placeholder=r'F:\Downloads\Flytbase-inbound-agent\runs')
        if st.button('Load this folder',use_container_width=True):
            st.session_state['aether_custom_dir']=saved.strip().strip('"')
            st.session_state.pop('aether_run_index',None)
            st.rerun()
        if not any(not is_demo(r) for _,(_,r) in options):st.caption('Only the bundled offline demonstration was found. Load the original runs folder to view real results.')
    st.markdown('<div class="side-rule"></div><div class="sidebar-foot">✦ QUALIFY → RESEARCH → RESPOND → ROUTE<br>YOUR SALES INTELLIGENCE WORKSPACE</div>',unsafe_allow_html=True)

scroll_to_top()

if page == 'New analysis':
    from aether_new import render as render_new_analysis
    render_new_analysis()
    st.stop()

if run is None:
    intro('00','Connect your analysis','Choose a saved execution to begin.')
    st.info('Enter the path to your FlytBase source project’s runs folder in the sidebar. The viewer will load original run.json records.')
    st.stop()

qst=get_stage(run,'Qualification');q=obj(qst.get('output'));lead=obj(q.get('lead'))
research=get_stage(run,'Deep Account Research');outreach=get_stage(run,'Response Generation')
cases=get_stage(run,'Case Study and Material Matching');partners=get_stage(run,'Partner Identification')
handoff=get_stage(run,'AE Handoff Summary');handoff_out=obj(handoff.get('output'))
sources=source_index(run)
name=str(lead.get('company') or obj(handoff_out.get('buyer_context')).get('company') or 'Incoming account')
short='SQM' if 'Sociedad Quimica' in name else name
score=q.get('priority_score','—'); completeness=q.get('qualification_completeness_percent','—')
demo=is_demo(run); run_id=str(run.get('run_id',''))

top_left,top_right=st.columns([4,1.3],vertical_alignment='center')
with top_left:
    st.markdown('<div class="topline">FLYTBASE / AETHER INTELLIGENCE <span>DECISION SUPPORT</span></div>',unsafe_allow_html=True)
with top_right:
    st.button('✦ Run new analysis →', use_container_width=True, type='primary', on_click=go_to_new, key='aether_top_new')
st.markdown(f'<div class="context-strip"><strong>{esc(short)}</strong><span>{esc(lead.get("geography","Unspecified location"))}</span><span>{esc(lead.get("industry","Unknown industry"))}</span><em class="{"demo-label" if demo else "live-label"}">{"OFFLINE DEMO" if demo else "ACTUAL RUN"} · {esc(status(run.get("status")))}</em></div>',unsafe_allow_html=True)
if demo:
    notice('DEMONSTRATION DATA — this is a fictional offline test. Case studies, companies, contacts and evidence may be synthetic. Select a LIVE saved run to review the actual SQM enquiry.','demo-banner')

if page=='Overview':
    intro('01','The opportunity. Clearly.','Everything a BDR needs before opening the first email.')
    st.markdown(f'<h2 class="opportunity-title">{esc(short)} <span>/ {esc(lead.get("need") or "Inbound inspection enquiry")}</span></h2>',unsafe_allow_html=True)
    st.markdown(f'<div class="signal-row"><div><b>{esc(score)}<small>/100</small></b><span>Engagement priority</span></div><div><b>{esc(completeness)}<small>%</small></b><span>Qualification completeness</span></div><div><b>{esc(status(q.get("priority_band") or "Discovery"))}</b><span>Recommended response</span></div></div>',unsafe_allow_html=True)
    left,right=st.columns([1.45,1],gap='large')
    with left:
        eyebrow('WHAT THE LEAD WANTS')
        st.markdown(f'<div class="lead-proposition">{esc(lead.get("need") or handoff_out.get("business_problem_and_desired_outcome") or "Enquiry received")}</div>',unsafe_allow_html=True)
        for fact in arr(lead.get('knowns'))[:5]:st.markdown(f'<div class="bullet-row"><span>↗</span>{esc(fact)}</div>',unsafe_allow_html=True)
        eyebrow('WHO WE ARE SPEAKING TO')
        line('Contact',lead.get('name') or 'Not supplied');line('Title',lead.get('title') or 'Not supplied');line('Email',lead.get('email') or 'Not supplied')
    with right:
        eyebrow('NEXT BEST ACTION')
        st.markdown('<div class="action-panel"><div class="action-tag">DISCOVERY FIRST ↗</div><h3>Clarify before proposing a solution</h3><p>'+esc(handoff_out.get('suggested_next_action') or 'Verify budget, stakeholders, the site conditions and implementation timeline.')+'</p></div>',unsafe_allow_html=True)
        eyebrow('GAPS THAT CHANGE THE DEAL')
        for k,label in [('budget','Budget approval'),('authority','Purchasing authority'),('timeline','Deployment timeline')]:line(label,status(obj(lead.get(k)).get('status') or 'Unknown'),accent=True)
    st.markdown('<hr class="rule">',unsafe_allow_html=True)
    eyebrow('THE DISCOVERY CONVERSATION')
    st.caption('These are questions for the BDR or AE to ask the buyer. They uncover missing facts; they are not generated answers or a quiz.')
    questions(arr(handoff_out.get('discovery_questions')) or arr(obj(lead.get('budget')).get('questions')),max_items=5)
    st.caption('Priority measures urgency for engagement, not probability of closing. Unknown qualification fields are deliberately shown as unknown.')

elif page=='Account intelligence':
    intro('02','The account, decoded.','Organisation, investment signals, news, and operating priorities—with sources attached.')
    topics=arr(obj(research.get('output')).get('topics'))
    if not topics:notice('Account research was not produced in this execution. Check the research stage details.','caution')
    for i,topic in enumerate(topics,1):
        eyebrow(f'{i:02d} / {topic.get("name") or "Research finding"}')
        claims(topic.get('claims'),sources,demo,max_items=10)
        gaps=arr(topic.get('gaps'))
        if gaps:
            for gap in gaps[:3]:st.markdown(f'<div class="small-gap">OPEN QUESTION · {esc(plain(gap))}</div>',unsafe_allow_html=True)
    pos=arr(obj(research.get('output')).get('positioning'))
    if pos:
        eyebrow('FLYTBASE POSITIONING')
        claims(pos,sources,demo,max_items=5)
    if research.get('warnings'):
        st.markdown('<hr class="rule">',unsafe_allow_html=True)
        eyebrow('RESEARCH VERIFICATION STATUS')
        st.caption('Verification issues are distinct from company research. The analysis above contains the actual research conclusions and source links.')
        warnings_list([research],sources,demo,open_first=False)

elif page=='Outreach studio':
    intro('03','Write with intelligence.','Five buyer-adaptive response paths. Read, edit, copy—and keep a human in control.')
    drafts=arr(obj(outreach.get('output')).get('drafts'))
    if not drafts:notice('No email drafts were generated. Check the Response Generation stage.','caution')
    else:
        labels={'initial':'01 · First response','no_reply':'02 · No reply','interested':'03 · Buyer interested','budget_clarification':'04 · Budget timing','stakeholder_referral':'05 · Stakeholder referral'}
        tabs=st.tabs([labels.get(d.get('branch'),status(d.get('branch','Email'))) for d in drafts])
        for tab,d in zip(tabs,drafts):
            with tab:
                st.markdown(f'<h2 class="email-subject">{esc(d.get("subject") or "Untitled email")}</h2>',unsafe_allow_html=True)
                line('Trigger',d.get('trigger') or 'Not recorded')
                line('Why this email',d.get('why_this_message') or 'Not recorded')
                line('If buyer responds',d.get('if_buyer_responds') or 'Manual follow-up')
                if d.get('hypothetical'):notice('This is a hypothetical follow-up path. It has not been triggered by an actual buyer reply.','caution')
                body='\n\n'.join(plain(c) for c in arr(d.get('paragraphs')) if plain(c))
                full=f'Subject: {d.get("subject","")}\n\n{body}'
                editor_widget(full,f'aether:{run_id}:{d.get("branch") or "email"}')
                st.caption('Review status: '+str(d.get('review_status') or 'Human verification required')+' · No automated sending')
        if arr(outreach.get('warnings')):
            with st.expander(f'Outreach verification notes · {len(outreach.get("warnings",[]))} findings'):
                for w in arr(outreach.get('warnings')):st.markdown(f'<div class="warning-row"><span>!</span><p>{esc(w)}</p></div>',unsafe_allow_html=True)

elif page=='Case studies & partners':
    intro('04','Proof. Then the route.','Case relevance, the Anglo American referral, and implementation ownership.')
    out=obj(cases.get('output')); rows=arr(out.get('comparison'))
    if not out.get('primary'):notice('No primary case study passed every evidence check in this run. The ranked candidates below are research leads for human review.','caution')
    for rank,entry in enumerate(rows[:6],1):
        render_case_decision(entry,sources,demo,f'{rank:02d} / CASE STUDY CANDIDATE')
        if rank < min(6,len(rows)):st.markdown('<hr class="rule">',unsafe_allow_html=True)
    if not rows:notice('No matching candidates were returned in this run.','caution')
    ref=arr(out.get('referral_findings'))
    eyebrow('THE REFERRED CUSTOMER / ANGLO AMERICAN')
    if ref:claims(ref,sources,demo,max_items=4)
    elif not demo:notice('The lead cites Anglo American as a referrer. The relationship and relevant case-study scope should be confirmed before outreach.')
    else:notice('Synthetic referral information is demonstration-only.')
    eyebrow('COMMERCIAL ROUTING')
    route=obj(partners.get('output'))
    st.markdown(f'<div class="lead-proposition">{esc(status(route.get("recommended_motion") or "Undetermined"))}</div>',unsafe_allow_html=True)
    for r in arr(route.get('rationale'))[:4]:st.markdown(f'<div class="bullet-row"><span>↗</span>{esc(plain(r))}</div>',unsafe_allow_html=True)
    line('Commercial owner',plain(route.get('commercial_owner')) or 'Not verified')
    line('Implementation owner',plain(route.get('implementation_owner')) or 'Not verified')
    for c in arr(route.get('candidates')):
        st.markdown(f'<div class="partner"><strong>{esc(c.get("name") or "Potential implementation partner")}</strong><span>{esc(c.get("partner_type") or "Partner type not specified")}</span><p>{esc(c.get("availability") or "Current availability not verified")}</p></div>',unsafe_allow_html=True)
    if route.get('next_action'):st.markdown(f'<div class="small-gap">NEXT ACTION · {esc(route.get("next_action"))}</div>',unsafe_allow_html=True)
    if any(arr(s.get('warnings')) for s in (cases,partners)):
        warnings_list([cases,partners],sources,demo)

elif page=='AE handoff':
    intro('05','A handoff worth reading.','The buyer story, commercial next step, and missing decisions in one briefing.')
    context=obj(handoff_out.get('buyer_context'))
    st.markdown(f'<div class="handoff-banner"><div class="eyebrow">BUYER / ACCOUNT</div><h2>{esc(context.get("company") or name)}</h2><p>{esc(context.get("name") or lead.get("name") or "Unknown buyer")} · {esc(context.get("title") or lead.get("title") or "Role to confirm")} · {esc(context.get("geography") or lead.get("geography") or "Unknown location")}</p></div>',unsafe_allow_html=True)
    eyebrow('THE BUSINESS PROBLEM')
    st.markdown(f'<div class="lead-proposition">{esc(handoff_out.get("business_problem_and_desired_outcome") or lead.get("need") or "Not established")}</div>',unsafe_allow_html=True)
    eyebrow('NEXT STEP — READY FOR THE AE')
    st.markdown(f'<div class="action-panel"><div class="action-tag">RECOMMENDED DISCOVERY ACTION</div><p>{esc(handoff_out.get("suggested_next_action") or "The saved run did not provide a next action.")}</p><div class="sub-reason">{esc(handoff_out.get("why") or "")}</div></div>',unsafe_allow_html=True)
    eyebrow('THREE RESEARCH FINDINGS TO KNOW')
    claims(handoff_out.get('top_three_research_findings'),sources,demo,max_items=3)
    eyebrow('CASE STUDY DECISION')
    case=handoff_out.get('recommended_case_study')
    if case:
        render_case_decision(case,sources,demo,'AE HANDOFF / CASE STUDY')
    else:
        candidates=arr(obj(cases.get('output')).get('comparison'))
        if candidates:render_case_decision(candidates[0],sources,demo,'EVIDENCE-REVIEW CANDIDATE')
        else:notice('No case study was approved. Review source-backed candidates before buyer outreach.','caution')
    eyebrow('DISCOVERY QUESTIONS — FOR THE HUMAN SALES CONVERSATION')
    st.caption('A BDR/AE asks these to fill qualification gaps; the app does not invent the buyer’s answers.')
    questions(handoff_out.get('discovery_questions'),max_items=12)
    eyebrow('HANDOFF LIMITATIONS')
    limits=arr(handoff_out.get('important_limitations'))
    for limit in limits[:12]:st.markdown(f'<div class="small-gap">{esc(plain(limit))}</div>',unsafe_allow_html=True)
    if not limits:notice('No explicit handoff limitations in this saved output; consult upstream stages for uncertainties.')
    export=run_path.parent/'ae-handoff.md' if run_path else None
    if export and export.is_file():st.download_button('↓ Download original AE handoff',export.read_bytes(),file_name='ae-handoff.md',mime='text/markdown')
    else:
        try:
            from flytbase_bdr.reporting import handoff_export
            from flytbase_bdr.models import RunRecord
            content=handoff_export(RunRecord.model_validate(run))
            st.download_button('↓ Download original AE handoff',content,file_name='ae-handoff.md',mime='text/markdown')
        except Exception:st.caption('The original handoff export is available with the source project’s saved runs.')

elif page=='Evidence & audit':
    intro('06','Confidence, not guesswork.','Every source, limitation, and stage outcome remains available for inspection.')
    eyebrow('SIX-STAGE EXECUTION TRAIL')
    for s in arr(run.get('stages')):
        warnings=arr(s.get('warnings'))
        st.markdown(f'<div class="data-line"><span>{esc(s.get("name","Stage"))}</span><strong>{esc(status(s.get("status")))} · {len(warnings)} warning{"s" if len(warnings)!=1 else ""}</strong></div>',unsafe_allow_html=True)
    eyebrow('WHAT NEEDS VERIFICATION — EXPLAINED IN PLAIN LANGUAGE')
    st.caption('These are verification notes from the AI workflow, grouped into topics—not separate business insights. The original detailed notices remain available when needed.')
    warnings_list(arr(run.get('stages')),sources,demo,open_first=False)
    st.markdown('<div id="public-source-register"></div>',unsafe_allow_html=True)
    eyebrow('PUBLIC SOURCE REGISTER')
    if demo:notice('This source register belongs to an offline test and may contain invented fixture URLs. It is not public-source verification.','demo-banner')
    search=st.text_input('Filter sources by company, title or ID',placeholder='e.g., SQM, Anglo American, 2026')
    count=0
    for sid,src in sources.items():
        title=str(src.get('title') or sid)
        if search and search.casefold() not in (sid+' '+title+' '+str(src.get('url',''))).casefold():continue
        count+=1
        if count>100:break
        link=verified_source_url(src.get('url'),title,demo)
        if link:st.markdown(f'<div class="source-entry"><span>{esc(sid)}</span><a href="{esc(link)}" rel="noopener noreferrer" target="_blank">{esc(title)} ↗</a></div>',unsafe_allow_html=True)
        else:st.markdown(f'<div class="source-entry"><span>{esc(sid)}</span>{esc(title)}{" — synthetic fixture" if demo else " — no verified link"}</div>',unsafe_allow_html=True)
    if not count:notice('No sources match this filter.')
    eyebrow('PROVIDER ACCOUNTING / RUN DATA')
    usage=obj(run.get('usage'))
    if usage:st.json(usage,expanded=False)
    else:notice('No provider accounting is attached to this run. Offline simulation consumes no provider credits.')
    st.caption('These values belong to the saved execution. Provider account balances must be checked at the provider.')
    c1,c2=st.columns(2)
    with c1:
        st.download_button('↓ Export authentic run.json',json.dumps(run,indent=2,ensure_ascii=False),file_name=f'{run_id}.json',mime='application/json')
    with c2:
        report=run_path.parent/'report.md' if run_path else None
        if report and report.is_file():st.download_button('↓ Export original report.md',report.read_bytes(),file_name='report.md',mime='text/markdown')

st.markdown(f'<div class="aether-footer"><span>AETHER / INBOUND INTELLIGENCE</span><span>{esc(run_id)} · {"OFFLINE TEST" if demo else "LIVE RUN"} · {esc(status(run.get("status")))}</span></div>',unsafe_allow_html=True)
