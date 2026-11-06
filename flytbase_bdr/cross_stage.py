"""Reconcile late-discovered first-party customer proof with earlier account research.

Stage 2 runs *before* Stage 4 and cannot know about later case-study URLs.
An LLM-generated 'no evidence' assertion must not survive if Stage 4 later
inspects a relevant official customer story. This operation is deterministic,
source-preserving and does not contact any API. It does not infer deployment at
the sites in the incoming enquiry or certify buyer identity/authority.
"""
from __future__ import annotations

import re
from .diagnostics import own_company_mentions, _brand
from .grounding import check_claim, path_affects_claim
from .models import Claim, EvidenceRef
from .evidence import now

TARGET_TOPIC = "Corporate changes and customer relationships"
PENDING_REVIEW_WARNING = ("Late-discovered official company relationship was checked against an exact source passage, "
                          "but was not included in the initial AI semantic audit; confirm scope before outreach.")


def _unsupported_denial(value: str) -> bool:
    text = str(value).casefold()
    if "flytbase" not in text and "existing relationship" not in text:
        return False
    if re.search(r"(?:current|active|signed|approved)\s+(?:commercial\s+)?(?:contract|agreement|commitment)|availability|capacity|(?:proposed|requested|new|three|3)\s+(?:lithium\s+)?sites|site.specific|division.specific|purchasing authority|reporting line", text):
        return False  # A published past deployment does not resolve these unknowns.
    if re.search(r"contract|agreement", text) and not re.search(r"relationship|partnership|collaborat|deploy", text):
        return False
    return bool(re.search(
        r"\bno (?:public )?(?:evidence|verified (?:evidence|findings)|published (?:evidence|relationship))\b"
        r"|\bno (?:existing )?(?:partnership|relationship|contract)\b"
        r"|\bnot (?:found|identified|established|verified)\b",
        text,
    ))


