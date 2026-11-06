import os
from typing import Literal
from pathlib import Path
from pydantic import Field
from dotenv import load_dotenv
from .models import Record

ROOT = Path(__file__).resolve().parent.parent


class Settings(Record):
    groq_model: str = "openai/gpt-oss-120b"
    compact_account_research: bool = True  # one structured synthesis instead of six costly calls
    project_max_groq_tokens: int = Field(default=40000, ge=1000, le=110000)
    project_max_tavily_credits: int = Field(default=40, ge=1, le=40)
    timeout_seconds: float = Field(default=90, ge=10, le=180)
    max_retries: int = Field(default=1, ge=0, le=2)
    max_output_tokens: int = Field(default=2600, ge=300, le=4800)
    task_aware_tokens: bool = False
    selective_search_depth: bool = False
    rate_safety_margin: float = Field(default=1.0, ge=.8, le=1)
    groq_input_tpm: int | None = Field(default=None, ge=1)
    groq_output_tpm: int | None = Field(default=None, ge=1)
    expanded_research: bool = False
    tavily_search_depth: Literal["basic", "advanced"] = "basic"
    tavily_extract_depth: Literal["basic", "advanced"] = "basic"
    groq_tpm: int = Field(default=8000, ge=1000, le=8000)
    groq_rpm: int = Field(default=25, ge=1, le=30)
    max_request_tokens: int = Field(default=7500, ge=1000, le=7500)
    max_api_requests: int = Field(default=24, ge=1, le=30)
    max_total_input_tokens: int = Field(default=65000, ge=1000, le=100000)
    max_total_output_tokens: int = Field(default=35000, ge=1000, le=60000)
    max_search_requests: int = Field(default=10, ge=1, le=24)
    max_extract_requests: int = Field(default=5, ge=1, le=12)
    max_tavily_credits: int = Field(default=16, ge=1, le=60)
    tavily_rpm: int = Field(default=30, ge=1, le=60)
    max_results_per_query: int = Field(default=3, ge=1, le=5)
    max_source_fetches: int = Field(default=15, ge=1, le=30)
    max_source_chars: int = Field(default=12000, ge=2000, le=18000)
    evidence_chars_per_source: int = Field(default=1800, ge=400, le=2400)
    evidence_chars_per_request: int = Field(default=6000, ge=1000, le=8000)
    max_retry_after_seconds: float = Field(default=90, ge=1, le=180)
    runs_dir: str = "runs"

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        return cls(**{k: os.environ.get(k.upper(), f.default) for k, f in cls.model_fields.items()})

    def run_path(self) -> Path:
        p = Path(self.runs_dir)
        return p if p.is_absolute() else ROOT / p


def credential_status() -> dict[str, bool]:
    load_dotenv(ROOT / ".env", override=False)
    def present(name):
        value = os.environ.get(name, "").strip()
        return len(value) >= 16 and not any(x in value.casefold() for x in ["your_api", "your-api", "placeholder", "your-key", "your_key", "setup-token"])
    return {name: present(name) for name in ["GROQ_API_KEY", "TAVILY_API_KEY"]}


def has_api_key() -> bool:
    """Both independent credentials must exist; values are never returned."""
    return all(credential_status().values())
