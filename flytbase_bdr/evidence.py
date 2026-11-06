"""Bounded public-page/PDF reader and shared source registry."""
import hashlib
import ipaddress
import re
import socket
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from .models import Lead, Source
from .normalization import publication_iso


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("Only public HTTP(S) URLs without credentials are permitted.")
    if p.port not in {None, 80, 443}:
        raise ValueError("Nonstandard URL port blocked.")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def assert_public_url(url: str):
    host = urlsplit(canonical_url(url)).hostname
    addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private, loopback or reserved network destination blocked.")


def is_flytbase(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host == "flytbase.com" or host.endswith(".flytbase.com")


def derive_queries(lead: Lead, as_of_date: str, expanded=False, deep=False) -> dict[str, list[str]]:
    """Ten targeted searches, based ONLY on the incoming customer enquiry.

    No customer, chosen case study, partner name, URL or financial figure is
    preselected. Reporting, financial documents and existing customer
    relationships each receive their own search rather than a broad query.
    """
    acronym = re.search(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", lead.company)
    brand = acronym.group(1) if acronym else lead.company.strip()
    company = f'"{brand}"'
    legal_name = lead.company.split("(", 1)[0].strip()
    recent_years = f"{int(as_of_date[:4]) - 1} {as_of_date[:4]}"
    geography = lead.geography.strip()
    # Include the enquiry's actual use case in the first case-study search.
    # A generic industry-only query can miss ports, perimeter-security, etc.
    # Keep it bounded so Tavily searches remain focused for long enquiries.
    need_terms = " ".join(lead.need.split()[:8])
    use_case = " ".join((lead.industry, need_terms, geography)).strip()
    referred = f'"{lead.referral}"' if lead.referral.strip() else use_case
    report_year = int(as_of_date[:4]) - 1
    queries = {
        "organisation": [
            f'{company} official executive leadership business divisions {geography} governance {lead.domain}',
            f'{company} "{legal_name}" {report_year} annual report management business segments reporting structure',
        ],
        "finance": [
            f'{company} {report_year} annual report 20-F capital expenditures site:sec.gov/Archives/edgar/data',
            f'{company} investor relations {as_of_date[:4]} results annual report capital expenditures operating costs',
        ],
        "current": [
            f'{company} official {lead.industry} operational strategy announcements {geography} {as_of_date[:4]} news',
            f'site:flytbase.com {company} autonomous inspections existing deployment',
        ],
        "materials": [
            f'site:flytbase.com/case-studies {company} case study autonomous drone inspection {lead.industry} {need_terms}'.strip(),
            f'site:flytbase.com/case-studies {referred} case study autonomous drones {lead.industry}',
        ],
        "partners": [
            f'site:flytbase.com/partner "{geography}" "System Integrator"',
            f'site:flytbase.com/case-studies {company} {geography} integrator implementation partner',
        ],
    }
    if expanded:
        queries["finance"].append(f'{company} {lead.domain} {recent_years} technology investment automation operating expenses investor priorities')
        queries["partners"].append(f'FlytBase drone integrator "{geography}" implementation maintenance {lead.industry} {need_terms}')
    if deep:
        queries["organisation"].append(f'{company} {lead.domain} {as_of_date[:4]} board executive leadership business segments official')
        queries["finance"].append(f'{company} {lead.domain} {recent_years} shareholder earnings investor priorities capital allocation')
        queries["current"].append(f'{company} official {as_of_date[:4]} strategic partnership corporate change operations {geography}')
        queries["materials"].append(f'site:flytbase.com/case-studies {lead.industry} {geography} {need_terms} operational deployment')
    return queries



def source_family_key(url: str) -> str:
    """Collapse mirrored website variants during *selection*, never alter source URLs.

    We retain every original URL, and prefer inspecting one authoritative page
    over three www/language mirrors that offer essentially the same information.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/").lower()
    if host == "flytbase.com":
        path = re.sub(r"^/(?:es|fr|de|ar|pt|it)(?=/)", "", path)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.casefold().startswith("utm_") and k.casefold() not in {"fbclid", "gclid"}]
    return f"{host}{path}" + ("?" + urlencode(sorted(query)) if query else "")




def is_issuer_document(source: Source, company: str, domain: str = "") -> bool:
    """Prevent an unrelated SEC registrant from being cited as the prospect.

    SEC hosts filings for thousands of issuers. Matching a search for '20-F'
    does not establish that the returned filing concerns the named account.
    Other websites still require ordinary evidence/semantic verification.
    """
    host = (urlsplit(source.url).hostname or "").casefold().removeprefix("www.")
    inspected = source.access in {"inspected_page", "inspected_pdf"} and bool(source.text)
    report = (source.access == "inspected_pdf" or urlsplit(source.url).path.casefold().endswith(".pdf")
              or bool(re.search(r"annual report|20.f|earnings release|financial statements", source.title, re.I)))
    if host != "sec.gov" and not (inspected and report):
        return True
    acronym = re.search(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", company)
    names = [acronym.group(1) if acronym else "", company.split("(")[0].strip(), domain.split(".")[0]]
    # Company-controlled report hosting establishes issuer context. A shared
    # CDN or another company's investor site does not. Body identity remains
    # required for SEC filings and mirrored reports.
    if host != "sec.gov" and any(len(n) >= 3 and n.casefold() in host.split(".") for n in names):
        return True
    # After inspecting an original filing, search snippets are NOT evidence of
    # identity; they can mention the query even when the returned issuer is wrong.
    preview = source.text[:2500] if source.access in {"inspected_page", "inspected_pdf"} and source.text else (
        source.title + " " + source.search_context[:2000])
    import unicodedata
    norm = lambda s: "".join(c for c in unicodedata.normalize("NFKD", s).casefold() if not unicodedata.combining(c))
    text = norm(preview)
    return any(len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(norm(name)) + r"(?!\w)", text)
               for name in names)


def rank_sources(ids: list[str], sources: dict[str, Source], group: str,
                 company: str = "", domain: str = "", referral: str = "") -> list[str]:
    """Rank public candidates, without choosing a specific company/case/partner.

    Results still come exclusively from live search. A source is not treated as
    verified until its own page is inspected, irrespective of ranking score.
    """
    acronym = re.search(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", company)
    brand = (acronym.group(1) if acronym else company).casefold().strip()
    domain_brand = domain.split(".")[0].casefold() if domain else ""
    def mentioned(text: str, term: str) -> bool:
        return bool(term and len(term) >= 2 and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))
    def rank(sid: str) -> int:
        source = sources[sid]
        url, title = source.url.casefold(), source.title.casefold()
        host = (urlsplit(source.url).hostname or "").casefold().removeprefix("www.")
        score = 10 if source.access in {"inspected_page", "inspected_pdf"} else 0
        if group in {"finance", "organisation"}:
            # Many unrelated 20-F reports share a generic "20-F" title. Do not
            # prioritize a different issuer merely because it is hosted by the SEC.
            preview = " ".join((source.title, source.search_context[:900], source.text[:1000]))
            company_terms = [part for part in (brand, domain_brand) if len(part) >= 3]
            # A search snippet often repeats the user's query even when the
            # SEC result belongs to a completely different registrant. Before
            # document inspection, rank generic filings conservatively.
            exact_issuer = any(mentioned(preview, term) for term in company_terms)
            if host in {"www.sec.gov", "sec.gov"}:
                if source.access in {"inspected_page", "inspected_pdf"}:
                    score += 110 if is_issuer_document(source, company, domain) else -145
                else:
                    title_identity = any(mentioned(source.title, term) for term in company_terms)
                    score += 55 if title_identity else -35
            company_host_hint = bool(domain_brand and domain_brand in host.split("."))
            score += 95 if host.startswith("ir.") and company_host_hint else 0
            score += 70 if company_host_hint else 0
            score += 35 if "investor" in host else 0
            score += 20 if "annual report" in title or "20-f" in title else 0
            if group == "finance" and ("capex" in preview.lower() or "capital expenditures" in preview.lower()):
                score += 20
            score -= 55 if any(x in host for x in ("bitget", "reddit", "stocktwits", "worldnews")) else 0
        elif group == "materials":
            score += 105 if is_flytbase(source.url) and "/case-studies/" in url else 0
            score += 35 if is_flytbase(source.url) and "/blog/" in url else 0
            score += 12 if is_flytbase(source.url) and "/webinars/" in url else 0
            score += 30 if mentioned(title, brand) else 0
            score += 20 if mentioned(title, referral) else 0
        elif group in {"partners", "current"}:
            score += 60 if is_flytbase(source.url) else 0
            score += 30 if mentioned(title, brand) else 0
            score += 20 if domain_brand and domain_brand in host else 0
            score += 15 if "partner" in url or "partner" in title else 0
        return score
    ordered = sorted(ids, key=rank, reverse=True)  # stable within equal-scoring results
    unique, families = [], set()
    for sid in ordered:
        family = source_family_key(sources[sid].url)
        if family not in families:
            unique.append(sid)
            families.add(family)
    return unique


def search_sources(result: dict, queries: list[str], sources: dict[str, Source]) -> list[str]:
    if "results" in result:
        ids = []
        for item in result["results"]:
            try:
                clean = canonical_url(item.get("url", ""))
            except ValueError:
                continue
            sid = "S_" + hashlib.sha256(clean.encode()).hexdigest()[:12]
            if sid not in sources:
                sources[sid] = Source(source_id=sid, url=clean, title=item.get("title") or clean,
                                      title_basis="search-result metadata; original document title not verified",
                                      retrieved_at=now(), access="search_excerpt_only",
                                      search_context=(item.get("content") or "")[:6000],
                                      publication_date=publication_iso(item.get("published_date") or ""),
                                      publication_date_basis="Tavily search metadata; not independently established" if item.get("published_date") else "not available")
            actual_queries = [item["retrieval_query"]] if item.get("retrieval_query") else queries
            sources[sid].queries = list(dict.fromkeys([*sources[sid].queries, *actual_queries]))
            if sid not in ids:
                ids.append(sid)
        return ids
    found = {}
    for item in result.get("output", []):
        if item.get("type") == "web_search_call":
            for src in item.get("action", {}).get("sources", []):
                if src.get("url"):
                    found[src["url"]] = src.get("title", src["url"])
        if item.get("type") == "message":
            for content in item.get("content", []):
                for annotation in content.get("annotations", []):
                    if annotation.get("type") == "url_citation" and annotation.get("url"):
                        found[annotation["url"]] = annotation.get("title", annotation["url"])
    ids = []
    for url, title in found.items():
        try:
            clean = canonical_url(url)
        except ValueError:
            continue
        sid = "S_" + hashlib.sha256(clean.encode()).hexdigest()[:12]
        if sid not in sources:
            sources[sid] = Source(source_id=sid, url=clean, title=title, retrieved_at=now(),
                                  title_basis="search-result metadata; original document title not verified",
                                  search_context=result.get("text", "")[:20000])
        sources[sid].queries = list(dict.fromkeys([*sources[sid].queries, *queries]))
        ids.append(sid)
    return ids


def relevant_html_excerpt(text: str, max_chars: int, queries: list[str]) -> str:
    """Retain traceable, noncontiguous HTML *excerpts* for long public reports.

    Never pretend the entire source was inspected. Windows are copied directly
    from the page text; section markers make omitted portions explicit.
    """
    if len(text) <= max_chars:
        return text
    # Avoid returning only the first few thousand characters of a 20-F, where
    # the CapEx and reporting-line evidence often occurs much later.
    keywords = [
        "capital expenditures", "capital expenditure", "cash flow", "investment plan",
        "business overview", "organizational structure", "organisation structure",
        "board of directors", "management", "governance", "operating costs",
        "joint venture", "operations", "inspection", "implementation", "partner",
    ]
    query_terms = [w.casefold() for w in re.findall(r"[a-zA-Z]{5,}", " ".join(queries))
                   if w.casefold() not in {"report", "latest", "annual", "company", "site", "flytbase", "investor", "relations", "official"}]
    windows = []
    window_width = 1150
    for start in range(0, len(text), window_width):
        fragment = text[start:start + window_width]
        low = fragment.casefold()
        score = 5 * sum(min(low.count(term), 2) for term in keywords)
        score += sum(min(low.count(term), 2) for term in set(query_terms))
        # Long regulatory filings repeat business-risk boilerplate. A finance
        # passage needs the actual reported value and period, not just a heading.
        if any(q in " ".join(queries).casefold() for q in ("capital", "expenditures", "financial", "investment")):
            if re.search(r"(?:capital expenditures|capital expenditure|investment plan).{0,360}(?:US\$|USD|\$|million|billion|\d{3}[,.]\d)", low, re.S):
                score += 38
            if re.search(r"(?:\d{3}[,.]\d|US\$\s*\d|USD\s*\d)", fragment, re.I):
                score += 7
        if re.search(r"\b(?:20(?:2[0-9]|1[0-9]))\b", fragment):
            score += 2
        windows.append((score, start, fragment))
    # Preserve the page introduction for origin context; fill the remaining
    # bounded context with the highest-value, geographically dispersed spans.
    pieces = [(0, text[:min(650, max_chars // 10)])]
    remaining = max_chars - len(pieces[0][1]) - 100
    for score, start, fragment in sorted(windows, key=lambda w: (-w[0], w[1])):
        if remaining < 300:
            break
        if start < window_width or any(abs(start - existing) <= window_width for existing, _ in pieces):
            continue
        part = fragment[:min(window_width, remaining - 30)]
        if len(part) < 250:
            continue
        pieces.append((start, part))
        remaining -= len(part) + 24
    # Keep ranked relevant passages ahead of low-signal early-page boilerplate.
    # Original offsets are printed, so this is NOT misrepresented as contiguous
    # or full-document reading. Chronological source order would frequently
    # truncate the only CapEx passage at the final string slice.
    return "\n".join(f"[HTML excerpt at character {start + 1}; omitted text between excerpts]\n{part}"
                     for start, part in pieces)[:max_chars]


def fetch_source(source: Source, max_chars: int = 18000, client=None):
    """Reads all PDF pages when within limits; explicitly records truncation otherwise."""
    from .execution import require_live_execution
    require_live_execution(client)
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(18, connect=8), follow_redirects=False,
                                    headers={"User-Agent": "InboundResearchDemo/1.0 (public-source verification)"})
    try:
        url = source.url
        for _ in range(5):
            assert_public_url(url)
            with client.stream("GET", url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    from urllib.parse import urljoin
                    url = canonical_url(urljoin(url, response.headers["location"]))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                # Regulatory 20-F HTML filings can exceed 8 MB. Permit larger
                # public HTML documents within a strict, bounded memory limit,
                # while retaining the smaller PDF limit (partial PDFs cannot be parsed).
                is_html = "html" in content_type
                ceiling = 24_000_000 if is_html else 12_000_000
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > ceiling:
                        raise ValueError("Document exceeds the bounded HTTP inspection limit.")
                    chunks.append(chunk)
                blob = b"".join(chunks)
                break
        else:
            raise ValueError("Too many redirects.")
        if blob.startswith(b"%PDF") or "application/pdf" in content_type:
            source.inspection_method = "local pypdf extraction"
            source.pages_read, source.pages_retained = 0, []
            reader = PdfReader(BytesIO(blob))
            source.pages_total = len(reader.pages)
            pages = []
            # Inspect a bounded set of pages, retain those relevant to the actual research query.
            terms = ["capital expenditure", "capex", "opex", "investment", "technology", "shareholder",
                     "investor", "priorities", "operations", "organisation", "governance", "leadership"]
            terms += [w for w in re.findall(r"[a-zA-Z]{5,}", " ".join(source.queries).lower())
                      if w not in {"official", "latest", "report", "annual", "company", "https"}]
            for i, page in enumerate(reader.pages):
                if i >= 220:
                    break
                text = page.extract_text() or ""
                score = sum(min(text.casefold().count(t), 5) for t in set(terms))
                pages.append((i + 1, text, score))
                source.pages_read += 1
            ranked = sorted(pages, key=lambda p: (-p[2], p[0]))
            selected, remaining = [], max_chars
            # Keep the first page's opening metadata, but reserve most of the
            # budget for pages mentioning the actual query terms (e.g. capex).
            cover = next((text for number, text, _ in pages if number == 1), "")
            if cover.strip():
                excerpt = f"[PDF page 1 — introduction]\n{cover[:min(850, max_chars // 6)]}"
                selected.append((1, excerpt))
                remaining -= len(excerpt) + 1
            for number, page_text, score in ranked:
                if remaining < 100 or not page_text.strip() or number == 1:
                    continue
                portion = f"[PDF page {number}]\n{page_text}"[:min(remaining, 2500)]
                selected.append((number, portion))
                remaining -= len(portion) + 1
            selected.sort()
            source.pages_retained = [n for n, _ in selected]
            source.text = "\n".join(t for _, t in selected)[:max_chars]
            source.truncated = (len(source.pages_retained) < source.pages_total
                                or source.pages_read < source.pages_total
                                or sum(len(t) for _, t, _ in pages) > max_chars)
            source.access = "inspected_pdf"
        elif "html" in content_type or blob.lstrip().startswith((b"<!", b"<html")):
            source.inspection_method = "direct HTTP and HTML text extraction"
            soup = BeautifulSoup(blob, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            source.title = title or source.title
            if title:
                source.title_basis = "original HTML title metadata; publisher asserted"
            for key in ["article:published_time", "datePublished", "date", "pubdate"]:
                tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
                if tag and tag.get("content"):
                    source.publication_date = tag["content"]
                    source.publication_date_basis = f"page metadata: {key}; publisher asserted"
                    break
            if not source.publication_date:
                for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
                    match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', tag.get_text())
                    if match:
                        source.publication_date = match.group(1)
                        source.publication_date_basis = "page JSON-LD datePublished; publisher asserted"
                        break
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()
            for tag in soup.select('[role="navigation"], [aria-hidden="true"]'):
                tag.decompose()
            # Customer menus frequently advertise other customer stories.
            # They are not evidence about the current article's customer.
            main = soup.find("main") or soup.find("article") or soup
            text = main.get_text(" ", strip=True)
            source.truncated = len(text) > max_chars
            source.text = relevant_html_excerpt(text, max_chars, source.queries)
            if source.truncated:
                source.inspection_method = "direct HTTP; query-relevant HTML excerpts only (not the whole page)"
            source.access = "inspected_page"
        else:
            raise ValueError("Unsupported content type.")
        source.publication_date = publication_iso(source.publication_date)
        if len(source.text.strip()) < 120:
            raise ValueError("Insufficient readable text; scanned/JavaScript-only content may need manual review.")
        source.retrieved_at = now()
        source.error = ""
    except Exception as exc:
        # Never save arbitrary exception messages, headers or query-bearing diagnostic URLs.
        source.access = "search_summary_only" if source.search_context else "inaccessible"
        source.text = ""
        source.error = f"Page inspection unavailable ({type(exc).__name__}); no claim of reading the original document."
    finally:
        if own_client:
            client.close()


def evidence_payload(sources: dict[str, Source], ids: list[str] | None = None) -> dict:
    selected = ids if ids is not None else list(sources)
    return {sid: sources[sid].model_dump() for sid in selected if sid in sources}