def reconcile_existing_customer_evidence(run) -> bool:
    """Return true only if run contents were enhanced using inspected evidence.

    Never upgrades an existing stage's technical/semantic-review status. Any
    suppressed contradictory text is retained in the run's audit log.
    """
    research_stage = run.stages[1]
    material_stage = run.stages[3]
    if not research_stage.output or not material_stage.output:
        return False
    findings = own_company_mentions(run)
    if not findings:
        return False
    topics = research_stage.output.get("topics", [])
    topic_index = next((i for i, t in enumerate(topics)
                        if t.get("name") == TARGET_TOPIC), None)
    if topic_index is None:
        return False
    topic = topics[topic_index]
    brand = _brand(run.stages[0].output.get("lead", {}).get("company", ""))
    if len(brand) < 3:
        return False

    inspected = []
    for finding in findings:
        sid = finding["source_id"]
        source = run.sources.get(sid)
        if not source or "/case-studies/" not in source.url:
            continue
        claim = Claim(
            text=f"FlytBase's inspected customer case study documents a company-level collaboration involving {brand}.",
            kind="public",
            evidence=[EvidenceRef(source_id=sid, quote=finding["quote"])],
            input_quote="", uncertainty="", financial_context=None, event_date="",
        )
        if not check_claim(claim, run.sources, run.input, run.as_of_date):
            inspected.append((sid, claim))
    if not inspected:
        return False

    review = research_stage.output.setdefault("groundedness", {})
    pending = review.setdefault("unreviewed_claim_paths", [])
    pending_before = list(pending)
    claim_keys = {(ref.get("source_id"), c.get("text"))
                  for c in topic.get("claims", []) for ref in c.get("evidence", [])}
    already_documented = set()
    errors = [f.get("path", "") for f in review.get("mechanical_and_semantic_findings", []) if f.get("severity") == "error"]
    for index, item in enumerate(topic.get("claims", [])):
        path = f"topics.{topic_index}.claims.{index}"
        # Older checkpoints recorded deterministic additions at source level,
        # before per-claim audit paths existed. They still need a real delta
        # audit, even though the earlier whole-stage audit says 'performed'.
        if (item.get("kind") == "public" and path not in pending
                and review.get("claim_semantic_reviews", {}).get(path) != "performed"
                and any(ref.get("source_id") in review.get("cross_stage_deterministic_only_source_ids", [])
                        for ref in item.get("evidence", []))):
            pending.append(path)
        if (item.get("kind") == "public" and "flytbase" in item.get("text", "").casefold()
                and re.search(r"collaborat|partner|deploy|uses|used|using", item.get("text", ""), re.I)
                and not _unsupported_denial(item.get("text", ""))
                and path not in pending and (review.get("semantic_review") == "performed"
                                             or review.get("claim_semantic_reviews", {}).get(path) == "performed")
                and not any(path_affects_claim(error, path) for error in errors)
                and not check_claim(Claim.model_validate(item), run.sources, run.input, run.as_of_date)):
            already_documented.update(r["source_id"] for r in item.get("evidence", []))
    additions = [(sid, c) for sid, c in inspected
                 if (sid, c.text) not in claim_keys and sid not in already_documented]
    prior_denials = [c for c in topic.get("claims", [])
                     if _unsupported_denial(c.get("text", ""))]
    prior_gaps = [g for g in topic.get("gaps", []) if _unsupported_denial(g)]
    prior_warnings = [w for w in research_stage.warnings if _unsupported_denial(w)]
    if not additions and not prior_denials and not prior_gaps and not prior_warnings and pending == pending_before:
        return False

    # Preserve original claim indexes: semantic findings cite numeric paths.
    # Changing list positions would incorrectly attach old audit verdicts to
    # other claims. Supersede a denial in-place, keeping its text in run.logs.
    for index, previous in enumerate(topic.get("claims", [])):
        if _unsupported_denial(previous.get("text", "")):
            topic["claims"][index] = Claim(
                text="Earlier claim of no public FlytBase relationship was superseded by a subsequently inspected official case study.",
                kind="unknown", evidence=[], input_quote="",
                uncertainty="See cross-stage reconciliation record and original source. Buyer/site scope is still unknown.",
                financial_context=None, event_date="",
            ).model_dump()
    for sid, new_claim in additions:
        pending.append(f"topics.{topic_index}.claims.{len(topic['claims'])}")
        topic["claims"].append(new_claim.model_dump())
    topic["gaps"] = [g for g in topic.get("gaps", []) if not _unsupported_denial(g)]
    scope_warning = ("Published company-level collaboration does not establish the buyer's "
                     "division, named stakeholder, three proposed sites or currently available partner capacity.")
    if scope_warning not in topic["gaps"]:
        topic["gaps"].append(scope_warning)
    research_stage.warnings = [w for w in research_stage.warnings if not _unsupported_denial(w)]
    stale_messages = {f"{TARGET_TOPIC}: no verified findings.",
                      f"{TARGET_TOPIC}: no public finding cleared source and semantic checks."}
    # The verified first-party claim replaces only this topic's stale warning;
    # no missing reporting-line, investor or financial research is concealed.
    research_stage.warnings = [w for w in research_stage.warnings if w not in stale_messages]
    review.setdefault(
        "cross_stage_deterministic_only_source_ids", []
    ).extend(sid for sid, _ in additions)
    if pending and PENDING_REVIEW_WARNING not in research_stage.warnings:
        research_stage.warnings.append(PENDING_REVIEW_WARNING)
    research_stage.output.setdefault("cross_stage_reconciliation", []).append({
        "at": now(), "method": "exact passage in inspected first-party customer case study",
        "source_ids": [sid for sid, _ in inspected],
        "validation": "deterministic citation/quote check; NOT independent AI semantic re-audit",
        "scope": "company-level only; new proposed sites and actual buyer identity unverified",
    })
    # Keep stage marked partial if genuine research gaps remain. Do not
    # override technical_status or semantic-review provenance from Stage 2.
    if research_stage.warnings:
        research_stage.status, research_stage.evidence_status = "partial", "partial"
    run.logs.append({
        "event": "cross_stage_customer_evidence_reconciled", "at": now(),
        "source_ids": [sid for sid, _ in inspected],
        "removed_claims": prior_denials, "removed_gaps": prior_gaps,
        "removed_warnings": prior_warnings,
        "note": "Local reconciliation after Stage 4; original generated denials kept in this log. No provider request.",
    })
    return True
