"""Offline-only regression for live Groq's documented materials JSON truncation."""
import json

from flytbase_bdr.models import MaterialChoice
from flytbase_bdr.providers.groq import structured_payload, strict_schema
from flytbase_bdr.provider import estimate_tokens
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider


def test_compact_material_choice_request_is_small_and_strict(settings):
    payload, cap = structured_payload(
        MaterialChoice, "Compare these two case references and return each required field.",
        {"lead": {"industry": "mining", "geography": "Chile"},
         "cases": [{"source_id": "S_example", "title": "Fictional mining inspection",
                    "dimensions": [{"name": "industry", "matched": True,
                                    "exact_quote": "Example mine uses drone inspection."}]}]},
        settings, "material comparison", max_tokens=950,
    )
    assert cap == 950
    assert strict_schema(MaterialChoice)["additionalProperties"] is False
    assert set(strict_schema(MaterialChoice)["required"]) == {
        "preferred_source_id", "ranked_source_ids", "rationale", "gaps"
    }
    assert estimate_tokens(json.dumps(payload)) + cap < settings.max_request_tokens


def test_compact_material_choice_executes_with_mocked_provider(settings, enquiry):
    class CompactCaseFake(FakeProvider):
        supports_compact_material_comparison = True
        def search(self, queries, purpose, as_of_date, domains=None):
            if purpose == "search:materials":
                return {"results": [{"url": "https://flytbase.com/case-studies/sqm-fixture",
                                     "title": "SQM mine inspection synthetic test",
                                     "content": "Synthetic offline case-study snippet"}]}
            return super().search(queries, purpose, as_of_date, domains)

        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is MaterialChoice:
                assert purpose == "material comparison"
                assert data["cases"] and len(data["cases"]) <= 2
                assert kwargs["max_tokens"] == 950
                return MaterialChoice(preferred_source_id=data["cases"][0]["source_id"],
                                      ranked_source_ids=[data["cases"][0]["source_id"]],
                                      rationale="Inspection use case at a mine is relevant; sites need confirmation.",
                                      gaps=["Confirm whether requested sites are the published sites."])
            return super().structured(schema, instruction, data, purpose, **kwargs)

    def fetched(src, max_chars):
        src.access = "inspected_page"
        src.text = ("SQM operates mining facilities in Chile. A mining team deploys drones "
                    "to inspect leaching piles and irrigation systems. " * 8)
        src.publication_date = "2026-01-01"

    run = Workflow(settings, CompactCaseFake, fetched, research_factory=CompactCaseFake).execute(
        enquiry, mode="offline_test"
    )
    stage = run.stages[3]
    assert stage.output.get("ai_case_comparison"), (stage.status, stage.warnings)
    assert stage.output["ai_case_comparison"]["status"].startswith("advisory")
    assert stage.technical_status == "succeeded"
    assert not any("deterministic fallback" in w for w in stage.warnings)
