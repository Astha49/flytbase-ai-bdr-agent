"""Release guards for v6 presentation. Offline, with zero API calls."""
from pathlib import Path
import json
import time

from aether_helpers import cached_saved_run
from flytbase_bdr.evidence import derive_queries
from flytbase_bdr.models import Lead

ROOT = Path(__file__).resolve().parents[1]


def test_email_editor_has_scrollable_fallback_and_autoresize():
    source = (ROOT / 'aether_app.py').read_text(encoding='utf-8')
    assert 'components.html(widget,height=height,scrolling=True)' in source
    assert 'streamlit:setFrameHeight' in source
    assert 'new ResizeObserver(resize)' in source
    assert 'let editing=false' in source


def test_anchors_and_sidebar_spacing():
    styles = (ROOT / 'assets/aether.css').read_text(encoding='utf-8')
    assert 'h1 a[href^="#"]' in styles
    assert 'stHeaderActionElements' in styles
    assert 'padding:.72rem 1.6rem' in styles


def test_saved_json_cache_invalidates_on_file_change(tmp_path):
    p = tmp_path / 'run.json'
    p.write_text(json.dumps({'run_id':'one', 'stages': []}), encoding='utf8')
    stat=p.stat()
    first=cached_saved_run(str(p.resolve()),stat.st_mtime_ns,stat.st_size)
    assert cached_saved_run(str(p.resolve()),stat.st_mtime_ns,stat.st_size) is first
    p.write_text(json.dumps({'run_id':'updated', 'stages': []}), encoding='utf8')
    stat2=p.stat()
    assert cached_saved_run(str(p.resolve()),stat2.st_mtime_ns,stat2.st_size)['run_id']=='updated'


def test_new_enquiry_uses_original_message_and_new_run():
    live=(ROOT/'aether_live.py').read_text(encoding='utf8')
    assert 'fresh = new_run(enquiry, profile, mode=\'live\')' in live
    assert 'Workflow(profile).execute(enquiry, resume=fresh' in live
    assert 'enquiry_sha256' in live and 'fingerprint(enquiry)' in live
    assert "'fresh_enquiry'" in live
    assert 'source_run' in live


def test_different_company_queries_change_without_static_sqm_data(lead):
    a=derive_queries(lead,'2026-11-06')
    lead.company='Aurora Ports International'
    lead.domain='auroraports.example'
    lead.geography='Singapore'
    lead.industry='Maritime logistics'
    lead.need='Automated container yard security and inspections'
    lead.referral=''
    b=derive_queries(lead,'2026-11-06')
    assert a != b
    assert 'Aurora Ports International' in str(b)
    assert 'Singapore' in str(b)
    assert 'SQM' not in str(b)
    assert 'Anglo American' not in str(b)
