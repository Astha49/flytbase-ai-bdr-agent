"""Smaller model contexts preserve original evidence in the saved registry."""
import re
from .grounding import iter_claims


def lead_context(qualification):
    lead = qualification.get("lead", {})
    return {**{k: lead.get(k, "") for k in ["name", "email", "title", "company", "geography", "industry", "need", "referral"]},
            "bant": {k: {"status": lead[k]["status"], "questions": lead[k]["questions"][:2]}
                     for k in ["budget", "authority", "need_dimension", "timeline"] if k in lead},
            "priority": qualification.get("priority_score"), "completeness": qualification.get("qualification_completeness_percent")}


def evidence_batch(sources, ids, settings, claims=None, max_sources=8, max_chars=None, focus="", window_offset=0):
    selected = [sid for sid in dict.fromkeys(ids) if sid in sources][:max_sources]
    if not selected:
        return {}
    per_source = min(settings.evidence_chars_per_source, (max_chars or settings.evidence_chars_per_request) // len(selected))
    refs = {}
    for _, claim in iter_claims(claims or {}):
        for ref in claim.evidence:
            quotes = refs.setdefault(ref.source_id, [])
            if ref.quote not in quotes:
                quotes.append(ref.quote)
    payload = {}
    for sid in selected:
        source = sources[sid]
        body = source.text or source.search_context
        windows = []
        if refs.get(sid):
            for quote in refs[sid]:
                position = body.find(quote)
                if position >= 0:
                    windows.append(body[max(0, position - 100):position + len(quote) + 100])
        if not windows:
            # Pick source sentences by query overlap; body remains verbatim within each window.
            terms = set(re.findall(r"[a-zA-Z]{5,}", " ".join(source.queries).casefold()))
            # Preserve neighbouring text around each selected sentence. In
            # financial reports the value, currency, units and year often sit
            # in adjacent table cells or lines, not in the same sentence.
            chunks = list(re.finditer(r"[^.!?\n]+(?:[.!?]|(?=\n)|$)", body))
            sentences = [(m.start(), m.end(), m.group(0)) for m in chunks]
            query_string = " ".join(source.queries).casefold()
            financial_intent = any(x in query_string for x in ("capital", "financial", "investment", "earnings", "opex"))
            materials_intent = any(x in query_string for x in ("case study", "customer deployment", "partner", "integrator"))
            def relevance(pair):
                _, _, sentence = pair
                low = sentence.casefold()
                score = sum(2 for t in terms if t in low)
                score += sum(10 for t in set(re.findall(r"[a-zA-Z]{5,}", focus.casefold())) if t in low)
                if financial_intent:
                    score += 12 if re.search(r"capital expenditur|investment plan|capital investment|research and development", low) else 0
                    score += 6 if re.search(r"(?:us\$|usd|\$)\s*\d|\b\d{2,}(?:[.,]\d+)?\s*(?:million|billion)", low) else 0
                    score += 2 if re.search(r"20[12]\d", low) else 0
                if materials_intent:
                    score += 8 if re.search(r"inspection|integration|deployment|drone|partner|autonom|system integrator", low) else 0
                    score += 4 if re.search(r"lithium|iodine|mine|survey|geograph|chile|peru", low) else 0
                return score
            ranked = sorted(sentences, key=lambda row: (-relevance(row), row[0]))
            windows = [body[max(0, start - 90):min(len(body), end + 125)]
                       for start, end, text in ranked[window_offset:window_offset + 8] if text.strip()]
        windows = list(dict.fromkeys(windows))
        packed = []
        for window in windows:
            if len("\n[…context omitted…]\n".join([*packed, window])) <= per_source:
                packed.append(window)
        text = "\n[…context omitted…]\n".join(packed) if packed else windows[0][:per_source] if windows else ""
        payload[sid] = {"source_id": sid, "url": source.url, "title": source.title[:140],
                        "publication_date": source.publication_date, "access": source.access,
                        "inspection_method": source.inspection_method, "text": text if source.text else "",
                        "search_context": text if not source.text else "", "context_is_excerpt": True}
    return payload


def audit_payload(data, sources, only_paths=None):
    """Deduplicate repeated case-dimension quotes while keeping exact audit paths.

    Free-text subjects, titles and routing strings are audited too; they cannot
    bypass grounding merely by living outside the Claim schema.
    """
    claims, quotes, keys, fields = [], {}, {}, []
    for path, claim in iter_claims(data):
        if only_paths is not None and path not in only_paths:
            continue
        value = {k: v for k, v in claim.model_dump().items() if v not in (None, "", [])}
        references = []
        for ref in claim.evidence:
            key = (ref.source_id, ref.quote)
            if key not in keys:
                label = "Q" + str(len(keys) + 1)
                keys[key] = label
                source = sources.get(ref.source_id)
                body = (source.text or source.search_context) if source else ""
                position = body.find(ref.quote)
                quotes[label] = {"source_id": ref.source_id, "quote": ref.quote,
                                 "context": body[max(0, position - 80):position + len(ref.quote) + 80] if position >= 0 else "Quote absent from source."}
            references.append({"source_id": ref.source_id, "quote_ref": keys[key]})
        if references:
            value["evidence"] = references
        claims.append({"path": path, "claim": value})
    all_ids = list(dict.fromkeys(q["source_id"] for q in quotes.values()))
    def visit(value, path="", source_ids=None):
        if isinstance(value, dict):
            if "kind" in value and "text" in value:
                return
            bound = value.get("source_id") or value.get("preferred_source_id")
            source_ids = [bound] if isinstance(bound, str) and bound in sources else source_ids
            for key, child in value.items():
                if key not in {"source_id", "groundedness"}:
                    visit(child, f"{path}.{key}".strip("."), source_ids)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{path}.{i}".strip("."), source_ids)
        elif isinstance(value, str) and value:
            record = {"path": path, "text": value}
            # Free-text fields must retain their related evidence even when
            # partitioned away from the candidate Claims. This is context for
            # audit, never automatic approval of a title or recommendation.
            ids = source_ids if source_ids is not None else all_ids
            terms = set(re.findall(r"[a-z]{4,}", value.casefold()))
            related = [key for key, q in quotes.items() if q["source_id"] in ids]
            related.sort(key=lambda key: -len(terms & set(re.findall(r"[a-z]{4,}", quotes[key]["quote"].casefold()))))
            # Bound repeated context for advisory strings. All Claim evidence
            # remains audited independently; this is supplementary context only.
            record["context_quote_refs"] = related[:2] if not path.endswith(".title") else related[:1]
            record["context_source_ids"] = list(dict.fromkeys(
                [*(source_ids or []), *(quotes[key]["source_id"] for key in record["context_quote_refs"])]))
            if path.rsplit(".", 1)[-1] in {"commercial_owner", "implementation_owner", "recommended_motion", "next_action"}:
                record["role"] = "proposed sales responsibility or next action; not an existing assignment"
            # A case-study title can be checked against the *inspected source's
            # own metadata*. That is evidence for the document title ONLY,
            # never for an operational outcome or prospect-site deployment.
            if path.endswith(".title"):
                parent_path = path.rsplit(".", 1)[0]
                parent = data
                try:
                    for component in parent_path.split("."):
                        parent = parent[int(component)] if isinstance(parent, list) else parent[component]
                except (KeyError, IndexError, TypeError, ValueError):
                    parent = None
                if isinstance(parent, dict):
                    source = sources.get(parent.get("source_id", ""))
                    if source and source.access in {"inspected_page", "inspected_pdf"}:
                        record["inspected_source_title"] = source.title
                        record["source_title_matches"] = (value == source.title)
                        record["title_provenance"] = source.title_basis
            fields.append(record)
    if only_paths is None:
        visit(data)
    cited = dict.fromkeys([*all_ids, *(sid for field in fields for sid in field["context_source_ids"])])
    return {"claims_with_paths": claims, "quotes": quotes, "review_fields": fields,
            "sources": {sid: {"url": sources[sid].url, "title": sources[sid].title,
                              "title_basis": sources[sid].title_basis,
                              "access": sources[sid].access, "publication_date": sources[sid].publication_date,
                              "context_is_excerpt": True} for sid in cited if sid in sources}}


def audit_batches(data, sources, target_tokens=3200, only_paths=None):
    """Partition a large groundedness audit without dropping claims or renumbering paths.

    The single-call form remains the default. Large case-study/finance records can
    otherwise exceed the provider's per-request limit, making every finding
    unreviewable. All quote IDs and paths are retained across partitions; each
    batch carries only metadata used by its own claims.
    """
    import json
    from .provider import estimate_tokens

    payload = audit_payload(data, sources, only_paths)
    if estimate_tokens(json.dumps(payload, ensure_ascii=False)) <= target_tokens:
        return [payload]

    atoms = [("claims_with_paths", x) for x in payload["claims_with_paths"]]
    atoms += [("review_fields", x) for x in payload["review_fields"]]
    if not atoms:
        return [payload]

    def build(rows):
        claims = [item for category, item in rows if category == "claims_with_paths"]
        fields = [item for category, item in rows if category == "review_fields"]
        quote_keys = {reference["quote_ref"] for row in claims
                      for reference in row["claim"].get("evidence", [])
                      if "quote_ref" in reference}
        quote_keys.update(key for field in fields for key in field.get("context_quote_refs", []))
        quotes = {key: value for key, value in payload["quotes"].items() if key in quote_keys}
        ids = {item["source_id"] for item in quotes.values()}
        ids.update(sid for field in fields for sid in field.get("context_source_ids", []))
        return {"claims_with_paths": claims, "quotes": quotes,
                "review_fields": fields,
                "sources": {sid: record for sid, record in payload["sources"].items() if sid in ids}}

    batches, current = [], []
    for atom in atoms:
        proposed = current + [atom]
        if current and estimate_tokens(json.dumps(build(proposed), ensure_ascii=False)) > target_tokens:
            batches.append(build(current))
            current = [atom]
        else:
            current = proposed
    if current:
        batches.append(build(current))
    return batches
