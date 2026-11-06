import json
from pathlib import Path
from flytbase_bdr.models import Audit, AuditFinding, Research, STAGE_NAMES
from flytbase_bdr.provider import ProviderError
from flytbase_bdr.reporting import json_export, markdown_export, load_run, save_run
from flytbase_bdr.workflow import Workflow
from conftest import FakeProvider, fake_fetch


def test_all_six_stages_dependency_order_and_export_parity(settings, enquiry):
    instances = []
    def factory(cfg, run):
        p = FakeProvider(cfg, run)
        instances.append(p)
        return p
    snapshots = []
    run = Workflow(settings, factory, fake_fetch, research_factory=FakeProvider).execute(enquiry, lambda r: snapshots.append(r.model_copy(deep=True)), mode="offline_test")
    assert run.status == "partial"  # only one unique research finding, never fabricate three
    assert [s.name for s in run.stages] == STAGE_NAMES
    assert all(s.status in {"complete", "partial"} for s in run.stages)
    running = [r.stages[next(i for i, s in enumerate(r.stages) if s.status == "running")].name
               for r in snapshots if any(s.status == "running" for s in r.stages)]
    unique_order = list(dict.fromkeys(running))
    assert unique_order == [STAGE_NAMES[i] for i in [0, 1, 3, 4, 2, 5]]
    emails_input = next(data for purpose, data in instances[0].received if purpose == "email drafts")
    assert emails_input["material"]["source_id"]
    assert "research_findings" in emails_input and "routing" in emails_input
    folder = settings.run_path() / run.run_id
    saved = load_run(folder / "run.json")
    assert json.loads(json_export(run)) == saved.model_dump(mode="json")
    assert (folder / "report.md").read_text(encoding="utf-8") == markdown_export(run)
    report = markdown_export(run)
    assert run.run_id in report and run.input.splitlines()[0] in report
    for sid in run.sources:
        assert f"[{sid}](" in report
    assert saved.stages[5].output["qualification"] == saved.stages[0].output


def test_provider_failure_is_failed_and_downstream_skipped(settings, enquiry):
    def factory(*args):
        raise ProviderError("Credential unavailable.")
    run = Workflow(settings, factory, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    assert run.status == "failed"
    assert run.stages[0].status == "failed"
    assert all(s.status == "skipped" and not s.output for s in run.stages[1:])


def test_search_failure_cannot_become_success(settings, enquiry):
    class FailedSearch(FakeProvider):
        def search(self, *args, **kwargs):
            raise ProviderError("Research provider failed.")
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FailedSearch).execute(enquiry, mode="offline_test")
    assert run.status == "partial"
    assert run.stages[1].status == "failed"  # no original evidence from account search
    assert run.stages[3].status == "failed"  # no material inspected
    assert run.stages[4].status == "partial"  # explicit direct-AE safety fallback, NOT verified partner discovery
    assert run.stages[4].warnings
    assert not run.stages[1].output
    assert run.stages[2].status == "partial"
    assert not run.stages[5].output["top_three_research_findings"]
    assert not run.stages[5].output["recommended_case_study"]
    assert run.warnings


def test_semantic_audit_failure_withholds_case_partner_and_public_handoff(settings, enquiry):
    class NoAudit(FakeProvider):
        def structured(self, schema, *args, **kwargs):
            if schema is Audit:
                raise ProviderError("Audit unavailable.")
            return super().structured(schema, *args, **kwargs)
    run = Workflow(settings, NoAudit, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    assert run.status == "partial"
    assert run.stages[3].output["primary"] is None
    assert not run.stages[5].output["top_three_research_findings"]


def test_semantic_unsupported_claim_is_not_promoted_to_handoff(settings, enquiry):
    class FlagResearch(FakeProvider):
        def structured(self, schema, instruction, data, purpose, **kwargs):
            if schema is Audit and purpose == "audit:account":
                return Audit(findings=[AuditFinding(path=f"output.topics[{i}].claims[0].text", reason="Quote does not support the assertion.", severity="error") for i in range(5)])
            return super().structured(schema, instruction, data, purpose)
    run = Workflow(settings, FlagResearch, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    assert not run.stages[5].output["top_three_research_findings"]
    assert run.stages[1].status == "partial"


def test_changed_enquiry_changes_extraction_and_run_queries(settings, enquiry):
    first = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    changed = enquiry.replace("Rodrigo Castillo", "Example Buyer").replace("r.castillo@sqm.cl", "buyer@example.test").replace(
        "Sociedad Quimica y Minera de Chile (SQM), Chile", "Example Copper, Peru")
    second = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(changed, mode="offline_test")
    assert first.run_id != second.run_id
    assert second.stages[0].output["lead"]["company"] == "Example Copper"
    assert first.queries != second.queries
    assert "Peru" in second.queries["partners"][0]


def test_secrets_are_redacted_in_both_exports(settings, enquiry, monkeypatch):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    secret = "sk-synthetic_secret_for_redaction_testing_only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    run.logs.append({"message": secret, "authorization": "Bearer " + secret})
    assert secret not in json_export(run)
    assert secret not in markdown_export(run)
    assert "[REDACTED]" in json_export(run)
    assert "redaction_testing_only" not in markdown_export(run)


def test_arbitrary_exceptions_do_not_leak_into_saved_record(settings, enquiry):
    def bad_factory(*args):
        raise ValueError("Authorization: secret-header-value")
    run = Workflow(settings, bad_factory, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    assert "secret-header-value" not in json_export(run)


def test_resume_reuses_successful_stages_without_new_inference_or_search(settings, enquiry):
    run = Workflow(settings, FakeProvider, fake_fetch, research_factory=FakeProvider).execute(enquiry, mode="offline_test")
    class Forbidden(FakeProvider):
        def structured(self, *args, **kwargs):
            raise AssertionError("Successful saved stages must be preserved")
        def search(self, *args, **kwargs):
            raise AssertionError("Cached stages must not search again")
    resumed = Workflow(settings, Forbidden, fake_fetch, research_factory=Forbidden).execute(enquiry, mode="offline_test", resume=run)
    assert resumed.run_id == run.run_id
    assert resumed.stages[0].output == run.stages[0].output
    assert all("cached stage" in s.execution_origin for s in resumed.stages)
