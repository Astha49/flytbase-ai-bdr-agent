"""AETHER's opt-in live runner for *any* inbound buyer email.

No provider work occurs in approval or preview. Each new enquiry gets a distinct,
ledger-bound allowance and requires a second, explicit launch action. Existing
FlytBase original runs and budget history remain immutable and shared.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import uuid

from flytbase_bdr.config import Settings
from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.run_allowance import (
    AllowanceError, stamp, daily_count, pending, reserve_floor,
)
from flytbase_bdr.provider import QuotaExhausted


def fingerprint(enquiry: str) -> str:
    return hashlib.sha256(enquiry.strip().encode('utf-8')).hexdigest()


def safe_observation(usage: int) -> dict:
    return {'checked_at': stamp().isoformat(), 'used_tokens': usage, 'daily_limit': 200000,
            'tpm': 8000, 'basis': 'operator-confirmed current Free dashboard; not independently queried',
            'paid_billing': False}


def approve_enquiry(settings: Settings, enquiry: str, used_today: int, groq_cap: int, tavily_cap: int,
                    *, free_only: bool, approved_budget: bool) -> dict:
    """Reserve a bounded future run. No API calls or automatic start."""
    enquiry = enquiry.strip()
    if not 1 <= len(enquiry) <= 16000:
        raise AllowanceError('Paste an inbound enquiry (up to 16,000 characters).')
    if not free_only or not approved_budget:
        raise AllowanceError('Explicit free-only confirmation and budget approval are required.')
    if not isinstance(used_today, int) or not 0 <= used_today <= 200000:
        raise AllowanceError('Enter today’s Groq token usage from the refreshed provider dashboard.')
    if not 8000 <= groq_cap <= 63000 or not 1 <= tavily_cap <= 16:
        raise AllowanceError('Fresh-run cap must be 8,000–63,000 Groq tokens and 1–16 Tavily credits.')
    observed = safe_observation(used_today)
    budget = ProjectBudget(settings)
    with budget.locked():
        data = budget.read()
        if not budget.path.exists():
            raise AllowanceError('The original protected project ledger was not found. Connect the original project first.')
        digest = fingerprint(enquiry)
        if any(a.get('kind') == 'fresh_enquiry' and a.get('enquiry_sha256') == digest
               and a.get('state') in {'approved', 'started'} and a.get('utc_day') == stamp().date().isoformat()
               for a in data.get('execution_allowances', [])):
            raise AllowanceError('An approved or running allowance already exists for this enquiry.')
        safe_usage = daily_count(data, observed)
        if safe_usage + pending(data) + groq_cap + reserve_floor(data) > 200000:
            possible = max(0, 200000 - safe_usage - pending(data) - reserve_floor(data))
            raise QuotaExhausted(f'Free daily quota guard allows at most {possible:,} new Groq tokens; requested {groq_cap:,}.')
        item = {'id': 'fresh-'+uuid.uuid4().hex[:12], 'kind': 'fresh_enquiry',
                'state': 'approved', 'created_at': stamp().isoformat(),
                'utc_day': stamp().date().isoformat(), 'groq_tokens': groq_cap, 'groq_requests': 24,
                'tavily_credits': tavily_cap, 'tavily_requests': 16, 'enquiry_sha256': digest,
                'source_run': '', 'source_sha256': digest, 'model': settings.groq_model,
                'run_id': '', 'quota_observation': observed,
                'approval': 'Separate operator budget approval; live launch requires a second click'}
        data.setdefault('execution_allowances', []).append(item)
        budget.write(data)
        return item


def execute_enquiry(settings: Settings, enquiry: str, allowance_id: str, *, approved: bool,
                    on_update=None):
    """Start exactly one live run against the original ledger and saved-runs folder."""
    if not approved:
        raise AllowanceError('Explicit live launch approval required.')
    from flytbase_bdr.execution import approved_live_execution
    from flytbase_bdr.workflow import Workflow, new_run
    from flytbase_bdr.reporting import load_run, save_run
    enquiry = enquiry.strip()
    budget = ProjectBudget(settings)
    with budget.locked():
        data = budget.read()
        item = next((a for a in data.get('execution_allowances', []) if a.get('id') == allowance_id), None)
        if not item or item.get('kind') != 'fresh_enquiry' or item.get('state') != 'approved':
            raise AllowanceError('This enquiry needs an unused, explicitly approved fresh-run allowance.')
        if item['utc_day'] != stamp().date().isoformat() or item['enquiry_sha256'] != fingerprint(enquiry):
            raise AllowanceError('Allowance expired or input changed. Approval is tied to the exact enquiry.')
        if item['model'] != settings.groq_model:
            raise AllowanceError('The approved model has changed.')
        when = datetime.fromisoformat(item['quota_observation']['checked_at'])
        if not -60 <= (stamp()-when).total_seconds() <= 900:
            raise AllowanceError('Provider usage check is older than 15 minutes. Obtain fresh approval.')
        if daily_count(data, item['quota_observation']) + pending(data, allowance_id) + reserve_floor(data) > 200000:
            raise QuotaExhausted('Protected daily headroom no longer sufficient.')
        profile = settings.model_copy(update={
            'max_retries': 0, 'task_aware_tokens': True, 'compact_account_research': True,
            'expanded_research': False, 'max_output_tokens': 3200,
            'max_api_requests': min(settings.max_api_requests, item['groq_requests']),
            'max_tavily_credits': min(settings.max_tavily_credits, item['tavily_credits']),
            'max_search_requests': min(settings.max_search_requests, 10),
            'max_extract_requests': min(settings.max_extract_requests, 5),
            'max_total_input_tokens': min(settings.max_total_input_tokens, item['groq_tokens']),
            'max_total_output_tokens': min(settings.max_total_output_tokens, item['groq_tokens']),
            'groq_tpm': min(settings.groq_tpm, 8000), 'groq_rpm': min(settings.groq_rpm, 25),
            'rate_safety_margin': min(settings.rate_safety_margin, .9),
        })
        fresh = new_run(enquiry, profile, mode='live')
        item['state'], item['run_id'], item['started_at'] = 'started', fresh.run_id, stamp().isoformat()
        budget.write(data)
    result = None
    try:
        with approved_live_execution(True, phase='new_run', allowance_id=allowance_id, confirmed_free_quota=True):
            result = Workflow(profile).execute(enquiry, resume=fresh,
                                              rerun_stages=set(range(6)), on_update=on_update)
            return result
    except (Exception, KeyboardInterrupt) as exc:
        saved = settings.run_path() / fresh.run_id / 'run.json'
        failed = load_run(saved) if saved.exists() else fresh
        failed.status, failed.finished_at = 'failed', stamp().isoformat()
        for stage in failed.stages:
            if stage.status in {'pending', 'running'}:
                stage.status = 'failed' if stage.status == 'running' else 'skipped'
        failed.warnings.append(f'Interrupted ({type(exc).__name__}); inspect saved results. No automatic retry.')
        save_run(failed, settings.run_path())
        raise
    finally:
        with budget.locked():
            data = budget.read()
            entry = next(a for a in data['execution_allowances'] if a.get('id') == allowance_id)
            entry['state'], entry['finished_at'] = 'finished', stamp().isoformat()
            entry['result_status'] = result.status if result else 'failed'
            budget.write(data)
