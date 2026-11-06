"""Optional researcher-supplied PUBLIC URL discovery leads, not verified research.

The cache pack can nominate links for retrieval. Its claims, suggested winners,
partner recommendations and evidence labels are NEVER fed to the model or used
as proofs. Only original pages inspected by the existing source reader may be cited.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from .config import ROOT
from .evidence import canonical_url, source_family_key

PACK_DIR = ROOT / "data" / "research"
_ALLOWED_GROUPS = frozenset(("organisation", "finance", "current", "materials", "partners"))


def candidates_for_lead(lead: dict, group: str, root: Path | None = None) -> list[dict]:
    """Return bounded metadata-only URL candidates for a *matching* buyer account.

    An unrelated customer must not inherit SQM's prior source hints. Strong
    domain/account equivalence is required, and source safety is delegated to
    the application's canonical URL and HTTP public-host protections.
    """
    if group not in _ALLOWED_GROUPS:
        return []
    folder = root if root is not None else PACK_DIR
    folder = Path(folder)
    company = str(lead.get("company", ""))
    domain = str(lead.get("domain", "")).lower().strip()
    if not company or not domain:
        return []
    collected = []
    for path in sorted(folder.glob("*_evidence_pack.json"))[:8]:
        try:
            if path.stat().st_size > 150_000:
                continue
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if pack.get("schema") != "flytbase_public_research_evidence_pack_v1":
            continue
        profile = pack.get("lead_supplied_input") or {}
        pack_email = str(profile.get("email", "")).lower()
        pack_company = str(profile.get("company", ""))
        pack_domain = pack_email.rpartition("@")[2]
        company_label = lambda x: re.sub(r"[^a-z0-9]", "", x.lower().split("(")[0])
        if not pack_domain or pack_domain != domain or company_label(pack_company) != company_label(company):
            continue
        facts = pack.get("public_facts") or []
        if not isinstance(facts, list):
            continue
        tags = {}
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            category = str(fact.get("category", "")).lower()
            for sid in fact.get("source_ids", []):
                if not isinstance(sid, str):
                    continue
                tags.setdefault(sid, set()).add(category)
        source_ids_for_cases = {c.get("source_id") for c in pack.get("case_studies", []) if isinstance(c, dict)}
        for source in pack.get("sources", [])[:30]:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                continue
            try:
                url = canonical_url(source["url"])
            except ValueError:
                continue
            host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
            if not host or not host.endswith((".gov", ".com", ".cl")):
                continue
            sid = source.get("id")
            categories = tags.get(sid, set())
            path_text = urlsplit(url).path.lower()
            if group == "finance":
                suitable = bool(categories & {"financial", "finance", "investment", "investor",
                                              "earnings", "finance_and_strategy", "investor_priorities",
                                              "news_and_investor_priorities"}) or host == "sec.gov"
            elif group == "organisation":
                suitable = bool(categories & {"organizational", "organisation", "governance", "operations"})
            elif group == "current":
                suitable = bool(categories & {"news", "strategic", "corporate", "customer", "operations",
                                              "earnings", "news_and_investor_priorities", "finance_and_strategy",
                                              "existing_relationship", "referral_relationship"})
            elif group == "materials":
                suitable = host == "flytbase.com" and ("/case-studies/" in path_text or sid in source_ids_for_cases)
            else:
                suitable = host == "flytbase.com" and ("/partner" in path_text or "/case-studies/" in path_text)
            if not suitable:
                continue
            collected.append({"url": url, "title": str(source.get("title") or url)[:220],
                              "retrieval_query": f"public source candidate for {company} ({group})"})
    unique, seen = [], set()
    for item in collected:
        key = source_family_key(item["url"])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    # Hard limit: candidate URLs must not flood source inspections.
    return unique[:5]
