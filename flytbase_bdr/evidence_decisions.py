"""Safe source-derived decisions when a large Groq schema is rejected.

No customer, case-study URL, winner or partner is preconfigured here. Each
candidate comes from the current run's inspected FlytBase evidence registry.
A deterministic fallback is *not* presented as an AI semantic audit.
"""
import re
from .evidence import is_flytbase, source_family_key
from .models import Claim, EvidenceRef, Material, Materials, MatchDimension, Partner, Routing
from .diagnostics import _brand


def article_prose(text: str) -> str:
    """Exclude the related-stories/navigation footer from evidence matching.

    A link to SQM below an Anglo American article does NOT establish an
    SQM deployment by Anglo American, and vice versa.
    """
    body = re.split(r"(?i)\b(?:related customer stories|related case studies|more customer stories|you may also like)\b", text, maxsplit=1)[0]
    # First-party case pages put promotional headings and animated metric
    # counters before their narrative. Prefer the actual summary when present.
    summary = re.search(r"\bTL;DR\b", body, re.I)
    return body[summary.end():].lstrip() if summary else body


def quote_near(text: str, pattern: str, width: int = 260) -> str:
    """Return exact contiguous source bytes, not a fabricated paraphrase."""
    match = re.search(pattern, text, re.I)
    if not match:
        return ""
    start = max(0, match.start() - 65)
    end = min(len(text), max(match.end() + 80, start + width))
    return text[start:end].strip()


