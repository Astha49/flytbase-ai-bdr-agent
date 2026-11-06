"""Code-only invariants for the evaluator-first presentation layer."""
from pathlib import Path
from flytbase_bdr.config import ROOT


def test_main_page_is_evaluator_focused():
    code = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "Command Center" in code
    assert "Account Intelligence" in code
    assert "Sales Strategy" in code
    assert "AE Handoff" in code
    assert "How It Works & Evidence" in code
    assert "Operator Tools" in code
    assert "full run data" not in code.lower()


def test_api_secrets_not_present_in_public_demo():
    files = list((ROOT / "examples" / "recruiter_demo").rglob("*"))
    for path in files:
        if not path.is_file() or path.suffix not in {".json", ".md", ".txt"}:
            continue
        contents = path.read_text(encoding="utf-8")
        assert "GROQ_API_KEY=" not in contents
        assert "TAVILY_API_KEY=" not in contents


def test_marketing_ui_explicitly_distinguishes_fictional_vs_live():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "fictional simulation is not a verified live result" in app
    assert "no paid provider fallback" in app.lower() or "No paid provider fallback" in app
