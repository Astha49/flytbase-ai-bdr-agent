"""Explicit dependency order, shared evidence and checkpointed run records."""
import json
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from . import prompts
from .config import Settings
from .evidence import derive_queries, search_sources, rank_sources, fetch_source, evidence_payload, now, is_flytbase, is_issuer_document
from .grounding import audit_mechanical, iter_claims, supported, resolve_audit_path, path_affects_claim
from .models import Audit, Lead, Materials, MaterialChoice, Research, Responses, Routing, Run, Topic, AccountAdvice
from .provider import ProviderError, QuotaExhausted
from .providers.groq import GroqProvider
from .providers.tavily import TavilyProvider
from .compact import lead_context, evidence_batch, audit_batches
from .normalization import normalize_claims
from .qualification import qualify
from .selection import select_materials, decide_routing
from .diagnostics import own_company_mentions
from .review import cleared_claims, handoff_highlights


def new_run(enquiry: str, settings: Settings, mode="live") -> Run:
    if not enquiry.strip() or len(enquiry) > 16000:
        raise ValueError("Enter an enquiry between 1 and 16,000 characters.")
    return Run(run_id=datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:10],
               mode=mode, started_at=now(), as_of_date=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(),
               input=enquiry, config=settings.model_dump())


def fork_resume(original, settings):
    """Write an approved continuation to a new record and preserve its historical source run."""
    run = original.model_copy(deep=True)
    fresh = new_run(original.input, settings, original.mode)
    run.run_id, run.started_at, run.finished_at = fresh.run_id, fresh.started_at, ""
    run.as_of_date = fresh.as_of_date
    # Historical calls belong to the immutable source run. Counting them here
    # exhausted a continuation's per-run limits before any new work was sent.
    previous_usage = run.usage
    run.usage = []
    previous_warnings = run.warnings
    run.warnings = []
    for stage in run.stages:
        if stage.output:
            stage.execution_origin = "cached from historical run; not fresh execution"
    run.logs.append({"event": "forked_resume", "source_run_id": original.run_id, "at": now(),
                     "historical_usage_records": len(previous_usage),
                     "historical_run_warnings": previous_warnings,
                     "historical_groq_tokens": sum(u.get("total_tokens", 0) or 0 for u in previous_usage if u.get("provider") == "groq"),
                     "note": "Usage in this fork records new requests only; original ledger/run usage retained."})
    return run


