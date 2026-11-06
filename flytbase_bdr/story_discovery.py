"""Optional official customer-story index discovery; no hard-coded winners.

Used only under an approved live execution if ordinary search has not found any
inspected FlytBase case-study page. This makes zero Groq/Tavily API requests,
but does require one ordinary public HTTP page fetch. Every proposed story must
still be individually inspected and evidence-gated before selection.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .evidence import is_flytbase, canonical_url
from .execution import require_live_execution


INDEX = "https://flytbase.com/case-studies"


def missing_story_connections(sources, lead: dict) -> bool:
    """An unrelated inspected story must not suppress prospect/referral lookup."""
    from .diagnostics import _brand
    stories = [s for s in sources.values() if is_flytbase(s.url) and "/case-studies/" in s.url
               and s.access in {"inspected_page", "inspected_pdf"} and s.text]
    if not stories:
        return True
    names = [name for name in (_brand(lead.get("company", "")), lead.get("referral", "")) if len(name.strip()) >= 3]
    return any(not any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", s.title + " " + s.url, re.I)
                       for s in stories) for name in names)


def story_links_from_html(html: str, lead: dict, limit: int = 3) -> list[dict]:
    """Rank current HTML story links against the buyer's actual enquiry.

    Company, referral, industry, and need are derived from the lead. A story
    link is a retrieval candidate only, never a verified case study claim.
    """
    soup = BeautifulSoup(html[:2_000_000], "html.parser")
    name = lead.get("company", "")
    acronym = re.search(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", name)
    brand = acronym.group(1).lower() if acronym else name.casefold().split(" ")[0]
    referral = str(lead.get("referral", "")).casefold().strip()
    industry = str(lead.get("industry", "")).casefold().strip()
    need = str(lead.get("need", "")).casefold()
    keywords = {w for w in re.findall(r"[a-z]{5,}", industry + " " + need)
                if w not in {"based", "across", "looking", "large", "scale", "sites", "their"}}
    ranked = {}
    for a in soup.select("a[href]"):
        try:
            url = canonical_url(urljoin(INDEX, a["href"]))
        except (ValueError, TypeError):
            continue
        if not is_flytbase(url) or "/case-studies/" not in urlsplit(url).path:
            continue
        # Link text, not an AI guess, provides the discoverable candidate title.
        title = " ".join(a.get_text(" ", strip=True).split())[:240]
        # Some live directories place "Read story" inside the link while the
        # actual story heading is a sibling in the same card. Discover the
        # published title from nearby HTML rather than discarding that link.
        if len(title) < 15 or title.casefold() in {"read", "read story", "read the story", "view case study"}:
            node = a.parent
            for _ in range(3):
                if node is None:
                    break
                heading = node.find(["h2", "h3", "h4", "h5"])
                if heading:
                    candidate_title = " ".join(heading.get_text(" ", strip=True).split())[:240]
                    if len(candidate_title) >= 12:
                        title = candidate_title
                        break
                node = node.parent
        if not title:
            continue
        lower = title.casefold()
        score = (20 if len(brand) >= 3 and brand in lower else 0)
        score += 16 if referral and len(referral) >= 3 and referral in lower else 0
        score += 4 if industry and industry in lower else 0
        score += sum(1 for keyword in keywords if keyword in lower)
        # Discard unrelated stories; don't turn a crowded directory into invented relevance.
        if score == 0:
            continue
        previous = ranked.get(url)
        if not previous or previous[0] < score:
            ranked[url] = (score, title)
    return [{"url": url, "title": title, "content": "Official case-study directory link; original story must be inspected."}
            for url, (score, title) in sorted(ranked.items(), key=lambda item: (-item[1][0], item[0]))[:limit]]


def discover_official_stories(lead: dict, *, client=None) -> list[dict]:
    """Read ONLY the first-party story index, with redirects confined to FlytBase."""
    require_live_execution(client)
    own_client = client is None
    client = client or httpx.Client(timeout=12, follow_redirects=False,
                                   headers={"User-Agent": "InboundResearchDemo/1.0"})
    try:
        url = INDEX
        for _ in range(3):
            if not is_flytbase(url):
                return []
            response = client.get(url)
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            if response.status_code != 200 or len(response.content) > 2_000_000:
                return []
            return story_links_from_html(response.text, lead)
        return []
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if own_client:
            client.close()
