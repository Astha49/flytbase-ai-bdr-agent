"""Mechanical format repairs only; never invent dates, facts or evidence."""
import re
from email.utils import parsedate_to_datetime
from datetime import datetime


def has_omission_marker(text):
    """Synthetic extraction separators are not part of the original document."""
    return bool(re.search(r"\[HTML excerpt at character|\[[^\]\n]*context omitted[^\]\n]*\]|omitted text between excerpts", text, re.I))


def publication_iso(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (ValueError, TypeError):
            return value


def expand_verbatim(quote, body):
    # Recover typographic variants from the actual source (e.g. nonbreaking vs ASCII hyphen).
    def escaped(part):
        pattern = ""
        for char in part:
            if char in "-‐‑‒–—":
                pattern += "[-‐‑‒–—]"
            elif char in "'‘’":
                pattern += "['‘’]"
            elif char.isspace():
                pattern += r"\s+"
            else:
                pattern += re.escape(char)
        return pattern
    parts = [p.strip() for p in re.split(r"\.{3}|…", quote) if p.strip()]
    pattern = r"[\s\S]{0,350}?".join(escaped(p) for p in parts)
    if not pattern:
        return quote
    match = re.search(pattern, body, re.I)
    return match.group() if match and len(match.group()) <= 650 and not has_omission_marker(match.group()) else quote


def normalize_claims(data, sources=None):
    if isinstance(data, dict):
        if {"text", "kind", "evidence", "event_date"}.issubset(data):
            value = data["event_date"].strip()
            if value.casefold() in {"unknown", "n/a", "not known", "not disclosed", "not available", "none"}:
                data["event_date"] = ""
            if re.fullmatch(r"20\d{2}", value):
                data["event_date"] = ""
                data["uncertainty"] = (data["uncertainty"] + f" Event year stated as {value}; full date not established.").strip()
            if data["kind"] != "supplied":
                data["input_quote"] = ""
            for ref in data["evidence"]:
                source = (sources or {}).get(ref["source_id"])
                if source and source.text:
                    ref["quote"] = expand_verbatim(ref["quote"], source.text)
            context = data.get("financial_context")
            if (context and context.get("publication_date", "").casefold() in {"", "unknown", "not available", "not found", "not established"}
                    and not any((sources or {}).get(r["source_id"]) and sources[r["source_id"]].publication_date for r in data["evidence"])
                    and not re.search(r"publication.{0,30}(?:unknown|unavailable|not|unverified)|date.{0,20}(?:unknown|not established)", data["uncertainty"], re.I)):
                prior = data["uncertainty"].strip().rstrip(".")
                if prior.casefold() in {"none", "n/a", "not applicable"}:
                    prior = ""
                data["uncertainty"] = (prior + ". Publication date unknown in retrieved metadata.").lstrip(". ")
        else:
            for child in data.values():
                normalize_claims(child, sources)
    elif isinstance(data, list):
        for child in data:
            normalize_claims(child, sources)
    return data
