"""Read-only evidence views shared by the UI and downstream sales outputs."""
from .grounding import supported, path_affects_claim, check_claim, unresolved_paths
from .models import Claim


def cleared_claims(output, sources, enquiry, as_of, prefix="topics"):
    review = output.get("groundedness", {})
    errors = unresolved_paths(review.get("mechanical_and_semantic_findings", []))
    found = []
    for i, topic in enumerate(output.get(prefix, [])):
        for j, item in enumerate(topic.get("claims", [])):
            path = f"{prefix}.{i}.claims.{j}"
            per_claim = review.get("claim_semantic_reviews", {}).get(path)
            if path in review.get("unreviewed_claim_paths", []):
                continue
            if review.get("semantic_review") != "performed" and per_claim != "performed":
                continue
            # Backward-compatible protection for early reconciliation records
            # that marked only source IDs and omitted claim-level audit paths.
            if "unreviewed_claim_paths" not in review and per_claim != "performed" and any(
                r["source_id"] in review.get("cross_stage_deterministic_only_source_ids", []) for r in item.get("evidence", [])
            ):
                continue
            claim = Claim.model_validate(item)
            if supported(claim, sources, enquiry, as_of) and not any(path_affects_claim(p, path) for p in errors):
                found.append({"topic": topic.get("name", ""), "path": path, "claim": item})
    return found


def backed_interpretation(claim, sources, enquiry, as_of):
    """A cited relevance judgement is an inference, not a publicly established fact."""
    return claim.kind in {"public", "inference"} and bool(claim.evidence) and not check_claim(claim, sources, enquiry, as_of)


def handoff_highlights(output, sources, enquiry, as_of):
    import re
    rows = cleared_claims(output, sources, enquiry, as_of)
    selected, words, used_topics, used_paths = [], [], set(), set()
    for diverse in (True, False):
        for row in rows:
            if row["path"] in used_paths:
                continue
            if diverse and row["topic"] in used_topics:
                continue
            tokens = set(re.findall(r"[a-z]{3,}", row["claim"]["text"].casefold())) - {"the", "and", "has", "its", "with", "from", "across", "for"}
            if any(len(tokens & other) / max(1, len(tokens | other)) >= .60 for other in words):
                continue
            selected.append(row["claim"])
            used_paths.add(row["path"])
            words.append(tokens)
            used_topics.add(row["topic"])
            if len(selected) == 3:
                return selected
    return selected
