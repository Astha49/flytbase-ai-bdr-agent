"""Pure presentation helpers for the local Streamlit workbench.

No network calls, no model calls, no mutation of workflow records. Strings from
buyers, provider output, or retrieved pages are HTML-escaped before insertion.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st


def e(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def inject_styles(root: Path) -> None:
    css = (root / "assets" / "theme.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def paint(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def pill(status: str) -> str:
    status_clean = str(status).lower().strip()
    kind = "ok" if status_clean in ("complete", "confirmed", "succeeded", "verified") else (
        "error" if status_clean in ("failed", "error", "rejected") else (
            "partial" if status_clean in ("partial", "unknown", "ambiguous", "running") else "neutral"
        )
    )
    prefix = "● " if kind == "ok" else ("◐ " if kind == "partial" else "◆ ")
    friendly = {"complete": "Completed", "partial": "Review Needed", "failed": "Failed", "pending": "Queued",
                "unknown": "Not confirmed", "ambiguous": "Date unclear", "confirmed": "Confirmed",
                "running": "Working", "neutral": "Review"}.get(status_clean, status_clean.capitalize())
    return f'<span class="fb-pill {kind}">{prefix}{e(friendly)}</span>' 


def section(kicker: str, title: str, helper: str = "") -> None:
    paint(f'<div class="fb-section"><div><div class="fb-eyebrow">{e(kicker)}</div>'
          f'<h2>{e(title)}</h2></div><small>{e(helper)}</small></div>')


def hero(read_only: bool = True) -> None:
    """Industrial flight-console visual built in CSS/SVG; illustration is not telemetry."""
    state = "PREVIEW MODE / NO API CALLS" if read_only else "LIVE MODE / EXPLICIT APPROVAL REQUIRED"
    paint(f'''<div class="fb-hero fb-hero-v2">
      <div class="fb-hero-copy">
        <div class="fb-hero-overline"><span class="fb-orbit-icon">✦</span> FLYTBASE / INBOUND INTELLIGENCE
          <span class="fb-hero-indicator">{e(state)}</span></div>
        <div class="fb-hero-title">From first contact<br>to <em>clear next move.</em></div>
        <p class="fb-hero-desc">One customer enquiry. Six connected decisions. Real company research, relevant proof, and a confident sales handoff — with the uncertainty left visible.</p>
        <div class="fb-hero-meta"><span class="fb-hero-tag"><b>06</b> connected steps</span>
        <span class="fb-hero-tag"><b>↗</b> evidence before claims</span>
        <span class="fb-hero-tag"><b>●</b> zero emails sent</span></div>
      </div>
      <div class="fb-radar-scene" aria-label="Decorative six-step workflow illustration; not real flight telemetry" role="img">
        <div class="fb-radar-grid"></div>
        <div class="fb-radar-ring ring-a"></div><div class="fb-radar-ring ring-b"></div><div class="fb-radar-ring ring-c"></div>
        <div class="fb-radar-scan"></div>
        <span class="fb-radar-point point-a"><i></i><small>01 · QUALIFY</small></span>
        <span class="fb-radar-point point-b"><i></i><small>02 · VERIFY</small></span>
        <span class="fb-radar-point point-c"><i></i><small>03 · HANDOFF</small></span>
        <div class="fb-radar-drone"><svg viewBox="0 0 120 120" role="presentation" aria-hidden="true">
          <path d="M60 24L75 45L95 38L107 51L95 64L76 60L60 93L44 60L25 64L13 51L25 38L45 45Z" fill="#a3eff0" opacity=".95"/>
          <path d="M60 34L67 51L88 46L96 51L88 56L69 56L60 79L51 56L32 56L24 51L32 46L53 51Z" fill="#1d3e57"/>
          <circle cx="60" cy="54" r="8" fill="#fff"/><circle cx="60" cy="54" r="3" fill="#2a77ad"/>
          <path d="M22 28L36 28M84 28L98 28M22 83L36 83M84 83L98 83" stroke="#9ce4ff" stroke-width="2" stroke-linecap="round"/>
        </svg></div>
        <div class="fb-radar-bottom"><span class="fb-signal-wave">▂ ▄ ▆ █</span><span>SIX-STAGE SIGNAL PATH</span><b>→</b></div>
        <div class="fb-radar-disclaimer">VISUAL CONCEPT · NOT LIVE TELEMETRY</div>
      </div>
    </div>''')



def evidence_experience() -> None:
    """Decorative, accessible explanation of the workflow (not live telemetry)."""
    paint("""<section class="fb-evidence-experience" aria-label="Evidence pipeline concept">
      <div class="fb-evidence-head">
        <span class="fb-visual-kicker">THE EVIDENCE PATH <span aria-hidden="true">✦</span></span>
        <h3>Research first. <em>Decisions second.</em></h3>
        <p>Three checks connect raw web findings to a commercially useful next move. Nothing is treated as verified just because a search returned it.</p>
      </div>
      <div class="fb-evidence-map" aria-label="Concept path: retrieve sources, inspect claims, recommend a sales action">
        <div class="fb-path-link" aria-hidden="true"></div>
        <div class="fb-path-node"><span>01 / DISCOVER</span><b>Find the source</b><small>Official filings · case studies</small></div>
        <div class="fb-path-node"><span>02 / VALIDATE</span><b>Check the claim</b><small>Scope · date · relevance</small></div>
        <div class="fb-path-node"><span>03 / RECOMMEND</span><b>Explain the move</b><small>Buyer question · AE handoff</small></div>
      </div>
      <div class="fb-evidence-bottom"><span class="fb-evidence-led" aria-hidden="true"></span> INSPECTABLE LOGIC <span>HUMAN REVIEW BEFORE OUTREACH</span></div>
    </section>""")


def operator_experience(read_only: bool = True) -> None:
    """Complementary operations visual, deliberately separate from execution controls."""
    state = "READ-ONLY / NO REQUESTS" if read_only else "LIVE CAPABLE / APPROVAL REQUIRED"
    paint(f"""<section class="fb-access-experience" aria-label="Operator access overview">
      <div class="fb-access-copy">
        <span class="fb-visual-kicker"><span class="fb-access-light" aria-hidden="true"></span> OPERATOR CONTROL ROOM</span>
        <div class="fb-access-status">{e(state)}</div>
        <h2>Run with intent.<br><em>Keep every receipt.</em></h2>
        <p>Inspect saved work for free, or explicitly approve a protected live run. Each analysis leaves an auditable trail without silently using your demo reserve.</p>
        <div class="fb-access-tags"><span>◎ REPLAY</span><span>◇ APPROVAL</span><span>↗ TRACEABILITY</span></div>
      </div>
      <div class="fb-access-console" role="img" aria-label="Decorative control-room signal visualization; not a live indicator or account usage meter">
        <div class="fb-console-grid"></div><div class="fb-console-ring c1"></div><div class="fb-console-ring c2"></div>
        <div class="fb-console-sweep"></div>
        <div class="fb-console-core"><span>✧</span><b>DECISION<br>ENGINE</b></div>
        <div class="fb-console-node n1"><i></i> INBOUND</div>
        <div class="fb-console-node n2"><i></i> SOURCE CHECK</div>
        <div class="fb-console-node n3"><i></i> HANDOFF</div>
        <div class="fb-console-bottom">EXPLICIT ACTIONS ONLY <span aria-hidden="true">▂ ▄ ▆ █</span></div>
      </div>
    </section>""")

def narrative_masthead(view: str) -> None:
    """Page-specific visual story; all copy is descriptive, not a claim about a run.

    Decorative paths and numbers describe system architecture only. The source
    backed findings that follow remain the authoritative result.
    """
    scenes = {
        "research": {
            "tone": "mint", "number": "01", "overline": "ACCOUNT INTELLIGENCE / SOURCE FIRST",
            "headline": "Find the signal.<br><em>Challenge the assumption.</em>",
            "description": "Research that goes beyond the company overview. Explore each source, the operational implication, and what still needs a buyer's answer.",
            "tracks": (("01", "Company structure"), ("02", "Financial signals"),
                       ("03", "Strategic priorities")),
            "label": "EVIDENCE / CONTEXT / COMMERCIAL MEANING",
        },
        "strategy": {
            "tone": "lilac", "number": "02", "overline": "SALES STRATEGY / FROM RESEARCH TO ACTION",
            "headline": "The right message.<br><em>The right next move.</em>",
            "description": "Compare conditional emails, customer proof and partner routes in one place. Every recommendation should explain the evidence behind it.",
            "tracks": (("01", "Buyer outreach"), ("02", "Customer proof"),
                       ("03", "Partner route")),
            "label": "PERSONALIZE / VALIDATE / ROUTE",
        },
        "handoff": {
            "tone": "peach", "number": "03", "overline": "ACCOUNT EXECUTIVE / DISCOVERY BRIEF",
            "headline": "Less noise.<br><em>More momentum.</em>",
            "description": "A concise brief the account executive can actually use: the buyer's context, unresolved questions and the next commercially sensible action.",
            "tracks": (("01", "Buyer context"), ("02", "Three insights"),
                       ("03", "Next action")),
            "label": "PREPARE / DISCOVER / HAND OFF",
        },
    }
    scene = scenes[view]
    rows = "".join(
        f'<div class="fb-mast-row"><span>{e(number)}</span><b>{e(label)}</b>'
        f'<i aria-hidden="true">↗</i></div>'
        for number, label in scene["tracks"]
    )
    paint(f'''<section class="fb-mast fb-mast-{scene["tone"]}" aria-label="{e(view)} page introduction">
      <div class="fb-mast-copy">
        <div class="fb-mast-kicker"><span class="fb-mast-dot" aria-hidden="true"></span>{e(scene["overline"])}</div>
        <h1>{scene["headline"]}</h1><p>{e(scene["description"])}</p>
        <div class="fb-mast-caption">{e(scene["label"])}</div>
      </div>
      <div class="fb-mast-art" aria-label="Decorative abstract route diagram" role="img">
        <div class="fb-mast-orbit orbit-one"></div><div class="fb-mast-orbit orbit-two"></div>
        <div class="fb-mast-card">
           <div class="fb-mast-card-heading"><span>WORKFLOW / {scene["number"]}</span><span class="fb-mast-cross">✳</span></div>
           {rows}
           <div class="fb-mast-card-foot"><span class="fb-mast-foot-light" aria-hidden="true"></span> TRACEABLE DECISIONS <b>↗</b></div>
        </div>
      </div>
    </section>''')


def story_ribbon() -> None:
    """Lightweight chapter markers, intentionally not invented progress metrics."""
    paint('''<div class="fb-story-ribbon" aria-label="How the sales intelligence workflow is organized">
      <div class="fb-story-item"><div class="fb-story-icon fb-story-mint" aria-hidden="true">⌁</div>
        <div><span>01 / UNDERSTAND</span><b>Start with the buyer</b><small>Extract context before guessing intent.</small></div></div>
      <div class="fb-story-item"><div class="fb-story-icon fb-story-blue" aria-hidden="true">◎</div>
        <div><span>02 / VERIFY</span><b>Follow the evidence</b><small>Inspect original sources and limitations.</small></div></div>
      <div class="fb-story-item"><div class="fb-story-icon fb-story-peach" aria-hidden="true">↗</div>
        <div><span>03 / ACT</span><b>Choose the next move</b><small>Deliver a usable AE handoff.</small></div></div>
    </div>''')


def workflow_track(stages) -> None:
    """Read-only visualization: stage completion is not acceptance verification."""
    names = ["Qualify", "Research", "Respond", "Match proof", "Partner route", "Sales handoff"]
    parts = []
    for index, stage in enumerate(stages[:6]):
        complete = stage.status == "complete"
        progress = {"complete": "ready", "partial": "needs-review", "failed": "failed",
                    "running": "working", "pending": "queued", "skipped": "queued"}.get(stage.status, "needs-review")
        label = {"complete": "Completed", "partial": "Review Needed", "failed": "Failed",
                 "running": "Working", "pending": "Queued", "skipped": "Skipped"}.get(stage.status, stage.status)
        parts.append(f'<div class="fb-flight-step {progress}" title="{e(label)}">'
                     f'<span class="fb-flight-index">0{index+1}</span>'
                     f'<strong>{e(names[index])}</strong>'
                     f'<small class="fb-flight-state">{e(label)}</small>'
                     f'<span class="fb-flight-dot" aria-label="{e(stage.status)}"></span></div>')
    paint('<div class="fb-flight-track" aria-label="Workflow status from the saved record">'
          + "".join(parts) + '</div><p class="fb-flight-caption">A green stage has a saved output; only the evidence checks establish submission readiness.</p>')


def next_steps_board(checks) -> None:
    """Two-line decision overview with explicit unresolved requirements."""
    snippets = []
    for item in checks:
        ready = item["state"] == "ready"
        label = "Ready to review" if ready else "Still needs work"
        snippets.append(f'<article class="fb-task {"done" if ready else "open"}">'
                        f'<div class="fb-task-head"><span class="fb-task-status">{e(label)}</span>'
                        f'<span class="fb-task-symbol">{"✓" if ready else "↗"}</span></div>'
                        f'<h4>{e(item["name"])}</h4><p>{e(item["details"])}</p>'
                        f'<div class="fb-task-next"><strong>NEXT ACTION</strong><span>{e(item["next"])}</span></div></article>')
    paint('<div class="fb-tasks-grid">' + "".join(snippets) + '</div>')


def provenance_strip(run) -> None:
    inspected = sum(s.access in {"inspected_page", "inspected_pdf"} for s in run.sources.values())
    unread = len(run.sources) - inspected
    mode = "FICTIONAL / OFFLINE" if run.mode == "offline_test" else "LIVE RUN RECORD"
    paint(f'<div class="fb-proof-strip"><div><span class="fb-proof-icon">◎</span><b>{e(mode)}</b></div>'
          f'<span><strong>{inspected}</strong> inspected pages/documents</span>'
          f'<span><strong>{unread}</strong> search-only or inaccessible records</span>'
          '<span>Inspected ≠ independently fact-checked</span></div>')


def sidebar_brand() -> None:
    paint('''<div class="fb-brand"><div class="fb-brand-mark">F</div>
    <div><div class="fb-brand-name">FlytBase</div>
    <div class="fb-brand-sub">LEAD WORKBENCH</div></div></div>''')


def sidebar_providers(credentials: dict) -> None:
    service_map = (("Groq", "Writes and checks drafts", "GROQ_API_KEY"),
                   ("Tavily", "Finds public web sources", "TAVILY_API_KEY"))
    html = '<div class="fb-sidebar-label">TOOLS USED</div>'
    for name, subtitle, key in service_map:
        configured = bool(credentials.get(key))
        html += (f'<div class="fb-service"><div><strong>{name}</strong><small>{subtitle}</small></div>'
                 f'<span class="fb-pulse {"" if configured else "off"}" aria-label="{ "configured" if configured else "not configured"}"></span></div>')
    paint(html)
    paint('<div class="fb-sidebar-note">🔒 &nbsp; API keys stay on this computer. '
          'Green means a key is present, not that your account limits or billing were checked. '
          'Emails are never sent by this app.</div>')


def editor_tip() -> None:
    paint('''<div class="fb-editor-note">
      <div class="fb-spark">THREE THINGS TO KNOW</div>
      <div class="fb-step"><span class="fb-step-number">01</span>
        <span class="fb-step-body"><strong>Paste the customer message</strong>You do not need to fill out a form.</span></div>
      <div class="fb-step"><span class="fb-step-number">02</span>
        <span class="fb-step-body"><strong>Check real sources</strong>The tool finds sources and flags what it cannot prove.</span></div>
      <div class="fb-step"><span class="fb-step-number">03</span>
        <span class="fb-step-body"><strong>Save the results</strong>Download the drafts and sales-team notes. Nothing is emailed.</span></div>
      <div class="fb-note">Already ran the tool? Open the saved results below. That uses no AI credits.</div>
    </div>''')


def banner(run_id: str, status: str, replay: bool, mode: str) -> None:
    head = "Saved run · read-only replay" if replay else "Current session · live workflow"
    detail = f"{run_id} · {mode} origin · replay makes no API calls" if replay else f"{run_id} · provider calls only occur on explicit actions"
    paint(f'<div class="fb-status-banner"><div><strong>{e(head)}</strong><p>{e(detail)}</p></div>{pill(status)}</div>')


def kpi(label: str, value: str, foot: str, accent: str, unit: str = "") -> None:
    allowed = {"purple": "#0b9275", "cyan": "#14aa94", "blue": "#3b8cbb", "amber": "#e4a15c"}
    color = allowed.get(accent, allowed["purple"])
    paint(f'<div class="fb-kpi" style="--accent:{color}"><div class="fb-kpi-label">{e(label)}</div>'
          f'<div class="fb-kpi-value">{e(value)}<small>{e(unit)}</small></div>'
          f'<div class="fb-kpi-desc">{e(foot)}</div></div>')


def stage_card(num: int, name: str, status: str, warnings: int) -> None:
    paint(f'<div class="fb-stage"><div class="fb-stage-top">'
          f'<span class="fb-stage-num">{num:02d}</span>{pill(status)}</div>'
          f'<div class="fb-stage-name">{e(name)}</div>'
          f'<div class="fb-stage-foot">{warnings} review note{"s" if warnings != 1 else ""}</div></div>')


def stage_head(number: int, name: str, status: str, count: int) -> None:
    paint(f'<div class="fb-review-head"><div><b>{number:02d} / {e(name)}</b>'
          f'<small>{count} warning{"s" if count != 1 else ""} to review · no results rewritten</small></div>'
          f'{pill(status)}</div>')


def _panel(title: str, body: str, status: str = "", small: str = "") -> str:
    state = pill(status) if status else ""
    return (f'<div class="fb-panel"><h4>{e(title)}</h4>{state}'
            f'<p>{e(body)}</p>{f"<small>{e(small)}</small>" if small else ""}</div>')


def stage_showcase(stage, sources=None, enquiry="", as_of="") -> None:
    """High-signal, read-only preview; full sources and claims are rendered separately."""
    data = stage.output or {}
    name = stage.name
    if name == "Qualification":
        lead = data.get("lead", {})
        items = (("Budget", "budget"), ("Authority", "authority"),
                 ("Need", "need_dimension"), ("Timeline", "timeline"))
        html = '<div class="fb-mini-grid">'
        for title, key in items:
            dimension = lead.get(key, {})
            snippet = "; ".join(dimension.get("evidence", [])[:1]) or "Not established from enquiry"
            html += _panel(title, snippet, dimension.get("status", "unknown"))
        paint(html + "</div>")
        paint('<div class="fb-issue"><b>Lead priority is different from how many questions are answered.</b> '
              'Budget, authority and a dated timeline still require buyer confirmation. '
              'The lead can still be worth calling even when these facts are missing.</div>')
    elif name == "Deep Account Research":
        from .review import cleared_claims
        cleared = cleared_claims(data, sources or {}, enquiry, as_of) if sources is not None else []
        html = '<div class="fb-mini-grid">'
        for topic in data.get("topics", []):
            claims, gaps = topic.get("claims", []), topic.get("gaps", [])
            visible = [row for row in cleared if row["topic"] == topic.get("name")]
            fragment = visible[0]["claim"]["text"] if visible else "No public finding cleared the recorded evidence checks in this area."
            html += _panel(topic.get("name", "Research area"), fragment,
                           "partial" if gaps or not claims else "neutral",
                           f"{len(visible)} cleared finding(s) · {len(gaps)} recorded gap(s)")
        paint(html + "</div>")
        if cleared:
            from .reporting import source_link
            cited = list(dict.fromkeys(r["source_id"] for row in cleared for r in row["claim"]["evidence"]))
            st.markdown("Supporting sources: " + " · ".join(source_link(sid, sources) for sid in cited))
        paint('<div class="fb-issue">Some research statements still need proof. '
              'Open the source links and check the actual wording before quoting them.</div>')
    elif name == "Response Generation":
        drafts = data.get("drafts", [])
        paint(f'<div class="fb-spark">DRAFT SEQUENCE · {len(drafts)} BRANCHES · NOTHING SENT</div>')
        for draft in drafts:
            paragraphs = "\n\n".join(p.get("text", "") for p in draft.get("paragraphs", []))
            scenario = "Hypothetical branch" if draft.get("hypothetical") else "Initial outreach"
            recovery = draft.get("review_status") == "source_limited_fallback"
            label = '<span class="fb-pill neutral">◆ Enquiry-only safe draft</span>' if recovery else pill("neutral")
            paint(f'<div class="fb-email">{label} <span class="fb-spark">&nbsp; {e(scenario)} · {e(draft.get("branch", ""))}</span>'
                  f'<div class="fb-email-subject">{e(draft.get("subject", "Untitled draft"))}</div>'
                  f'<div class="fb-email-body">{e(paragraphs)}</div>'
                  f'<div class="fb-email-foot"><strong>When:</strong> {e(draft.get("trigger", ""))} &nbsp; · &nbsp; '
                  f'<strong>Why:</strong> {e(draft.get("why_this_message", ""))} &nbsp; · '
                  f'<strong>Next:</strong> {e(draft.get("if_buyer_responds", ""))}</div></div>')
            if sources:
                from .reporting import source_link
                cited = list(dict.fromkeys(ref["source_id"] for paragraph in draft.get("paragraphs", [])
                                            for ref in paragraph.get("evidence", [])))
                if cited:
                    st.markdown("Draft evidence: " + " · ".join(source_link(sid, sources) for sid in cited))
        if data.get("safe_recovery"):
            paint('<div class="fb-issue">One or more AI drafts failed evidence checks. The visible replacement drafts '
                  'were generated from the enquiry alone by a local recovery rule, not passed off as approved AI research. '
                  'Nothing was sent; review wording before outreach.</div>')
        else:
            paint('<div class="fb-issue">These are reviewable drafts requiring human approval. Nothing was sent. '
                  'See the full analysis to check what supports each claim.</div>')
    elif name == "Case Study and Material Matching":
        winner = data.get("primary")
        audited = data.get("groundedness", {}).get("semantic_review") == "performed"
        if winner and winner.get("candidate"):
            paint('<div class="fb-spark">' + ('SELECTED BY SAVED WORKFLOW' if audited else 'PROVISIONAL SOURCE-BASED COMPARISON · SEMANTIC REVIEW UNAVAILABLE') + '</div>')
            c = winner["candidate"]
            paint(_panel(c.get("title", "Selected material"),
                         str(c.get("relevance", {}).get("text", "")), "complete" if audited else "partial",
                         f"Evidence-gated relevance: {winner.get('score', 0)}/100"))
        else:
            paint('<div class="fb-issue"><strong>No case study chosen yet.</strong> '
                  'The available examples did not have enough verified evidence. Their scores are shown below, but none was approved.</div>')
        html = '<div class="fb-mini-grid">'
        for comp in data.get("comparison", []):
            candidate = comp.get("candidate", {})
            score = comp.get("score", 0)
            issues = comp.get("rejection_reasons", [])
            html += _panel(candidate.get("title", "Candidate"),
                           "; ".join(issues[:2]) if issues else "No rejection reasons supplied.",
                           "complete" if comp.get("eligible") and audited else "partial",
                           f"Relevance score {score}/100 · {'Eligible' if comp.get('eligible') else 'Not eligible'}")
        paint(html + "</div>")
    elif name == "Partner Identification":
        route = data.get("recommended_motion", "unverified").replace("_", " ").title()
        fallback = any(x in (data.get("decision_basis") or "").lower()
                       for x in ("fallback", "did not complete", "policy"))
        paint(f'<div class="fb-action"><div class="fb-eyebrow">WHO FOLLOWS UP · {e("POLICY FALLBACK" if fallback else "PROPOSED")}</div>'
              f'<h3>{e(route)}</h3><p>{e(data.get("next_action", "No next action supplied."))}</p></div>')
        html = '<div class="fb-mini-grid">'
        html += _panel("Commercial owner", data.get("commercial_owner", "Unverified"))
        html += _panel("Implementation partner", data.get("implementation_owner", "Not assigned"))
        paint(html + "</div>")
        if fallback:
            paint('<div class="fb-issue">The tool picked a safe default because the partner check stopped early. '
                  'A local partner has not been confirmed.</div>')
    elif name == "AE Handoff Summary":
        paint(f'<div class="fb-action"><div class="fb-eyebrow">RECOMMENDED NEXT STEP</div>'
              f'<h3>{e(data.get("suggested_next_action", "Schedule discovery and confirm unknowns"))}</h3>'
              f'<p>{e(data.get("why", "Review outstanding evidence before outreach."))}</p></div>')
        from .identity import handoff_identity
        ctx, recovered = handoff_identity(data)
        html = '<div class="fb-mini-grid">'
        html += _panel("Buyer", f"{ctx.get('name', 'Unknown')} · {ctx.get('title', 'Unknown role')}")
        html += _panel("Company & geography", f"{ctx.get('company', 'Unknown')} · {ctx.get('geography', 'Unknown region')}")
        paint(html + "</div>")
        if recovered:
            st.caption("Missing handoff identity fields are displayed from the original enquiry qualification; the saved record is unchanged.")
        if data.get("important_limitations"):
            paint('<div class="fb-issue"><b>Handoff contains unresolved limitations.</b> '
                  'See detailed source-backed findings below before using it commercially.</div>')


def footer() -> None:
    paint('<div class="fb-footer">FlytBase Inbound Command · Local prototype · '
          'Read-only replay and downloads consume no Groq tokens or Tavily credits. '
          'Outputs require human review before commercial use.</div>')
