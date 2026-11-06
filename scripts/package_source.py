"""Create a reviewable source bundle from an explicit allowlist; never include local runs or secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = ["app.py", "README.md", "pytest.ini", "requirements.txt", "requirements-lock.txt", "run_app.cmd", ".gitignore", ".env.example", ".streamlit/config.toml"]
PATTERNS = ["flytbase_bdr/**/*.py", "tests/*.py", "scripts/*.py", "examples/*.txt", "assets/*.css"]
PUBLIC_DOCS = ["ARCHITECTURE.md", "REQUIREMENTS.md", "REVIEWER_GUIDE.md", "APPROVED_CONTINUATION.md",
               "SUBMISSION_READY.md", "WALKTHROUGH_READY_SCRIPT.md", "RESEARCH_VERIFICATION_GUIDE.md"]
DEMO_FILES = ["examples/recruiter_demo/README.md", "examples/recruiter_demo/offline_simulation/run.json",
              "examples/recruiter_demo/offline_simulation/report.md", "examples/recruiter_demo/offline_simulation/verification.json"]


def package(output: Path | None = None) -> Path:
    output = output or ROOT / "dist" / "flytbase-inbound-source.zip"
    files = {ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()}
    for pattern in PATTERNS:
        files.update(ROOT.glob(pattern))
    files = {path for path in files if not path.name.startswith("SAVED_RUN_REVIEW_")}
    files.update(ROOT / name for name in DEMO_FILES if (ROOT / name).is_file())
    files.update(ROOT / "docs" / name for name in PUBLIC_DOCS if (ROOT / "docs" / name).is_file())
    # A public simulation is explicitly allowlisted; never glob private run data.
    demo = ROOT / DEMO_FILES[1]
    if demo.exists():
        record = json.loads(demo.read_text(encoding="utf-8"))
        if record.get("mode") != "offline_test" or "SYNTHETIC OFFLINE SIMULATION" not in str(record.get("warnings", [])):
            raise ValueError("Only the explicitly labelled synthetic demo may be distributed.")
    local = dotenv_values(ROOT / ".env")
    secrets = {value for name in ("GROQ_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY")
               for value in (local.get(name), os.environ.get(name)) if value and len(value) >= 16}
    output.parent.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for path in sorted(files):
        relative = path.relative_to(ROOT)
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Linked/out-of-workspace files are not allowed in the source package.")
        if path.suffix.lower() == ".pdf" or path.name == ".env" or "runs" in relative.parts:
            raise ValueError("Confidential/local file rejected by source bundle policy.")
        content = path.read_bytes()
        if any(secret.encode() in content for secret in secrets):
            raise ValueError(f"Local credential found in {relative.as_posix()}; source package not created.")
        payloads[relative.as_posix()] = content
    required = {"app.py", "README.md", "requirements.txt", ".env.example", "assets/theme.css",
                "flytbase_bdr/workflow.py", "flytbase_bdr/providers/groq.py", "flytbase_bdr/providers/tavily.py"}
    if not required.issubset(payloads):
        raise ValueError("Required runnable source/configuration files are missing; incomplete archive not created.")
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in payloads.items():
            archive.writestr(name, content)
        manifest = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n" for name, content in payloads.items())
        archive.writestr("MANIFEST.sha256", manifest)
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Source archive failed CRC verification.")
    return output


if __name__ == "__main__":
    print(package())