class Workflow:
    def __init__(self, settings: Settings, provider_factory=GroqProvider, fetcher=fetch_source, research_factory=TavilyProvider):
        self.settings, self.provider_factory, self.fetcher = settings, provider_factory, fetcher
        self.research_factory = research_factory

    def execute(self, enquiry: str, on_update=None, mode="live", resume=None, rerun_stages=None, refresh_research=None) -> Run:
        from .reporting import save_run
        from .execution import current_execution_phase
        from .budget import ProjectBudget
        demo_budget, seeded_research = None, False
        resuming_started_demo = False
        if mode == "live" and current_execution_phase() == "demo" and ProjectBudget(self.settings).demo_summary():
            from .final_demo import demo_settings
            envelope = ProjectBudget(self.settings).demo_summary()
            if envelope.get("quota_confirmation_required"):
                from .execution import free_quota_confirmed
                if not free_quota_confirmed():
                    raise ProviderError("Fourth demo requires current free-dashboard confirmation before fresh execution or same-run recovery. No request sent.")
            self.settings = demo_settings(self.settings, envelope)
            demo_budget = ProjectBudget(self.settings)
            envelope = demo_budget.demo_summary()
            if resume is not None:
                # Recovery is permitted ONLY for the SAME previously approved run,
                # against its ORIGINAL remaining allowance. A different/new run,
                # or a finished demo, must not use the one-time envelope.
                if envelope.get("state") != "started" or envelope.get("run_id") != resume.run_id:
                    raise ProviderError("Demo recovery requires the exact started run ID and its unchanged allowance. No request sent.")
                if resume.mode != "live" or resume.input != enquiry or resume.status != "running":
                    raise ProviderError("Demo recovery requires an unfinished live checkpoint with the identical enquiry.")
                resuming_started_demo = True
        run = resume.model_copy(deep=True) if resume else new_run(enquiry, self.settings, mode)
        if demo_budget and not resuming_started_demo:
            demo_budget.start_final_demo(run.run_id)
            from .final_demo import research_seed
            seed = research_seed(self.settings, enquiry)
            if seed:
                run.sources = {sid: src.model_copy(deep=True) for sid, src in seed.sources.items()}
                run.retrieval_cache = {g: dict(seed.retrieval_cache[g]) for g in ("organisation", "finance", "current", "materials", "partners")
                                       if g in seed.retrieval_cache}
                seeded_research = True
                run.warnings.append(f"LIVE AI generation begins with cached research from {seed.run_id}; original inspection timestamps retained. New searches/inspections are logged separately. No saved stage answers are replayed.")
                run.logs.append({"event": "demo_research_seed", "source_run_id": seed.run_id,
                                 "groups": list(run.retrieval_cache), "stage_outputs_reused": False, "model_responses_reused": False})
        elif resuming_started_demo:
            # Do not call start_final_demo twice, clone a run, or clear its
            # checkpoint/cache. A completed Groq extraction is reused only if
            # its exact prompt, schema and system fingerprint still match.
            run.logs.append({"event": "same_run_demo_recovered", "run_id": run.run_id, "at": now(),
                             "note": "Operator restarted the interrupted process. Only missing stages/model calls run; historical receipts retained."})
        if resume and enquiry != run.input:
            raise ValueError("Resume requires the identical enquiry; changed inputs require a new run.")
        rerun = set(rerun_stages or [])
        group_owners = {"organisation": 1, "finance": 1, "current": 1, "materials": 3, "partners": 4}
        rerun.update(group_owners[g] for g in refresh_research or [] if g in group_owners)
        if resume:
            rerun.update(i for i, item in enumerate(run.stages) if item.status in {"failed", "skipped", "pending"})
            if 0 in rerun:
                rerun.update(range(6))
            if rerun.intersection({1, 3, 4}):
                rerun.update({2, 5})
            if 2 in rerun:
                rerun.add(5)
            run.status, run.finished_at = "running", ""
            run.logs.append({"event": "resume", "at": now(), "rerun_stages": sorted(rerun), "prior_config": run.config})
            run.config = self.settings.model_dump()
            for index in rerun:
                run.stages[index].status = "pending"
                run.stages[index].technical_status = "not_run"
                run.stages[index].elapsed_seconds = 0
                run.stages[index].started_at = run.stages[index].finished_at = ""
                run.stages[index].execution_origin = "queued for revalidation; previous output retained until replaced"
        # Cache-first retry preserves paid-for research. Only an explicit
        # refresh flag requests new retrieval for a named topic.
        refresh_groups = set(refresh_research or [])
        if demo_budget and self.settings.expanded_research and not resuming_started_demo:
            refresh_groups.update({"organisation", "finance", "current"})
            run.logs.append({"event": "fourth_demo_research_refresh", "groups": sorted(refresh_groups),
                             "note": "Fresh discovery for current account topics; original inspected sources remain reusable with their dates."})
        if resume:
            if refresh_groups and run.stages[0].output.get("lead"):
                # Apply improved query-generation code to a saved run; the
                # company's identity still comes only from the same enquiry.
                prior_queries = dict(run.queries)
                updated_queries = derive_queries(Lead.model_validate(run.stages[0].output["lead"]), run.as_of_date, self.settings.expanded_research, self.settings.task_aware_tokens)
                for group in refresh_groups:
                    run.queries[group] = updated_queries[group]
                run.logs.append({"event": "search_plan_regenerated_for_explicit_retry",
                                 "groups": sorted(refresh_groups), "prior_queries": prior_queries})
        fetch_count = 0
        provider = None
        research_provider = None

        def checkpoint():
            save_run(run, self.settings.run_path())
            if on_update:
                on_update(run)

        def synthesize(schema, instruction, data, purpose, **kwargs):
            """Persist each successful structured call before later audits can fail."""
            import hashlib
            signature = json.dumps({"model": self.settings.groq_model, "system": prompts.SYSTEM, "schema": schema.model_json_schema(),
                                    "instruction": instruction, "data": data}, sort_keys=True, ensure_ascii=False)
            fingerprint = hashlib.sha256(signature.encode()).hexdigest()
            cache = run.retrieval_cache.setdefault("_structured", {})
            saved = cache.get(purpose)
            if resume and saved and saved.get("fingerprint") == fingerprint:
                run.logs.append({"event": "structured_call_reused", "purpose": purpose, "origin": "cached; not a fresh model response"})
                return schema.model_validate(saved["output"])
            value = provider.structured(schema, instruction, data, purpose, **kwargs)
            cache[purpose] = {"fingerprint": fingerprint, "output": value.model_dump(), "at": now(),
                              "note": "Schema-valid model response; factual validation remains separate."}
            checkpoint()
            return value

        def stage(index, action):
            item = run.stages[index]
            if resume and index not in rerun and item.output and item.status in {"complete", "partial"}:
                item.execution_origin = "cached stage from saved run; not fresh execution"
                run.logs.append({"event": "stage_reused", "stage": item.name})
                checkpoint()
                return
            item.output, item.warnings = {}, []
            item.technical_status, item.evidence_status = "not_run", "not_assessed"
            item.execution_origin = ("local deterministic handoff; no provider request" if index == 5 else "fresh live provider execution") if mode == "live" else "offline test fixture"
            item.status, item.started_at = "running", now()
            start = time.monotonic()
            checkpoint()
            try:
                output, warnings = action()
                item.output, item.warnings = output, list(dict.fromkeys(warnings))
                audit_state = output.get("groundedness", {}).get("semantic_review", "performed" if index in {0, 5} else "not_assessed")
                item.technical_status = "partial" if output.get("technical_issues") or audit_state != "performed" else "succeeded"
                if item.technical_status == "partial" and not item.warnings:
                    item.warnings.append("Technical processing or semantic verification did not complete; output remains provisional.")
                item.status = "partial" if item.warnings else "complete"
                item.evidence_status = "partial" if item.warnings else "supported"
            except Exception as exc:
                item.status = "failed"
                item.technical_status, item.evidence_status = "failed", "not_assessed"
                # Only our own provider messages are persisted; SDK/server exceptions can contain sensitive content.
                message = str(exc) if isinstance(exc, ProviderError) else f"{type(exc).__name__}: stage did not complete; inspect code/configuration locally."
                item.warnings.append(message)
                run.logs.append({"event": "stage_error", "stage": item.name, "type": type(exc).__name__, "message": message})
            item.finished_at, item.elapsed_seconds = now(), round(time.monotonic() - start, 2)
            checkpoint()

        def search(group, domains=None):
            nonlocal fetch_count, research_provider
            cached = run.retrieval_cache.get(group)
            if (resume or seeded_research) and group not in refresh_groups and cached and cached.get("queries") == run.queries[group]:
                run.logs.append({"event": "retrieval_reused", "group": group, "note": "cached research; not a fresh search"})
                lead_details = run.stages[0].output["lead"]
                available = [sid for sid in cached["source_ids"] if sid in run.sources]
                ids = rank_sources(available, run.sources, group, lead_details.get("company", ""),
                                   lead_details.get("domain", ""), lead_details.get("referral", ""))
                if group in {"organisation", "finance"}:
                    ids = [sid for sid in ids if is_issuer_document(run.sources[sid], lead_details.get("company", ""), lead_details.get("domain", ""))]
                problems = list(cached.get("warnings", []))
                if len(ids) != len(available):
                    problems.append(f"{group}: cached duplicate or unrelated-issuer sources excluded; no fresh retrieval performed.")
                if not ids:
                    raise ProviderError(f"{group}: cached research contains no relevant sources; explicit refresh required.")
                return ids, problems
            if research_provider is None:
                research_provider = self.research_factory(self.settings, run)
            result = research_provider.search(run.queries[group], f"search:{group}", run.as_of_date, domains)
            ids = search_sources(result, run.queries[group], run.sources)
            # Researcher-supplied URL hints are merely discovery leads. They are
            # never trusted as inspected evidence until the existing reader
            # independently retrieves the original public page. No conclusions,
            # case-study winners or partner decisions are imported from the pack.
            from .research_candidates import candidates_for_lead
            lead_details = run.stages[0].output["lead"]
            extra = candidates_for_lead(lead_details, group)
            if extra:
                supplement = search_sources({"results": extra}, run.queries[group], run.sources)
                ids = list(dict.fromkeys([*supplement, *ids]))
                run.logs.append({"event": "research_candidate_urls", "group": group,
                                 "candidate_count": len(extra), "note": "unverified local URL hints; original inspection required"})
            if not ids:
                raise ProviderError(f"{group}: no source URLs were returned; no evidence invented.")
            # Prefer original filings, the company's investor website and
            # actual case-study pages; suppress duplicated www/translated mirrors.
            lead_details = run.stages[0].output["lead"]
            ids = rank_sources(ids, run.sources, group, lead_details.get("company", ""),
                               lead_details.get("domain", ""), lead_details.get("referral", ""))
            warnings = list(result.get("errors", []))
            if group in {"organisation", "finance"}:
                verified_ids = [sid for sid in ids if is_issuer_document(
                    run.sources[sid], lead_details.get("company", ""), lead_details.get("domain", ""))]
                if len(verified_ids) != len(ids):
                    warnings.append(f"{group}: unrelated SEC issuers were excluded from research evidence.")
                ids = verified_ids
            if not ids:
                raise ProviderError(f"{group}: search returned no prospect-relevant sources; do not cite unrelated filings.")
            ranked = ids  # primary-source rank takes precedence over query order
            # Organisation/finance searches frequently return a few unrelated
            # SEC filings. Inspect more ranked candidates before declaring the
            # entire group unsupported; only matching issuers may be cited.
            inspection_limit = (8 if group in {"organisation", "finance"} else 4) if self.settings.task_aware_tokens else (5 if group in {"organisation", "finance"} else 3)
            pending = [sid for sid in ranked if run.sources[sid].access not in {"inspected_page", "inspected_pdf"}][:inspection_limit]
            # Research used to exhaust all source-fetch slots before the case
            # study and partner steps. Reserve capacity so those stages can
            # INSPECT first-party originals, not just collect search snippets.
            reserve = (5 if group in {"organisation", "finance", "current"}
                       else 4 if group == "materials" else 0)
            if self.settings.max_source_fetches < 10:
                reserve = 0  # tiny explicit test budgets retain prior behavior
            pending = pending[:max(0, self.settings.max_source_fetches - fetch_count - reserve)]
            fetch_count += len(pending)
            # Annual reports may be hundreds of pages. Prefer direct, bounded
            # PDF page inspection over Tavily's first-N-character extraction.
            # This is the same public URL, not an untracked research provider.
            for sid in pending:
                src = run.sources[sid]
                if src.url.lower().split("?", 1)[0].endswith(".pdf"):
                    self.fetcher(src, self.settings.max_source_chars)
            still_pending = [sid for sid in pending if run.sources[sid].access not in
                             {"inspected_page", "inspected_pdf"}]
            extracted = {}
            if still_pending:
                try:
                    response = {"results": [], "failed_results": []}
                    for offset in range(0, len(still_pending), 5):
                        try:
                            batch = research_provider.extract([run.sources[s].url for s in still_pending[offset:offset + 5]], f"extract:{group}")
                        except ProviderError as exc:
                            warnings.append(str(exc))
                            break  # Keep earlier successful extraction batches.
                        response["results"].extend(batch.get("results", []))
                        response["failed_results"].extend(batch.get("failed_results", []))
                    from .evidence import source_family_key
                    extracted = {source_family_key(item["url"]): item.get("raw_content") or ""
                                 for item in response.get("results", []) if item.get("url")}
                    for failure in response.get("failed_results", []):
                        # Record the URL's stable source ID, not arbitrary server text.
                        sid = next((s for s in still_pending if source_family_key(run.sources[s].url) == source_family_key(failure.get("url", ""))), None)
                        if sid:
                            run.logs.append({"event": "extract_url_failed", "source_id": sid,
                                             "note": "Provider extraction failed; direct bounded reader will be attempted."})
                except ProviderError as exc:
                    warnings.append(str(exc))
            for sid in pending:
                src = run.sources[sid]
                if src.access in {"inspected_page", "inspected_pdf"}:
                    continue
                from .evidence import source_family_key, relevant_html_excerpt
                text = extracted.get(source_family_key(src.url), "")
                if len(text.strip()) >= 120:
                    src.text = relevant_html_excerpt(text, self.settings.max_source_chars, src.queries)
                    src.access, src.inspection_method = "inspected_page", "Tavily basic Extract; provider-extracted text, original completeness not established"
                    src.truncated = len(text) > self.settings.max_source_chars
                    src.retrieved_at = now()
                    src.error = ""
                else:
                    # Local HTTP/PDF parsing is a free reader, never a paid search-provider fallback.
                    self.fetcher(src, self.settings.max_source_chars)
                    if src.access not in {"inspected_page", "inspected_pdf"}:
                        src.error = src.error or "Neither provider extraction nor direct inspection returned usable original text."
                run.logs.append({"event": "source_fetch", "source_id": sid, "access": src.access, "truncated": src.truncated})
            checkpoint()
            # Bound context size. Do not quietly accept an unrelated SEC issuer
            # when the inspected original contradicts a search-result snippet.
            if group in {"organisation", "finance"}:
                issuer_discarded = [sid for sid in ids if not is_issuer_document(
                    run.sources[sid], lead_details.get("company", ""), lead_details.get("domain", ""))]
                if issuer_discarded:
                    warnings.append(f"{group}: {len(issuer_discarded)} unrelated filing(s) excluded after inspection.")
                ids = [sid for sid in ids if sid not in issuer_discarded]
            selected = [sid for sid in ids if run.sources[sid].access in {"inspected_page", "inspected_pdf"}][:8 if self.settings.task_aware_tokens else 3]
            selected += [sid for sid in ids if sid not in selected][:1]
            warnings += [f"{sid}: {run.sources[sid].error}" for sid in pending if run.sources[sid].error]
            if not any(run.sources[sid].text for sid in ids):
                warnings.append(f"{group}: no relevant original document inspected; public conclusions remain provisional.")
            if any(run.sources[sid].truncated for sid in selected):
                warnings.append(f"{group}: some documents were inspected only in part; consult source truncation/page counts.")
            run.retrieval_cache[group] = {"queries": run.queries[group], "source_ids": selected, "warnings": warnings, "at": now()}
            return selected, warnings

        def context(ids=None, compact=False, focus=""):
            """Use a minimal, evidence-only payload for deep nested JSON schemas.

            Original source text stays in run.sources; shortening model context
            does not change what is available to the verifier or reviewer.
            """
            chosen = list(run.sources) if ids is None else ids
            if compact:
                lead = lead_context(run.stages[0].output)
                return {"as_of_date": run.as_of_date,
                        "lead": {k: lead[k] for k in ("company", "geography", "industry", "need", "referral")},
                        "sources": evidence_batch(run.sources, chosen, self.settings,
                                                  max_sources=3, max_chars=2250)}
            return {"as_of_date": run.as_of_date, "enquiry": run.input,
                    "qualification": lead_context(run.stages[0].output),
                    "sources": evidence_batch(run.sources, chosen, self.settings, focus=focus)}

        def audit(data, purpose, only_paths=None):
            """Semantically inspect every claim, splitting only when necessary.

            A failed/missing audit NEVER promotes a claim to verified. Each
            independent audit batch retains original claim paths and source IDs.
            """
            normalize_claims(data, run.sources)
            findings = audit_mechanical(data, run.sources, enquiry, run.as_of_date)
            if only_paths is not None:
                findings = [f for f in findings if any(path_affects_claim(f["path"], p) for p in only_paths)]
            for finding in findings:
                finding["origin"] = "mechanical"
            batches = audit_batches(data, run.sources, target_tokens=2800 if self.settings.expanded_research else 3200,
                                    only_paths=only_paths)
            audit_status = "performed"
            for index, batch in enumerate(batches):
                try:
                    result = synthesize(
                        Audit, prompts.AUDIT,
                        {"as_of_date": run.as_of_date, "enquiry": enquiry, **batch},
                        (f"audit:{purpose}" if len(batches) == 1 else f"audit:{purpose}:part:{index + 1}-of-{len(batches)}"),
                        max_tokens=1800 if self.settings.task_aware_tokens else 1400 if self.settings.expanded_research else 1000)
                    for finding in result.findings:
                        record = finding.model_dump()
                        record["origin"] = "semantic"
                        record["path"] = resolve_audit_path(record["path"], data)
                        # A broken claim path must not silently evade review.
                        if only_paths is not None and (not record["path"] or not any(
                            path_affects_claim(record["path"], p) for p in only_paths
                        )):
                            findings.extend({**record, "path": p} for p in only_paths)
                        else:
                            findings.append(record)
                except Exception as exc:
                    findings.extend({"path": p, "severity": "error",
                                     "reason": f"Semantic groundedness review unavailable ({type(exc).__name__}); output needs manual review."}
                                    for p in (only_paths if only_paths is not None else [""]))
                    audit_status = "unavailable"
                    break
            return {"mechanical_and_semantic_findings": findings, "semantic_review": audit_status,
                    "audit_batches": len(batches),
                    "limitation": "Automated checks flag risks; they do not guarantee factual truth."}

        def qualification():
            nonlocal provider
            provider = self.provider_factory(self.settings, run)
            lead = synthesize(Lead, prompts.EXTRACT, {"enquiry": enquiry, "as_of_date": run.as_of_date}, "extraction")
            data = qualify(lead, enquiry)
            warnings = data.pop("warnings")
            # Identity and known information must be traceable to the input, too.
            from .qualification import normalise
            # Parse a literal From header deterministically. A model can omit
            # the address even when it is plainly present in the raw enquiry.
            # Never use an address inferred from a company domain or contact name.
            address_match = re.search(r"^From:\s*[^\n]*?\(([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\)", enquiry, re.I | re.M)
            if address_match:
                data["lead"]["email"] = address_match.group(1)
            for field in ["name", "email", "title", "company", "domain", "referral"]:
                value = data["lead"][field]
                if value and normalise(value) not in normalise(enquiry):
                    data["lead"][field] = ""
                    warnings.append(f"{field}: extraction could not be tied to the enquiry; cleared for review.")
            data["lead"]["knowns"] = [k for k in data["lead"]["knowns"] if normalise(k) in normalise(enquiry)]
            extracted = Lead.model_validate(data["lead"])
            if not extracted.company:
                raise ProviderError("No company could be established from the enquiry; account research cannot proceed reliably.")
            run.queries = derive_queries(extracted, run.as_of_date, self.settings.expanded_research, self.settings.task_aware_tokens)
            return data, warnings

        def account():
            ids, warnings, groups = [], [], {}
            technical_issues = []
            for group in ["organisation", "finance", "current"]:
                try:
                    selected, problems = search(group)
                    ids += selected
                    groups[group] = selected
                    warnings += problems
                except Exception as exc:
                    warnings.append(f"{group} research failed ({type(exc).__name__}); this area remains unverified.")
                    technical_issues.append(f"{group}: retrieval failed ({type(exc).__name__}).")
            if not ids:
                raise ProviderError("All account-research searches failed; no research brief was fabricated.")
            mapping = [("Organisation and reporting lines", "organisation"), ("Budget and investment signals", "finance"),
                       ("News and strategic announcements", "current"), ("Investor priorities", "finance"),
                       ("Corporate changes and customer relationships", "current")]
            if self.settings.compact_account_research:
                # One evidence-backed structured research synthesis, not five
                # near-duplicate model requests plus a sixth advice request.
                # Pick up to two inspected sources from each retrieval group;
                # each group must have a chance to inform the answer.
                compact_ids = []
                for group in ("organisation", "finance", "current"):
                    inspected = [sid for sid in groups.get(group, [])
                                 if sid in run.sources and run.sources[sid].access in {"inspected_page", "inspected_pdf"}]
                    compact_ids.extend(inspected[:2])
                compact_ids = list(dict.fromkeys(compact_ids))
                if not compact_ids:
                    raise ProviderError("No original public documents were inspected. Research was not invented.")
                prompt = (prompts.RESEARCH + "\nReturn exactly all FIVE named research topics in the required order. "
                          "Aim for one atomic, evidence-backed finding per topic, maximum two. "
                          "If a topic lacks inspected support, return claims=[] and an explicit gap. "
                          "For financial figures include currency, units, reporting period and company scope. "
                          "For organisation distinguish division structure from the named buyer's unverified manager. "
                          "Keep positioning to two concise items and stakeholder hypothesis to one. "
                          "This is one compact inference call: be economical with words but never omit uncertainty.")
                try:
                    synthesized = synthesize(
                        Research, prompt,
                        {**context(compact_ids),
                         "expected_topic_names": [name for name, _ in mapping],
                         "instruction": "Document only claims genuinely supported by the provided original text."},
                        "account research:compact", max_tokens=min(self.settings.max_output_tokens, 2600))
                    data = synthesized.model_dump()
                    returned = {topic["name"]: topic for topic in data["topics"]}
                    # An incomplete model response is never silently marked complete.
                    data["topics"] = [returned.get(name, Topic(name=name, claims=[], gaps=[
                        "Model did not return this required topic; review needed."]).model_dump())
                                      for name, _ in mapping]
                    if len(returned) != len(mapping) or len(data["topics"]) != len(returned):
                        warnings.append("Compact research did not return each required topic exactly once.")
                    run.logs.append({"event": "compact_account_research", "at": now(),
                                     "note": "one model synthesis call, same live inspected source registry",
                                     "source_ids": compact_ids})
                except ProviderError as exc:
                    warnings.append("Compact research synthesis failed: " + str(exc))
                    technical_issues.append("Compact research synthesis did not complete.")
                    data = {"topics": [Topic(name=name, claims=[], gaps=[
                        "Compact model call unavailable; no source-backed synthesis produced."]).model_dump()
                                       for name, _ in mapping],
                            "positioning": [], "stakeholder_hypothesis": [], "conflicts": []}
            else:
                topics = []
                for name, group in mapping:
                    if not groups.get(group):
                        topics.append(Topic(name=name, claims=[], gaps=["Retrieval failed for this area; not verified."]).model_dump())
                        continue
                    try:
                        focus = ({"organisation": "Report public division/governance structure even when the named buyer's manager is unknown.",
                                  "finance": "Report general company investment/operational priorities; a private drone-project budget is not required for a company-level finding.",
                                  "current": "Report supported dated developments or existing customer relationships; distinguish future plans."}.get(group, ""))
                        source_focus = ("investor priorities strategy safety capital discipline growth reliability" if name == "Investor priorities" else name)
                        count = "three" if self.settings.task_aware_tokens else "two"
                        topic = synthesize(Topic, prompts.RESEARCH + f"\nReturn ONLY topic '{name}', at most {count} atomic claims. Preserve distinct capex/opex/technology findings when supported. Each quote under 45 words. " + focus,
                                                    context(groups[group], focus=source_focus), f"account topic:{name}",
                                                    max_tokens=3400 if self.settings.task_aware_tokens else 2200 if self.settings.expanded_research else 1800)
                        if topic.name != name:
                            raise ProviderError("Research topic did not match the requested area.")
                        if self.settings.task_aware_tokens and not topic.claims:
                            # New passages, not a retry of the same unsupported
                            # conclusion. Private unknowns stay unknown. Bound
                            # this to one follow-up per empty topic and require
                            # room for a useful complete request first.
                            available = ProjectBudget(self.settings).demo_summary()
                            additional_sources = evidence_batch(run.sources, groups[group], self.settings,
                                                                focus=source_focus, window_offset=2)
                            initial_sources = context(groups[group], focus=source_focus)["sources"]
                            has_new_passages = any(s.get("text") and s.get("text") != initial_sources.get(sid, {}).get("text")
                                                   for sid, s in additional_sources.items())
                            if available and available["groq_remaining"] >= 7500 and has_new_passages:
                                supplementary = {**context([]), "requested_topic": name,
                                                 "sources": additional_sources}
                                initial_gaps = topic.gaps[:]
                                try:
                                    candidate = synthesize(Topic, prompts.RESEARCH +
                                        f"\nReturn only '{name}'. Inspect these different source passages for company-level facts. "
                                        "Private project funding or a personal reporting line is not required for a general company finding. Preserve narrow unknowns; do not invent facts.",
                                        supplementary, f"account followup:{name}", max_tokens=3400)
                                    if candidate.name == name and candidate.claims:
                                        topic = candidate
                                    run.logs.append({"event": "research_gap_followup", "topic": name,
                                                     "earlier_gaps": initial_gaps,
                                                     "method": "one distinct-passage follow-up, not a repeated failed request"})
                                except ProviderError as exc:
                                    technical_issues.append(f"{name}: supplemental passage review unavailable; initial gaps retained.")
                                    run.logs.append({"event": "research_gap_followup_failed", "topic": name,
                                                     "error_type": type(exc).__name__})
                        topics.append(topic.model_dump())
                    except ProviderError as exc:
                        technical_issues.append(f"{name}: synthesis did not complete.")
                        topics.append(Topic(name=name, claims=[], gaps=[str(exc)]).model_dump())
                try:
                    advice = synthesize(AccountAdvice, prompts.RESEARCH + "\nOnly positioning (max 2), stakeholder hypothesis (max 1) and conflicts. No new facts beyond evidence and findings.",
                                                  {**context(list(dict.fromkeys(ids))[:4]), "findings": [c for t in topics for c in t["claims"]][:6]},
                                                  "account positioning", max_tokens=1500)
                    advice_data = advice.model_dump()
                except ProviderError as exc:
                    # Preserve expensive, already-saved original research; do not
                    # discard every topic because the last synthesis call failed.
                    warnings.append("Account positioning unfinished: " + str(exc))
                    technical_issues.append("Account positioning did not complete.")
                    advice_data = {"positioning": [], "stakeholder_hypothesis": [], "conflicts": []}
                data = {"topics": topics, **advice_data}
            data["groundedness"] = audit(data, "account")
            if technical_issues:
                data["technical_issues"] = technical_issues
            names = {t["name"] for t in data["topics"]}
            expected = {"Organisation and reporting lines", "Budget and investment signals", "News and strategic announcements",
                        "Investor priorities", "Corporate changes and customer relationships"}
            if names != expected:
                warnings.append("Not all required account-research topics were returned.")
            for topic in data["topics"]:
                warnings += [f"{topic['name']}: {gap}" for gap in topic["gaps"]]
                if not topic["claims"]:
                    warnings.append(f"{topic['name']}: no verified findings.")
            verified_topics = {row["topic"] for row in cleared_claims(data, run.sources, enquiry, run.as_of_date)}
            for topic in data["topics"]:
                if topic["name"] not in verified_topics:
                    warnings.append(f"{topic['name']}: no public finding cleared source and semantic checks.")
            warnings += data["conflicts"]
            warnings += [f"Groundedness {f['path']}: {f['reason']}" for f in data["groundedness"]["mechanical_and_semantic_findings"]]
            return data, warnings

        def materials():
            nonlocal fetch_count
            try:
                ids, warnings = search("materials", ["flytbase.com"])
            except ProviderError as exc:
                # Tavily's search can fail even when official case-study URLs
                # are known from the public index. Continue to first-party
                # discovery (under the same explicit live approval); each
                # original must still be fetched and evidence-checked. Never
                # treat the dated directory as verified case-study evidence.
                ids, warnings = [], ["Case-study search unavailable; attempting official originals: " + str(exc)]
                if mode != "live" and not any(is_flytbase(src.url) and src.text for src in run.sources.values()):
                    raise  # No external discovery in offline fixture mode.
            # If ordinary search returned only webinars/blogs, look for relevant
            # first-party customer-story links on FlytBase's live index. Nothing
            # here is a preselected winner; individual URLs must be inspected.
            from .story_discovery import missing_story_connections
            missing_connections = missing_story_connections(run.sources, run.stages[0].output["lead"])
            if mode == "live" and current_execution_phase() == "new_run" and missing_connections:
                warnings.append("Cache-only continuation: missing customer/referral story connections remain unverified; no fresh directory lookup performed.")
            if mode == "live" and current_execution_phase() != "new_run" and missing_connections and fetch_count < self.settings.max_source_fetches:
                from .story_discovery import discover_official_stories
                leads = run.stages[0].output.get("lead", {})
                # Discover candidates from the current FIRST-PARTY directory,
                # not a saved catalogue of customer URLs. Keeping preselected
                # customer URLs in runtime code could bias the case decision
                # and would weaken the assignment's no-hard-coding requirement.
                # These directory links are only retrieval candidates: each
                # original page must still be inspected and scored.
                candidates = discover_official_stories(leads)
                by_url = {row["url"].rstrip("/"): row for row in candidates}
                proposals = list(by_url)
                if proposals:
                    story_ids = search_sources({"results": [by_url[url] for url in proposals]},
                                                ["Official first-party case-page candidate"], run.sources)
                    limit = max(0, min(2, self.settings.max_source_fetches - fetch_count -
                                       (2 if self.settings.max_source_fetches >= 10 else 0)))
                    for sid in story_ids[:limit]:
                        self.fetcher(run.sources[sid], self.settings.max_source_chars)
                        fetch_count += 1
                    inspected = [sid for sid in story_ids if run.sources[sid].access in {"inspected_page", "inspected_pdf"}]
                    ids = list(dict.fromkeys([*inspected, *ids]))
                    run.logs.append({"event": "official_case_candidate_discovery", "discovered": len(proposals),
                                     "inspected": len(inspected),
                                     "method": "current official index links; originals inspected; no stored-case URLs or hardcoded winner"})
            # Account research may already have found useful prospect-specific material.
            ids = list(dict.fromkeys([*ids, *[sid for sid, s in run.sources.items() if is_flytbase(s.url) and s.text]]))[:8]
            # The full Material schema is sizable. Send a focused evidence set,
            # not eight pages plus a duplicate copy of the full enquiry.
            article_ids = sorted(ids, key=lambda sid: (
                "/case-studies/" not in run.sources[sid].url,
                not any(name in (run.sources[sid].title + " " + run.sources[sid].text[:400]).lower()
                        for name in (run.stages[0].output["lead"].get("company", "").split("(")[-1].rstrip(")").lower(),
                                     run.stages[0].output["lead"].get("referral", "").lower()) if name)),
                )
            ai_choice = None
            try:
                if getattr(provider, "supports_compact_material_comparison", False):
                    # Groq's strict Materials JSON schema requires a very large,
                    # nested response (two cases × six dimensions × citations).
                    # The recorded 2026-11-05 request returned HTTP 400 because
                    # max_completion_tokens ended before the required `gaps` key.
                    # Build full citeable candidates from inspected sources and
                    # request ONLY a compact AI comparison/advisory judgement.
                    from .evidence_decisions import material_proposals
                    proposed = material_proposals(run, article_ids)
                    if not proposed.candidates:
                        raise ProviderError("No inspected source-backed case candidates; no comparison was invented.")
                    brief = []
                    for candidate in proposed.candidates[:2]:
                        src = run.sources.get(candidate.source_id)
                        brief.append({
                            "source_id": candidate.source_id,
                            "title": candidate.title[:130],
                            "official_url": src.url if src else "",
                            "dimensions": [{"name": d.dimension, "matched": d.matched,
                                            "exact_quote": (d.rationale.evidence[0].quote
                                                            if d.rationale.evidence else "")}
                                           for d in candidate.dimensions],
                            "limitations": candidate.limitations[:2],
                        })
                    lead_details = run.stages[0].output["lead"]
                    ai_choice = synthesize(
                        MaterialChoice, prompts.MATERIAL_CHOICE,
                        {"lead": {k: lead_details.get(k, "") for k in ("company", "geography", "industry", "need", "referral")},
                         "cases": brief},
                        "material comparison", max_tokens=950)
                    candidate_ids = {c.source_id for c in proposed.candidates}
                    if (ai_choice.preferred_source_id and ai_choice.preferred_source_id not in candidate_ids) or any(
                        sid not in candidate_ids for sid in ai_choice.ranked_source_ids
                    ):
                        raise ProviderError("Material AI response named a source outside inspected candidates; withheld.")
                    # AI preference is advisory; evidence-gated local scoring
                    # and the separate semantic audit still control acceptance.
                else:
                    # Offline fixture and injected custom providers retain the
                    # established full-Materials contract for compatibility.
                    proposed = synthesize(Materials, prompts.MATERIALS + "\nAt most two candidates; limit each rationale to one short cited excerpt.",
                                          context(article_ids, compact=True), "material comparison", max_tokens=2600)
                audit_input = proposed.model_dump()
                if ai_choice is not None:
                    audit_input["ai_case_comparison"] = ai_choice.model_dump()
                review = audit(audit_input, "materials")
            except (ProviderError, QuotaExhausted) as exc:
                from .evidence_decisions import material_proposals
                proposed = material_proposals(run, article_ids)
                ai_choice = None
                if not proposed.candidates:
                    raise ProviderError("No inspected case-study candidate passed source checks; rerun the case-study search.") from exc
                review = {"mechanical_and_semantic_findings": audit_mechanical(proposed.model_dump(), run.sources, enquiry, run.as_of_date),
                          "semantic_review": "rule_based_fallback",
                          "limitation": "Source-derived match, mechanically verified; AI semantic audit unavailable. Review original articles."}
                warnings.append("Case comparison used a source-backed deterministic fallback; AI comparison unavailable. Review sources.")
            data = select_materials(proposed, run.sources, enquiry, run.as_of_date, review["mechanical_and_semantic_findings"],
                                    lead=run.stages[0].output["lead"])
            data["groundedness"] = review
            if ai_choice is not None:
                data["ai_case_comparison"] = {
                    **ai_choice.model_dump(),
                    "status": "advisory only; final selection is evidence-gated",
                }
                if ai_choice.preferred_source_id and data.get("primary") and (
                    ai_choice.preferred_source_id != data["primary"]["candidate"]["source_id"]
                ):
                    warnings.append("AI-preferred case differs from evidence-gated winner; inspect both source records.")
                if not ai_choice.preferred_source_id:
                    warnings.append("AI comparison did not identify a suitable case; source-based selection needs review.")
            if review["semantic_review"] != "performed":
                data["technical_issues"] = ["AI case comparison/audit unavailable; rule-based proposal is provisional."]
            data["possible_existing_company_relationship"] = own_company_mentions(run)
            if data["possible_existing_company_relationship"]:
                for row in data.get("comparison", []):
                    row["candidate"]["own_company_expansion_assessment"] = (
                        "An inspected FlytBase source indicates possible adoption elsewhere in the company. "
                        "Confirm which division/site uses FlytBase before treating these requested sites as an expansion. "
                        "See source registry and original model proposal for evidence/limitations."
                    )
            if data["possible_existing_company_relationship"] and any(
                "no evidence" in str(candidate).casefold() and "flytbase" in str(candidate).casefold()
                for candidate in data.get("candidates", [])):
                warnings.append("Case-comparison contradiction: inspected FlytBase material references this company; verify whether the enquiry concerns new sites/divisions.")
            warnings += proposed.gaps
            if not data["primary"]:
                warnings.append("No primary case study cleared the evidence and groundedness checks.")
            warnings += [f"Groundedness {f['path']}: {f['reason']}" for f in review["mechanical_and_semantic_findings"]]
            return data, warnings

        def routing():
            try:
                ids, warnings = search("partners")
            except ProviderError as exc:
                ids, warnings = [], ["Fresh partner search unavailable: " + str(exc)]
            # A current customer's inspected case study may name the local
            # implementation company. Keep that source visible for routing,
            # rather than searching only a generic partner directory.
            lead_details = run.stages[0].output.get("lead", {})
            from .diagnostics import _brand
            signals = [_brand(lead_details.get("company", "")).casefold(),
                       str(lead_details.get("referral", "")).casefold()]
            signals = [word for word in signals if len(word) >= 3]
            candidate_ids = [sid for sid, src in run.sources.items()
                             if is_flytbase(src.url) and src.text and
                             any(word in src.text.casefold() for word in signals)]
            ids = list(dict.fromkeys([*candidate_ids[:2], *ids]))[:8]
            if not ids:
                return {"recommended_motion": "direct_ae", "selected_partner_name": "", "candidates": [],
                        "required_partner_type": "Verified local drone installation provider",
                        "commercial_owner": "FlytBase Account Executive", "implementation_owner": "Not verified",
                        "next_action": "Ask FlytBase to verify local implementation support before assigning a partner.",
                        "decision_basis": "Conservative policy fallback; no inspected partner evidence was available.",
                        "retrieved_source_ids": [], "gaps": warnings}, warnings + ["No inspected partner evidence was available."]
            try:
                if getattr(provider, "supports_compact_partner_advice", False):
                    # Inspect and construct any partner evidence locally. The AI
                    # only chooses a compact business route; it never invents
                    # nested evidence/capability/geographic coverage objects.
                    from .models import RouteAdvice
                    from .evidence_decisions import route_proposal
                    proposed = route_proposal(run, ids)
                    context_data = context(ids, compact=True)
                    context_data["documented_candidates"] = [
                        {"name": c.name, "availability": c.availability,
                         "evidence": c.ecosystem_evidence.model_dump()}
                        for c in proposed.candidates[:1]]
                    advice = synthesize(RouteAdvice, prompts.ROUTING_ADVICE, context_data,
                                        "partner routing:compact", max_tokens=750)
                    # RouteAdvice is advisory; all final country and capability
                    # gates are still enforced by decide_routing below.
                    names = {c.name.casefold(): c.name for c in proposed.candidates}
                    suggested = names.get(advice.proposed_partner_name.casefold())
                    if advice.recommended_motion == "partner_led" and suggested:
                        proposed.recommended_motion = "partner_led"
                        proposed.proposed_partner_name = suggested
                    proposed.gaps = list(dict.fromkeys([*proposed.gaps, *advice.gaps[:2]]))
                    run.logs.append({"event": "compact_partner_advice", "at": now(),
                                     "note": "small AI business-choice JSON; source-derived partner evidence and downstream gates remain independent"})
                else:
                    proposed = synthesize(Routing, prompts.ROUTING + "\nAt most one candidate. Return EVERY required Routing and Partner schema field. "
                                      "For each candidate, limitations MUST be a list (empty if none verified). "
                                      "If any capability or coverage cannot be supported, choose direct_ae and candidates=[]. "
                                      "Use short atomic claims and quotes; do not repeat the full page.",
                                          context(ids, compact=True), "partner routing", max_tokens=2300)
            except (ProviderError, QuotaExhausted) as exc:
                from .evidence_decisions import route_proposal
                proposed = route_proposal(run, ids)
                review = {"mechanical_and_semantic_findings": audit_mechanical(proposed.model_dump(), run.sources, enquiry, run.as_of_date),
                          "semantic_review": "rule_based_fallback",
                          "limitation": "Evidence-backed rule-based routing; no Groq semantic audit. Current partner availability remains unknown."}
                warnings.append("Groq partner assessment unavailable; source-backed routing policy used. Review partner capacity.")
            else:
                review = audit(proposed.model_dump(), "routing")
            lead = Lead.model_validate(run.stages[0].output["lead"])
            data = decide_routing(proposed, run.sources, enquiry, run.as_of_date, lead.geography, review["mechanical_and_semantic_findings"])
            data["groundedness"] = review
            if review["semantic_review"] != "performed":
                data["technical_issues"] = ["AI routing/audit unavailable; rule-based proposal is provisional."]
            warnings += data["gaps"]
            warnings += [f"Groundedness {f['path']}: {f['reason']}" for f in review["mechanical_and_semantic_findings"]]
            return data, warnings

        def safe_output(index):
            """Remove flagged claims before email synthesis; keep full flagged records for inspection."""
            import copy
            data = copy.deepcopy(run.stages[index].output)
            if index in {1, 3, 4} and data.get("groundedness", {}).get("semantic_review") != "performed":
                policy = ({"recommended_motion": "direct_ae", "commercial_owner": "FlytBase Account Executive",
                           "selected_partner_name": "", "implementation_candidates": [],
                           "implementation_owner": "Unassigned; local capability/capacity not verified",
                           "next_action": "AE-led discovery; verify implementation support before assignment.",
                           "decision_basis": "Conservative commercial policy, not a verified partner recommendation."} if index == 4 else {})
                return {"status": "unverified", "warning": "Semantic review unavailable; public conclusions withheld from downstream drafts.", **policy}
            findings = data.get("groundedness", {}).get("mechanical_and_semantic_findings", [])
            from .grounding import unresolved_paths
            errors = unresolved_paths(findings)
            if "" in errors:
                return {"status": "unverified", "warning": "Semantic review unavailable; do not use public conclusions."}
            def scrub(value, path=""):
                if any(path == p or path.startswith(p + ".") for p in errors):
                    return "Withheld: groundedness review flagged this field."
                if isinstance(value, dict):
                    if "kind" in value and "text" in value:
                        if any(path_affects_claim(p, path) for p in errors):
                            return {"kind": "unknown", "text": "Finding withheld: groundedness review flagged support."}
                    return {k: scrub(v, f"{path}.{k}".strip(".")) for k, v in value.items() if k != "groundedness"}
                if isinstance(value, list):
                    return [scrub(v, f"{path}.{i}".strip(".")) for i, v in enumerate(value)]
                return value
            cleaned = scrub(data)
            if index == 3:
                # Rejected candidates remain inspectable, but must not influence buyer-facing drafts.
                cleaned = {k: cleaned.get(k) for k in ["primary", "supporting", "referral_findings", "gaps"]}
            return cleaned

        def emails():
            research = safe_output(1)
            findings = handoff_highlights(run.stages[1].output, run.sources, enquiry, run.as_of_date)
            materials = safe_output(3)
            primary = materials.get("primary") or {}
            candidate = primary.get("candidate") or {}
            short_material = {k: candidate.get(k) for k in ["title", "source_id", "relevance", "limitations"]}
            route = safe_output(4)
            relationship = run.stages[3].output.get("possible_existing_company_relationship", [])[:1]
            brief = {"research_findings": findings, "positioning": research.get("positioning", [])[:2],
                     "material": short_material, "possible_existing_company_relationship": relationship,
                     "routing": {k: route.get(k) for k in ["recommended_motion", "commercial_owner", "next_action"]}}
            cited = list(dict.fromkeys([*(r.source_id for _, c in iter_claims(brief) for r in c.evidence),
                                        *(x["source_id"] for x in relationship)]))
            email_context = {**context([]), **brief, "sources": evidence_batch(run.sources, cited, self.settings, brief)}
            if self.settings.expanded_research:
                # Preserve the original quotes in the registry/audit, but remove
                # duplicated context before a large five-branch JSON completion.
                lead = run.stages[0].output["lead"]
                email_context = {"as_of_date": run.as_of_date, "enquiry": enquiry,
                    "qualification_status": {d: {"status": lead[d]["status"], "questions": lead[d]["questions"][:1]}
                                             for d in ("budget", "authority", "timeline")},
                    "research_findings": findings[:2],
                    "material": {k: short_material.get(k) for k in ("title", "source_id", "limitations")},
                    "possible_existing_company_relationship": relationship,
                    "routing": brief["routing"],
                    "sources": evidence_batch(run.sources, cited, self.settings, brief,
                                              max_sources=2, max_chars=1200)}
            data = synthesize(Responses, prompts.EMAILS, email_context,
                              "email drafts").model_dump()
            warnings = list(data["limitations"])
            branches = {d["branch"] for d in data["drafts"]}
            if branches != {"initial", "no_reply", "interested", "budget_clarification", "stakeholder_referral"} or len(data["drafts"]) != 5:
                warnings.append("All five unique response branches were not returned.")
            for draft in data["drafts"]:
                if draft["branch"] == "initial" and draft["hypothetical"]:
                    draft["hypothetical"] = False
                    warnings.append("Initial response corrected to a draft for the actual enquiry; no prior reply assumed.")
                if draft["branch"] != "initial" and not draft["hypothetical"]:
                    draft["hypothetical"] = True
                    warnings.append("Follow-up branch corrected to hypothetical; no buyer response was received.")
                if not draft.get("trigger") or not draft.get("why_this_message") or not draft.get("if_buyer_responds"):
                    warnings.append(f"{draft['branch']}: progression trigger, reason or next action is missing.")
                text = " ".join(p["text"] for p in draft["paragraphs"])
                if text.count("?") > 2:
                    warnings.append(f"{draft['branch']}: too many discovery questions for a concise senior-buyer message.")
                from .sales_validation import introduces_timing_year
                if any(introduces_timing_year(p, enquiry, draft["branch"]) for p in draft["paragraphs"]):
                    warnings.append(f"{draft['branch']}: the draft introduces a year absent from the enquiry; ask which year without suggesting one.")
            if findings:
                initial = next((d for d in data["drafts"] if d["branch"] == "initial"), {})
                if not any(p["evidence"] for p in initial.get("paragraphs", [])):
                    warnings.append("Initial draft omitted available verified research context; revise before use.")
            data["groundedness"] = audit(data, "emails")
            warnings += [f"Groundedness {f['path']}: {f['reason']}" for f in data["groundedness"]["mechanical_and_semantic_findings"]]
            from .sales_validation import checked_drafts
            data, removed_warnings = checked_drafts(data, run.sources, enquiry, run.as_of_date)
            warnings += removed_warnings
            # Do not leave sales users with five blank emails when upstream AI
            # produces unverifiable statements. Rebuild safe question-led drafts
            # exclusively from supplied facts, preserving rejected originals for
            # inspection and explicitly marking the distinct recovery provenance.
            if getattr(provider, "supports_safe_email_recovery", False):
                from .safe_email_recovery import generate_safe_drafts
                data, recovered = generate_safe_drafts(
                    enquiry, run.stages[0].output.get("lead", {}), data,
                    run.sources, run.as_of_date, verified_claims=findings)
                if recovered:
                    warnings.append("Generated question-led source-limited drafts for rejected branches; "
                                    "original AI claims remain withheld and semantic approval is not implied.")
            if any(run.stages[i].status in {"partial", "failed"} for i in [1, 3, 4]):
                warnings.append("Upstream research/material/routing limitations require review before using drafts.")
            return data, warnings

        def handoff():
            qualification = run.stages[0].output
            research = run.stages[1].output
            findings = research.get("groundedness", {}).get("mechanical_and_semantic_findings", [])
            error_paths = [f["path"] for f in findings if f["severity"] == "error"]
            top = handoff_highlights(research, run.sources, enquiry, run.as_of_date)
            lead = qualification["lead"]
            relationship = run.stages[3].output.get("possible_existing_company_relationship", [])
            questions = list(dict.fromkeys(q for dim in ["budget", "authority", "need_dimension", "timeline"]
                                           for q in lead[dim]["questions"]))
            limits = [f"{s.name}: {w}" for s in run.stages if s.name != "AE Handoff Summary" for w in s.warnings]
            if len(top) < 3:
                limits.append(f"Only {len(top)} public research findings cleared checks; three findings were not fabricated.")
            incomplete_evidence = bool(limits)
            if relationship:
                limits.insert(0, "Inspected FlytBase content mentions potential existing customer-level deployment; confirm which division/sites and whether this is expansion.")
                questions.append(f"Does this request expand an existing FlytBase deployment at another {lead['company']} site or division?")
            case = safe_output(3).get("primary")
            route = safe_output(4)
            data = {"buyer_context": {k: lead[k] for k in ["name", "email", "title", "company", "geography", "referral"]},
                    "identity_basis": "Buyer identity/title/referral are enquiry-supplied, not publicly verified authority or relationships.",
                    "business_problem_and_desired_outcome": lead["need"],
                    "qualification": qualification, "top_three_research_findings": top,
                    "recommended_case_study": case,
                    "possible_existing_company_relationship": relationship[:2],
                    "routing": {**{k: route.get(k, [] if k == "implementation_candidates" else "" if k == "selected_partner_name" else "Not established")
                                    for k in ["recommended_motion", "selected_partner_name", "commercial_owner", "implementation_owner", "implementation_candidates", "next_action"]},
                                "assessment_status": run.stages[4].status,
                                "decision_basis": route.get("decision_basis", "Inspect upstream routing evidence and limitations.")},
                    "suggested_next_action": "Arrange a short discovery call to confirm budget approval process, decision stakeholders, timing year, site conditions and pilot success criteria.",
                    "why": "The engagement priority and qualification completeness are separate; resolve feasibility and buying-process gaps before proposing a rollout.",
                    "discovery_questions": questions,
                    "important_limitations": limits,
                    "stakeholder_hypotheses": safe_output(1).get("stakeholder_hypothesis", [])}
            # A useful discovery caveat does not mean the briefing failed.
            # Keep scope/authority unknowns visible while reserving partial
            # status for incomplete evidence or upstream verification failures.
            return data, ["Upstream uncertainties are preserved; review limitations before taking action."] if incomplete_evidence else []

        checkpoint()
        if resume and run.stages[0].output:
            provider = self.provider_factory(self.settings, run)
        stage(0, qualification)
        if run.stages[0].status == "failed":
            for item in run.stages[1:]:
                item.status = "skipped"
                item.technical_status = "skipped"
                item.warnings = ["Qualification/extraction prerequisite failed; no downstream output fabricated."]
        else:
            stage(1, account)
            stage(3, materials)
            # The account-research step precedes first-party case retrieval.
            # Reconcile ONLY new, independently inspected first-party customer
            # evidence before composing routing, outreach and handoff. This is
            # a local provenance-preserving operation, not a provider request.
            from .cross_stage import reconcile_existing_customer_evidence
            if reconcile_existing_customer_evidence(run):
                checkpoint()
            # Audit only newly added relationship claims. Reuse exact cached
            # audit responses; never re-label a deterministic check as AI work.
            account_review = run.stages[1].output.get("groundedness", {})
            pending_paths = list(account_review.get("unreviewed_claim_paths", []))
            if pending_paths:
                delta = audit(run.stages[1].output, "account-late-evidence", only_paths=pending_paths)
                # A recovered delta review replaces its earlier failed verdicts,
                # not the original audit of unrelated, successful research.
                old_delta = [f for previous in account_review.get("late_evidence_reviews", [])
                             for f in previous.get("mechanical_and_semantic_findings", [])
                             if any(path_affects_claim(f.get("path", ""), p) for p in pending_paths)]
                account_review["mechanical_and_semantic_findings"] = [
                    f for f in account_review.get("mechanical_and_semantic_findings", []) if f not in old_delta]
                old_warnings = {f"Late-evidence groundedness {f['path']}: {f['reason']}" for f in old_delta}
                run.stages[1].warnings = [w for w in run.stages[1].warnings if w not in old_warnings]
                account_review.setdefault("late_evidence_reviews", []).append({"paths": pending_paths, **delta})
                account_review.setdefault("mechanical_and_semantic_findings", []).extend(delta["mechanical_and_semantic_findings"])
                if delta["semantic_review"] == "performed":
                    account_review["unreviewed_claim_paths"] = []
                    account_review.setdefault("claim_semantic_reviews", {}).update({p: "performed" for p in pending_paths})
                    account_review["cross_stage_deterministic_only_source_ids"] = []
                    from .cross_stage import PENDING_REVIEW_WARNING
                    run.stages[1].warnings = [w for w in run.stages[1].warnings if w != PENDING_REVIEW_WARNING]
                    if "technical_status_before_delta" in account_review:
                        run.stages[1].technical_status = account_review.pop("technical_status_before_delta")
                for finding in delta["mechanical_and_semantic_findings"]:
                    run.stages[1].warnings.append(f"Late-evidence groundedness {finding['path']}: {finding['reason']}")
                if delta["semantic_review"] != "performed":
                    account_review.setdefault("technical_status_before_delta", run.stages[1].technical_status)
                    run.stages[1].technical_status = "partial"
                run.stages[1].status = "partial" if run.stages[1].warnings else "complete"
                run.stages[1].evidence_status = "partial" if run.stages[1].warnings else "supported"
                checkpoint()
            stage(4, routing)
            stage(2, emails)
            stage(5, handoff)
        run.finished_at = now()
        states = [s.status for s in run.stages]
        run.status = "failed" if states[0] == "failed" else "complete" if all(s == "complete" for s in states) else "partial"
        if any(s == "failed" for s in states):
            run.warnings.append("One or more stages failed; this is not a successful end-to-end live demonstration.")
        run.logs.append({"event": "run_finished", "status": run.status, "at": run.finished_at,
                         "source_fetch_attempts": fetch_count})
        if research_provider is not None and hasattr(research_provider, "refresh_usage"):
            try:
                research_provider.refresh_usage()
            except ProviderError as exc:
                run.warnings.append(str(exc))
        checkpoint()
        for client in [provider, research_provider]:
            if client is not None and hasattr(client, "close"):
                client.close()
        if demo_budget:
            demo_budget.finish_final_demo(run.run_id, run.status)
        return run
