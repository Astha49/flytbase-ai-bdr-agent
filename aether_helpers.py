"""UI-only rendering helpers. No providers or writes to source runs."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any


def obj(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def arr(x: Any) -> list:
    return x if isinstance(x, list) else []


def text_value(x: Any) -> str:
    if isinstance(x, dict):
        for k in ('text', 'value', 'description', 'title'):
            if x.get(k):
                return text_value(x[k])
        return ''
    if isinstance(x, list):
        return '; '.join(filter(None, (text_value(y) for y in x)))
    return str(x or '')


MATCH_LABELS = {
    'industry': 'Mining industry',
    'use_case': 'Inspection use case',
    'operating_context': 'Operational conditions',
    'geography': 'Geographic relevance',
    'referral': 'Anglo American referral',
    'same_company': 'Existing company relationship',
}


def case_summary(raw: Any) -> dict:
    """Turn a complex case-study decision into a short human-facing view.

    Distinguishes AI relevance scoring from evidence approval; no new assertions.
    """
    if isinstance(raw, str):
        # Older records may serialize the decision as text. Parse only JSON-shaped
        # objects; plain human notes remain plain and are never used as a score.
        try:
            import json
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {'title': raw}
    root = obj(raw)
    cand = obj(root.get('candidate')) or root
    if not root:
        return {}
    dims = [MATCH_LABELS.get(str(d.get('dimension')), str(d.get('dimension', '')).replace('_',' ').title())
            for d in arr(cand.get('dimensions')) if isinstance(d, dict) and d.get('matched') is True]
    relevance = text_value(cand.get('relevance'))
    reasons = [text_value(v) for v in arr(root.get('rejection_reasons'))]
    reasons = [v for v in reasons if v]
    return {
        'title': str(cand.get('title') or root.get('title') or 'Case study candidate').split(' | ')[0].strip(),
        'source_id': str(cand.get('source_id') or root.get('source_id') or ''),
        'score': root.get('score'),
        'eligible': root.get('eligible') is True,
        'dimensions': dims,
        'relevance': relevance,
        'status': text_value(root.get('status')), 
        'reasons': reasons,
        'limitations': [text_value(x) for x in arr(cand.get('limitations')) if text_value(x)],
        'selection_note': text_value(root.get('selection_note')),
    }


# Alert classifications translate machine findings into useful human decisions.
# The original warning strings remain preserved in the saved run and optional audit details.
GROUPS = [
    ('access', 'Some source pages could not be opened',
     'The system could not verify the complete original document.',
     'Review the public source link before citing the affected claim.',
     ('httpstatuserror', 'page inspection unavailable', 'unavailable (http', 'failed to fetch', 'failed to access')),
    ('issuer', 'Some retrieved documents were unrelated',
     'Search results from unrelated companies or duplicated filings were excluded.',
     'Use the remaining verified sources for decisions.',
     ('unrelated filing', 'unrelated issuer', 'unrelated-issuer', 'unrelated sec issuers', 'wrong issuer', 'duplicate or unrelated')),
    ('partial_docs', 'Some source documents were only partly reviewed',
     'The available excerpts did not cover every page of the original document.',
     'Check the full document for consequential claims.',
     ('truncation', 'inspected only in part', 'page counts', 'incomplete source')),
    ('scope', 'The published deployment may be different from this enquiry',
     'Evidence of a company-level FlytBase relationship does not confirm deployment at the proposed sites.',
     'Ask the buyer which division and sites are already using the platform.',
     ('leaching piles', 'lithium extraction', 'existing', 'division', 'scope is unclear', 'cannot verify the requested sites')),
    ('partner', 'Partner availability or ownership is not confirmed',
     'Public material does not establish who is available to deliver this particular project.',
     'Confirm implementation capacity and commercial ownership before routing.',
     ('partner availability', 'partner capacity', 'willingness to engage', 'current availability', 'implementation role', 'commercial_owner', 'commercial owner', 'partner is not verified', 'extent of adentu', 'coverage across')),
    ('financial', 'Financial or procurement details need confirmation',
     'The evidence is insufficient to assert a budget amount, decision-maker, or fiscal timeline.',
     'Use discovery questions to verify the missing buying-process facts.',
     ('currency', 'capex', 'opex', 'financial figure', 'budget discussion', 'budget or spending', 'budget size', 'drone-inspection budget', 'fiscal scope', 'procurement', 'publication_date', 'publication date', 'decision-making authority', 'target implementation date')),
    ('role_unknown', 'The buyer’s internal reporting structure is unconfirmed',
     'Public records do not establish the requested contact’s internal reporting line or purchasing authority.',
     'Ask the contact who owns the initiative and approves the purchase.',
     ('reporting chain', 'reporting line', 'northern operations division', 'rodrigo castillo')),
    ('outreach_review', 'Email claims require review before sending',
     'Some earlier draft statements could not be substantiated and were withheld or rewritten.',
     'Use the reviewed drafts in Outreach studio and verify claims before sending.',
     ('draft', 'no safe email body', 'subject withheld', 'withheld from', 'email body', 'review before using drafts')),
    ('case_review', 'Case-study match needs further verification',
     'The material is potentially useful, but it did not pass every evidence check.',
     'Review the published study and confirm it applies to the proposed sites.',
     ('primary case study', 'case study', 'candidates.', 'ai_case_comparison')),
    ('evidence', 'Some statements did not pass evidence review',
     'A claim or comparison lacked supporting source material and was held for human review.',
     'Check the cited passages before using the claim in outreach.',
     ('groundedness', 'not supported', 'unsupported', 'not substantiate', 'lacks source', 'source evidence', 'grounded', 'evidence insufficient', 'audit failed', 'source is missing')),
    ('handoff_review', 'The handoff includes unresolved qualification gaps',
     'The Account Executive has useful context, but upstream uncertainty remains.',
     'Review the buyer’s unanswered discovery questions before advancing the deal.',
     ('upstream uncertainties', 'review limitations before taking action')),
    ('freshness', 'This review reused previously collected research',
     'The system worked from saved sources rather than retrieving everything again.',
     'Refresh the research before making time-sensitive claims.',
     ('cached', 'no fresh retrieval', 'not refreshed', 'old research')),
]


def group_warnings(warnings: list) -> list[dict]:
    grouped: OrderedDict[str, dict] = OrderedDict()
    for warning in warnings:
        raw = text_value(warning).strip()
        if not raw:
            continue
        lower = raw.casefold()
        matched = next(((key, head, detail, next_action) for key, head, detail, next_action, terms in GROUPS
                        if any(t in lower for t in terms)), None)
        if matched is None:
            matched = ('other', 'Other findings need human review',
                       'The saved workflow flagged an issue that needs context.',
                       'Read the original technical note to understand the affected claim.')
        key, head, detail, next_action = matched
        if key not in grouped:
            grouped[key] = {'key': key, 'title': head, 'meaning': detail,
                            'next_action': next_action, 'count': 0, 'original': []}
        grouped[key]['count'] += 1
        grouped[key]['original'].append(raw)
    # meaningful clusters on top, with other items last
    return sorted(grouped.values(), key=lambda group: (group['key'] == 'other', -group['count']))


# Streamlit reruns the presentation script on every navigation action.  Keep
# parsing of multi-megabyte saved executions in this imported module's cache.
# File stat values are part of the key, so checkpoint changes are visible.
from functools import lru_cache
import json as _json
from pathlib import Path as _Path

@lru_cache(maxsize=24)
def cached_saved_run(file_path: str, modified_ns: int, size: int) -> dict:
    """Read a saved execution once per file version, without changing it."""
    result = _json.loads(_Path(file_path).read_text(encoding='utf-8'))
    if not isinstance(result, dict) or not isinstance(result.get('stages'), list):
        raise ValueError('Not a FlytBase run JSON')
    return result
