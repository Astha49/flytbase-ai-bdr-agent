"""Read-only local bottleneck diagnostic: no provider calls, no secrets printed."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def diagnose(path):
    p = Path(path)
    if p.is_dir():
        files = list(p.glob('*/run.json'))
        if not files:
            raise SystemExit('No saved run.json found.')
        p = max(files, key=lambda x: x.stat().st_mtime)
    data = json.loads(p.read_text(encoding='utf-8'))
    print(f"RUN {data.get('run_id')} | {data.get('status')} | mode={data.get('mode')}")
    start = data.get('started_at', '')
    if start:
        try:
            dt = datetime.fromisoformat(start.replace('Z','+00:00'))
            print(f"Elapsed since launch: {(datetime.now(timezone.utc)-dt).total_seconds()/60:.1f} minutes")
        except (ValueError, TypeError):
            pass
    age = (datetime.now(timezone.utc).timestamp()-p.stat().st_mtime)
    print(f"Last saved checkpoint: {age:.0f} seconds ago")
    print('Stages:')
    for i,s in enumerate(data.get('stages', []),1):
        print(f"  {i}. {s.get('name')}: {s.get('status')}; {s.get('elapsed_seconds', '')}s; output={'yes' if s.get('output') else 'no'}")
    groq = [u for u in data.get('usage',[]) if u.get('provider')=='groq']
    print(f"Groq completed HTTP responses: {len(groq)}")
    for u in groq[-8:]:
        print(f"  {u.get('purpose')}: {u.get('total_tokens','?')} tokens; HTTP {u.get('elapsed_seconds','?')}s")
    cached = data.get('retrieval_cache',{}).get('_structured', {})
    print('Saved structured AI responses:', ', '.join(cached) or 'none')
    print('Recent activity (types, purposes, durations only):')
    for x in data.get('logs',[])[-18:]:
        fields = [f'{k}={x[k]}' for k in ('event','stage','purpose','seconds','status_code','type') if k in x]
        print('  ' + ' '.join(fields))
    if data.get('status')=='running' and age > 180:
        print('WARNING: checkpoint has not changed in over three minutes. A stalled/abandoned worker is possible.')
        print('Do not assume the workflow will finish. Inspect worker status before any continuation.')
    print('Read-only inspection completed. Zero API requests.')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('path',nargs='?',default='runs',help='A specific run.json, or a runs directory')
    diagnose(ap.parse_args().path)
