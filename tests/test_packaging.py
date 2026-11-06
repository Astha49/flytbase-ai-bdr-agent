from zipfile import ZipFile
import hashlib
import json
from scripts.package_source import package


def test_source_bundle_contains_code_and_excludes_confidential_local_files(tmp_path):
    path = package(tmp_path / "source.zip")
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert "app.py" in names and ".env.example" in names and "pytest.ini" in names
        assert "flytbase_bdr/workflow.py" in names
        assert "flytbase_bdr/providers/groq.py" in names and "flytbase_bdr/providers/tavily.py" in names
        assert not any(n.endswith(".pdf") or n == ".env" or n.startswith(("runs/", ".venv/", "tmp/", ".git/")) for n in names)
        assert not any(n.startswith("docs/SAVED_RUN_REVIEW_") for n in names)
        assert "docs/SUBMISSION_READY.md" in names
        assert "docs/REVIEWER_GUIDE.md" in names and "docs/APPROVED_CONTINUATION.md" in names
        assert "docs/REPAIR_CHECKPOINT.md" not in names
        demo = json.loads(archive.read("examples/recruiter_demo/offline_simulation/run.json"))
        assert demo["mode"] == "offline_test" and not demo["usage"]
        assert "SYNTHETIC OFFLINE SIMULATION" in str(demo["warnings"])
        assert archive.testzip() is None
        for line in archive.read("MANIFEST.sha256").decode().splitlines():
            digest, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_packaging_refuses_any_actual_local_key_in_sources(tmp_path, monkeypatch):
    import pytest
    import scripts.package_source as builder
    root = tmp_path / "project"
    root.mkdir()
    key = "gsk_test_secret_that_must_never_ship_12345"
    (root / ".env").write_text("GROQ_API_KEY=" + key, encoding="utf-8")
    (root / "app.py").write_text("accidental_key = '" + key + "'", encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", root)
    output = tmp_path / "rejected.zip"
    with pytest.raises(ValueError, match="Local credential found"):
        builder.package(output)
    assert not output.exists()