def operating_context_quote(text: str) -> str:
    """Continuous inspection needs operational evidence, not telemetry or a plan."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if (re.search(r"24/7|round.the.clock|continuous(?:ly)?\s+(?:operation|monitor|inspect)", sentence, re.I)
                and re.search(r"inspect|monitor|operat|surveill", sentence, re.I)
                and not re.search(r"\bplan\w*|\bfuture\b|\bwill\b|\bintend\w*|\bexpect\w*|flight.status|telemetry", sentence, re.I)
                and len(sentence.strip()) <= 650):
            return sentence.strip()
    return ""


def claim(text: str, sid: str = "", quote: str = "", *, kind="inference") -> Claim:
    return Claim(text=text, kind=kind,
                 evidence=[EvidenceRef(source_id=sid, quote=quote)] if sid and quote else [],
                 input_quote="", uncertainty=("Comparison only; the proposed sites still need discovery."
                                               if kind == "inference" else "Not established from inspected evidence."),
                 financial_context=None, event_date="")


def material_proposals(run, ids: list[str]) -> Materials:
    """Create independently inspectable proposal inputs; selection.py scores.

    This is a fallback, not a promise that a case study exists. A customer
    testimonial in a blog is never called an inspected case study.
    """
    lead = run.stages[0].output["lead"]
    brand, referral, country = _brand(lead.get("company", "")), lead.get("referral", ""), lead.get("geography", "")
    industry = lead.get("industry", "").casefold()
    wants_inspection = bool(re.search(r"inspect|survey|monitor", lead.get("need", ""), re.I))
    options = []
    for sid in dict.fromkeys(ids):
        source = run.sources.get(sid)
        if not source or not source.text or not is_flytbase(source.url) or source.access not in {"inspected_page", "inspected_pdf"}:
            continue
        # The assignment explicitly requires a case study. Do not silently
        # promote a blog post or webinar into a customer case-study winner.
        if "/case-studies/" not in source.url:
            continue
        body = article_prose(source.text)
        industry_pattern = r"\bmin(?:e|es|ing)\b|\blithium\b|\biodine\b|\bcopper\b" if "min" in industry else re.escape(industry)
        industry_quote = quote_near(body, industry_pattern) if industry else ""
        inspection_quote = quote_near(body, r"\binspect\w*|\bsurvey\w*|\bmonitor\w*|\bthermal\w*") if wants_inspection else ""
        if not industry_quote or not inspection_quote:
            continue
        same_quote = quote_near(body, rf"(?<!\w){re.escape(brand)}(?!\w)") if len(brand) >= 3 else ""
        referral_quote = quote_near(body, rf"(?<!\w){re.escape(referral)}(?!\w)") if len(referral) >= 3 else ""
        geo_quote = quote_near(body, rf"(?<!\w){re.escape(country)}(?!\w)") if len(country) >= 3 else ""
        cont_quote = operating_context_quote(body)
        features = {
            "industry": industry_quote,
            "use_case": inspection_quote,
            "operating_context": cont_quote if "24/7" in run.input else "",
            "geography": geo_quote,
            "referral": referral_quote,
            "same_company": same_quote,
        }
        dimensions = [MatchDimension(dimension=k, matched=bool(v), rationale=claim(
            f"The inspected article mentions {k.replace('_', ' ')} relevant to the enquiry." if v
            else f"A {k.replace('_', ' ')} match was not established from this article.",
            sid if v else "", v, kind="inference" if v else "unknown")) for k, v in features.items()]
        cited = same_quote or referral_quote or inspection_quote
        if not cited:
            continue
        limits = ["One publication is not proof of performance or feasibility at the buyer's proposed sites."]
        if "/case-studies/" not in source.url:
            limits.append("This FlytBase publication is a webinar/blog, not a verified case-study page.")
        if same_quote:
            limits.append("Possible existing company relationship does not prove the proposed division or sites are covered.")
        candidate = Material(title=source.title, source_id=sid, dimensions=dimensions,
                             relevance=claim("This inspected FlytBase material concerns a related industrial drone use; transfer needs discovery.", sid, cited),
                             limitations=limits,
                             own_company_expansion_assessment=("Investigate whether the enquiry concerns different operations/sites."
                                                               if same_quote else "This is a peer example, not proof of deployment at the buyer."))
        score = (60 if "/case-studies/" in source.url else 0) + (30 if same_quote else 0) + (20 if referral_quote else 0)
        options.append((score, candidate))
    options.sort(key=lambda pair: pair[0], reverse=True)
    selected, families = [], set()
    for _, item in options:
        family = source_family_key(run.sources[item.source_id].url)
        if family not in families:
            selected.append(item)
            families.add(family)
        if len(selected) == 2:
            break
    return Materials(candidates=selected, referral_findings=[],
                     gaps=[] if selected else ["No inspected FlytBase industrial-inspection material found; refresh discovery."])


def route_proposal(run, ids: list[str]) -> Routing:
    """Cautious AE ownership with optional *documented* local implementation evidence.

    A customer-case collaborator and an official ecosystem partner are not
    automatically assumed available or contractually assigned to this deal.
    """
    lead = run.stages[0].output["lead"]
    country = lead.get("geography", "").strip()
    candidates = []
    if country:
        # Extract candidate names from *patterns* in official source text;
        # no particular vendor or country is hardcoded.
        # A prospect's existing integrator can be described in multiple
        # grammatical forms in first-party customer stories. Discover the name
        # from each actual inspected page, never from a configured brand list.
        country_form = re.escape(country) + r"(?:an|ian)?"
        proper = r"([A-Z][A-Za-z0-9&-]{2,36}(?:\s+[A-Z][A-Za-z0-9&-]{2,36}){0,2})"
        patterns = [
            rf"\b{proper},?\s+(?i:a|an)\s+{country_form}[- ]based\s+(?i:(?:(?:drone|systems?)\s+)?integrator)",
            rf"\b{proper},?\s+(?i:a|an)\s+{country_form}\s+(?i:(?:(?:drone|systems?)\s+)?integrator)",
            rf"\b{proper}\s+(?:Gold\s+)?System Integrator\s+Solution Provider\s+{re.escape(country)}\b",
        ]
        for sid in ids:
            source = run.sources.get(sid)
            if not source or source.access not in {"inspected_page", "inspected_pdf"} or not is_flytbase(source.url):
                continue
            body = article_prose(source.text)
            for pattern in patterns:
                match = re.search(pattern, body)
                if not match:
                    continue
                name = match.group(1).strip()
                if name.casefold() in {"flytbase", "company", "partner", "customer", "the company"}:
                    continue
                quote = match.group(0)
                refs = [EvidenceRef(source_id=sid, quote=quote)]
                proof = Claim(text=f"The source identifies {quote}.",
                              kind="public", evidence=refs, input_quote="", uncertainty="",
                              financial_context=None, event_date="")
                activity_quote = next((sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n", body)
                                       if len(sentence.strip()) <= 650
                                       and re.search(rf"(?<!\w){re.escape(name)}\b", sentence, re.I)
                                       and re.search(r"\b(?:built|installed|implemented|deployed|integrated|speciali[sz]\w*)\b", sentence, re.I)), "")
                country_quote = next((sentence for sentence in re.split(r"(?<=[.!?])\s+|\n", body)
                                      if re.search(rf"\b{re.escape(name)}\b", sentence, re.I)
                                      and re.search(rf"\b{re.escape(country)}\b", sentence, re.I)
                                      and re.search(r"operat|deploy|install|implement|servic", sentence, re.I)), "")
                coverage = (Claim(text=f"This publication documents {name} participating in an operation in {country}; territorial coverage and current capacity remain unverified.",
                                  kind="public", evidence=[EvidenceRef(source_id=sid, quote=country_quote)], input_quote="", uncertainty="",
                                  financial_context=None, event_date="") if country_quote else proof)
                candidates.append(Partner(name=name, partner_type="Industrial drone systems integrator",
                                          ecosystem_evidence=proof,
                                          capabilities=[Claim(text=(activity_quote if activity_quote
                                                                    else f"The inspected source identifies {name} as an integrator."),
                                                              kind="public", evidence=[EvidenceRef(source_id=sid, quote=activity_quote)] if activity_quote else refs, input_quote="",
                                                              uncertainty="", financial_context=None, event_date="")],
                                          geographic_coverage=coverage,
                                          availability="Not verified: confirm present capacity and willingness.",
                                          limitations=["Public participation/country presence does not establish current availability or assignment."]))
                break
            if candidates:
                break
    return Routing(recommended_motion="direct_ae", rationale=[claim(
        "Direct AE ownership is appropriate for complex enterprise discovery; verify installation support locally.")],
        candidates=candidates, proposed_partner_name="", required_partner_type="Local industrial drone systems integrator",
        commercial_owner="FlytBase Account Executive", implementation_owner="FlytBase AE to confirm local support",
        next_action="Schedule buyer discovery; confirm existing deployments, funding, site requirements and partner capacity.",
        gaps=["Current partner availability and procurement scope must be confirmed."])
