"""Visual-only structural checks. No imports of providers or API calls."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_editorial_chapters_are_wired_into_evaluator_pages():
    app = (ROOT/'app.py').read_text(encoding='utf-8')
    ui = (ROOT/'flytbase_bdr/ui.py').read_text(encoding='utf-8')
    for view in ('research', 'strategy', 'handoff'):
        assert f'narrative_masthead("{view}")' in app
    assert 'story_ribbon()' in app
    assert 'def narrative_masthead(view: str)' in ui

def test_theme_is_consistent_and_respects_motion_preferences():
    css = (ROOT/'assets/theme.css').read_text(encoding='utf-8')
    config = (ROOT/'.streamlit/config.toml').read_text(encoding='utf-8')
    for selector in ('.fb-mast-mint','.fb-mast-lilac','.fb-mast-peach',
                     '.fb-story-ribbon','.fb-evidence-experience','.fb-access-experience'):
        assert selector in css
    assert 'prefers-reduced-motion' in css
    assert 'primaryColor = "#0B927B"' in config
    assert 'GROQ_API_KEY=' not in css and 'TAVILY_API_KEY=' not in css
