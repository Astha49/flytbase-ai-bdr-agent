"""Mechanical provenance checks complement (but cannot replace) semantic review."""
import re
from datetime import date
from .models import Claim, Source
from .qualification import normalise


def resolve_audit_path(path: str, data: dict) -> str:
    """Unlocatable audit errors apply globally rather than silently escaping the gates."""
    path = re.sub(r"\[(\d+)\]", r".\1", path).removeprefix("output.").strip(".")
    current = data
    resolved = []
    try:
        for part in path.split(".") if path else []:
            # Audit payloads wrap each Claim in `claim`, but application output
            # stores it directly. Remove ONLY that demonstrably redundant wrapper.
            if part == "claim" and isinstance(current, dict) and {"text", "kind", "evidence"}.issubset(current) and "claim" not in current:
                continue
            current = current[int(part)] if isinstance(current, list) else current[part]
            resolved.append(part)
    except (KeyError, IndexError, ValueError, TypeError):
        return ""
    return ".".join(resolved)


def path_affects_claim(error_path: str, claim_path: str) -> bool:
    return (not error_path or error_path == claim_path or error_path.startswith(claim_path + ".")
            or claim_path.startswith(error_path + "."))


def unresolved_paths(findings):
    """A claim-specific semantic caveat is unresolved, not verification.

    General metadata warnings remain visible without invalidating unrelated
    findings. Missing/rejected audits (global errors) still fail closed.
    """
    return [f.get("path", "") for f in findings if f.get("severity") == "error"
            or (f.get("severity") == "warning" and f.get("origin") == "semantic" and f.get("path"))]


def iter_claims(data, path=""):
    if isinstance(data, dict):
        if {"text", "kind", "evidence", "input_quote", "financial_context"}.issubset(data):
            yield path, Claim.model_validate(data)
        else:
            for key, value in data.items():
                yield from iter_claims(value, f"{path}.{key}".strip("."))
    elif isinstance(data, list):
        for i, value in enumerate(data):
            yield from iter_claims(value, f"{path}.{i}".strip("."))


