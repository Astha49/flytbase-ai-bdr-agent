"""New visual layer regressions. Run using the project's Streamlit-enabled venv."""
from pathlib import Path
from flytbase_bdr.config import ROOT
from flytbase_bdr.ui import e, pill
from scripts.package_source import package
from zipfile import ZipFile


def test_new_ui_escapes_untrusted_text():
    assert e('<script>alert("x")</script>') == '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;'
    assert '<script>' not in e('<script>')


def test_stage_status_is_truthful_and_accessible():
    assert 'Review Needed' in pill('partial')
    assert 'Completed' in pill('complete')
    assert 'Failed' in pill('failed')
    assert 'Queued' in pill('pending')


def test_css_is_shipped_with_source_bundle(tmp_path):
    assert (ROOT / 'assets' / 'theme.css').is_file()
    assert (ROOT / '.streamlit' / 'config.toml').is_file()
    output = package(tmp_path / 'complete.zip')
    with ZipFile(output) as z:
        names = set(z.namelist())
        assert {'app.py', 'assets/theme.css', 'flytbase_bdr/ui.py', '.streamlit/config.toml'} <= names
        assert '.env' not in names
        assert not any(n.startswith('runs/') for n in names)
