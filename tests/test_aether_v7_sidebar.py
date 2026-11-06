"""Navigation regressions: native Streamlit toggles plus AETHER fallback."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_sidebar_native_control_preserved():
    css=(ROOT/'assets'/'aether.css').read_text(encoding='utf8')
    assert '[data-testid="stToolbar"]{visibility:visible' in css
    assert 'visibility:hidden!important;height:0!important' not in css
    assert '[data-testid="stSidebarCollapsedControl"]' in css

def test_persistent_toggle_has_accessible_open_close_paths():
    code=(ROOT/'aether_app.py').read_text(encoding='utf8')
    for phrase in ('aether-navigation-toggle','Open navigation sidebar',
                   'Close navigation sidebar','stSidebarCollapsedControl',
                   'native.click()', 'MutationObserver'):
        assert phrase in code

def test_new_version_parallel_port():
    script=(ROOT/'START_AETHER.ps1').read_text(encoding='utf8')
    assert '--server.port 8506' in script