def check_claim(claim: Claim, sources: dict[str, Source], enquiry: str, as_of_date: str) -> list[str]:
    issues = []
    if claim.kind == "supplied":
        if not claim.input_quote.strip() or normalise(claim.input_quote) not in normalise(enquiry):
            issues.append("Supplied assertion lacks a matching enquiry quote.")
        text, quote = claim.text.casefold(), claim.input_quote.casefold()
        if "?" not in text:
            approval = re.search(r"\b(?:approved|allocated|authori[sz]ed|secured)\b", text)
            if approval and re.search(r"budget|funding|funds", text) and not re.search(r"\b(?:not|no|unapproved|unconfirmed)\b", text):
                if not re.search(r"\b(?:approved|allocated|authori[sz]ed|secured)\b", quote) or re.search(r"\b(?:not|no|pending)\b", quote):
                    issues.append("A supplied budget discussion or missing approval cannot substantiate an approved-funding assertion.")
            if re.search(r"final (?:decision|approv)|purchasing authority|sign.off authority", text) and not re.search(r"\b(?:not|no|unknown|unverified)\b", text):
                if not re.search(r"final (?:decision|approv)|purchasing authority|sign.off", quote):
                    issues.append("A supplied title does not establish final purchasing authority.")
        numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim.text))
        if not numbers.issubset(set(re.findall(r"\d+(?:[.,]\d+)*", claim.input_quote))):
            issues.append("Supplied numeric facts are absent from the cited enquiry passage.")
    if claim.kind == "public" and not claim.evidence:
        issues.append("Public assertion has no supporting evidence.")
    if (claim.kind in {"public", "unknown"} and re.search(
            r"not (?:reflected|disclosed|listed).{0,35}(?:any|all) public|does not (?:name|disclose).{0,100}(?:public filings|public records)|no publicly available", claim.text, re.I)
            and not re.search(r"(?:this run|retrieved|reviewed|inspected) (?:materials|sources|documents|records)|in this run", claim.text, re.I)):
        issues.append("A search gap cannot establish absence from all public records; scope the unknown to reviewed sources.")
    if claim.kind == "inference" and not claim.uncertainty.strip():
        issues.append("Inference is missing its uncertainty or recommendation label.")
    quote_text = " ".join(r.quote for r in claim.evidence)
    if claim.kind == "unknown" and re.search(r"\b(?:has deployed|has approved|reports to|serves|achieved)\b", claim.text, re.I) and not re.search(r"\b(?:not|unknown|unverified|whether|if)\b|\?", claim.text, re.I):
        issues.append("A positive assertion is labelled unknown; uncertainty cannot bypass evidence requirements.")
    if re.search(r"\b(?:we|flytbase|this (?:solution|deployment))\s+(?:will|can)\s+(?:guarantee|(?:reduce|save|deliver|achieve).{0,50}\d+\s*%)", claim.text, re.I):
        issues.append("Unsupported prospect-specific outcome promise; no guaranteed ROI or deployment result.")
    if claim.kind == "public" and re.search(r"24/7|round.the.clock", claim.text, re.I) and not re.search(r"24/7|round.the.clock", quote_text, re.I):
        issues.append("Continuous-operation assertion is not established by its quoted evidence.")
    if claim.kind == "public" and re.search(r"validat\w* feasibility|guarantee\w* (?:roi|savings|outcomes)", claim.text, re.I):
        issues.append("A case study cannot establish guaranteed outcomes or prospect-specific feasibility; discovery is required.")
    commodities = {"iodine", "lithium", "copper", "nitrate", "coal", "iron", "gold"}
    mentioned = set(re.findall(r"\b[a-z]+\b", claim.text.casefold())) & commodities
    quoted = set(re.findall(r"\b[a-z]+\b", quote_text.casefold())) & commodities
    if claim.kind == "public" and mentioned and quoted and mentioned.isdisjoint(quoted):
        issues.append("Deployment commodity differs from its supporting passage; do not transfer an existing deployment to the proposed sites.")
    if claim.kind == "public" and re.search(r"reports? (?:directly )?to|reporting (?:directly )?to", claim.text, re.I) and not re.search(r"reports? (?:directly )?to|reporting|report to", quote_text, re.I):
        issues.append("Reporting relationship is not explicitly established by the quoted evidence.")
    for ref in claim.evidence:
        from .normalization import has_omission_marker
        if has_omission_marker(ref.quote):
            issues.append("Evidence quote crosses an extraction omission; cite one contiguous inspected passage.")
        source = sources.get(ref.source_id)
        if source is None:
            issues.append(f"Unknown source ID: {ref.source_id}.")
            continue
        inspected = source.access in {"inspected_page", "inspected_pdf"}
        body = source.text if inspected else source.search_context
        if not ref.quote.strip() or normalise(ref.quote) not in normalise(body):
            issues.append(f"Evidence passage is absent from {ref.source_id}.")
        if not inspected:
            issues.append(f"{ref.source_id} has search-summary support only; original page not inspected.")
        if source.publication_date:
            try:
                if date.fromisoformat(source.publication_date[:10]) > date.fromisoformat(as_of_date):
                    issues.append(f"{ref.source_id} publication is after the run date.")
            except ValueError:
                issues.append(f"{ref.source_id} publication date is not machine-verifiable.")
    # High-risk financial quantities require explicit financial context, not merely a citation.
    financial = re.search(r"(\$|€|£|\b(?:USD|CLP|EUR|US\$)\b|capex|opex|capital expenditure|investment)", claim.text, re.I)
    quantities = re.findall(r"\b\d+(?:[.,]\d+)*\b", claim.text)
    monetary_quantity = any(not re.fullmatch(r"20\d{2}", n) for n in quantities)
    if claim.kind in {"public", "inference"} and financial and monetary_quantity:
        context = claim.financial_context
        if not context or any(not v.strip() or v.casefold() in {"unknown", "n/a", "not found"}
                              for k, v in context.model_dump().items() if k != "publication_date"):
            issues.append("Financial quantity lacks verified currency, units, reporting period, publication date or scope.")
        if context:
            currency_patterns = {"USD": r"\bUSD\b|US\$|U\.S\.\$", "EUR": r"\bEUR\b|€",
                                 "GBP": r"\bGBP\b|£", "CLP": r"\bCLP\b|CL\$|Ch\$"}
            currency_pattern = currency_patterns.get(context.currency.upper(), re.escape(context.currency))
            if not re.search(currency_pattern, quote_text, re.I):
                issues.append("Financial currency is not established by the quoted evidence.")
            if context.units.casefold() in {"million", "billion", "thousand"} and not re.search(r"\b" + re.escape(context.units) + r"s?\b", quote_text, re.I):
                issues.append("Financial units conflict with or are absent from quoted evidence.")
            if re.search(r"drone|inspection project", claim.text, re.I) and re.search(r"approv|allocat", claim.text, re.I) and re.search(r"company|group|corporate", context.scope, re.I):
                issues.append("Company-wide spending does not establish an approved budget for this drone project.")
            numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim.text))
            evidence_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", quote_text))
            if not numbers.issubset(evidence_numbers):
                issues.append("Financial figures/periods are absent from the quoted evidence; conversions need explicit verification.")
            period_years = set(re.findall(r"20\d{2}", context.reporting_period))
            if not period_years.issubset(set(re.findall(r"20\d{2}", quote_text))):
                issues.append("Financial reporting period is not established by its quoted evidence.")
            dates = {sources[r.source_id].publication_date[:10] for r in claim.evidence
                     if r.source_id in sources and sources[r.source_id].publication_date}
            date_unknown = context.publication_date.strip().casefold() in {"", "unknown", "not available", "not found", "not established"}
            if date_unknown:
                if dates or not re.search(r"publication.{0,30}(?:unknown|unavailable|not|unverified)|date.{0,20}(?:unknown|not established)", claim.uncertainty, re.I):
                    issues.append("Financial publication date must use available metadata or be explicitly disclosed as unknown.")
            try:
                if not date_unknown and date.fromisoformat(context.publication_date[:10]) > date.fromisoformat(as_of_date):
                    issues.append("Financial claim publication date is after the run date.")
                if not date_unknown and dates and context.publication_date[:10] not in dates:
                    issues.append("Financial publication date conflicts with retrieved source metadata.")
                if not date_unknown and not dates and context.publication_date[:10] not in quote_text:
                    issues.append("Financial publication date has no retrieved metadata or explicit quoted support.")
            except ValueError:
                issues.append("Financial claim publication date is not an ISO date; review the reporting context.")
    if claim.event_date:
        try:
            if date.fromisoformat(claim.event_date[:10]) > date.fromisoformat(as_of_date) and not re.search(
                    r"planned|expected|scheduled|proposed|forecast|future|target", claim.text, re.I):
                issues.append("Future event is described without a forward-looking qualifier.")
        except ValueError:
            issues.append("Event date is not an ISO date; do not imply an established event date.")
    return issues


def audit_mechanical(data: dict, sources: dict[str, Source], enquiry: str, as_of_date: str) -> list[dict]:
    return [{"path": path, "severity": "error", "reason": reason}
            for path, claim in iter_claims(data) for reason in check_claim(claim, sources, enquiry, as_of_date)]


def supported(claim: Claim, sources: dict[str, Source], enquiry: str, as_of_date: str) -> bool:
    return claim.kind == "public" and bool(claim.evidence) and not check_claim(claim, sources, enquiry, as_of_date)
