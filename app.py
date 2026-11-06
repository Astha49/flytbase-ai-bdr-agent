"""FlytBase Inbound Intelligence — evaluator-first Streamlit workbench.

Five purposeful views separate sales outcomes from operator configuration. All
read-only navigation, evidence inspection and exports are entirely local.
Provider requests require the existing explicit live-approval gate.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

from flytbase_bdr.budget import ProjectBudget
from flytbase_bdr.config import ROOT, Settings, credential_status, has_api_key
from flytbase_bdr.diagnostics import assess_run, review_markdown
from flytbase_bdr.execution import approved_live_execution
from flytbase_bdr.planning import plan_resume
from flytbase_bdr.progression import simulate_followup
from flytbase_bdr.readiness import check_requirements
from flytbase_bdr.reporting import (
    json_export, handoff_export, load_run, markdown_export, render_value, save_run,
    source_link, stage_markdown,
)
from flytbase_bdr.ui import (
    e, paint, inject_styles, hero, sidebar_brand, banner, kpi, section,
    stage_showcase, stage_head, workflow_track, next_steps_board,
    provenance_strip, footer, evidence_experience, operator_experience,
    narrative_masthead, story_ribbon,
)
from flytbase_bdr.workflow import Workflow, fork_resume


PAGES = (
    "Command Center", "Account Intelligence", "Sales Strategy",
    "AE Handoff", "How It Works & Evidence",
)


def scroll_page_to_top() -> None:
    """Reset the *main* content scroller after workspace navigation.

    Streamlit reruns a single document for radio-based navigation, retaining the
    previous scroll offset. Prefer first-party st.html JavaScript (Streamlit
    1.52+) running in the app document; older versions get a same-origin iframe
    fallback. Both paths are display-only and never call providers.
    """
    javascript = r"""
    (function () {
      // Repaint/rerun can restore a stale position after the first render.
      // Repeat briefly, but only on navigation or explicit saved-run loading.
      function resetMainScroll() {
        const selectors = [
          'section[data-testid="stMain"]',
          '[data-testid="stAppViewContainer"]',
          '[data-testid="stMain"]',
          'section.main', 'main'
        ];
        for (const selector of selectors) {
          const el = document.querySelector(selector);
          if (el) {
            el.scrollTop = 0;
            if (typeof el.scrollTo === 'function') el.scrollTo({ top: 0, behavior: 'instant' });
          }
        }
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
        window.scrollTo(0, 0);
      }
      function resetAfterNavigation() {
        resetMainScroll();
        [50, 150, 350, 700, 1200].forEach(ms =>
          window.setTimeout(resetMainScroll, ms)
        );
      }
      // Capture future sidebar navigation *before* Streamlit starts rerendering.
      // A single persistent listener survives normal single-page reruns.
      if (!window.__flytbaseMainScrollListenerInstalled) {
        const navSelector = 'section[data-testid="stSidebar"] [role="radiogroup"] label';
        document.addEventListener('pointerdown', event => {
          if (event.target instanceof Element && event.target.closest(navSelector)) {
            resetAfterNavigation();
          }
        }, true);
        document.addEventListener('keydown', event => {
          if ((event.key === 'Enter' || event.key === ' ') &&
              event.target instanceof Element && event.target.closest(navSelector)) {
            resetAfterNavigation();
          }
        }, true);
        window.__flytbaseMainScrollListenerInstalled = true;
      }
      resetAfterNavigation();
    })();
    """
    # st.html(..., unsafe_allow_javascript=True) is available in Streamlit
    # 1.52+, and executes in the parent document rather than a child iframe.
    try:
        st.html("<script>" + javascript + "</script>", unsafe_allow_javascript=True)
    except TypeError:
        # Compatible fallback for existing deployments on Streamlit 1.50–1.51.
        # A srcdoc iframe can access the parent only if the browser permits it.
        components.html(
            "<script>(function(){try{var window=parent;var document=parent.document;"
            + javascript + "}catch(_){}})();</script>",
            height=0, scrolling=False,
        )


def friendly_run(path) -> str:
    """User-facing label; exact run identifiers remain in audit and downloads."""
    try:
        dt = datetime.strptime(path.parent.name[:15], "%Y%m%dT%H%M%S")
        return f"{dt:%d %b %Y · %H:%M}  ·  Saved analysis"
    except (ValueError, AttributeError):
        return "Saved analysis"


def stage_status(stage) -> str:
    return {"complete": "Completed", "partial": "Review Needed", "failed": "Failed",
            "running": "Working", "pending": "Queued", "skipped": "Skipped"}.get(stage.status, stage.status)


def inspected_count(run) -> int:
    return sum(s.access in {"inspected_page", "inspected_pdf"} for s in run.sources.values())


def limit_notice(run) -> None:
    """One truthful banner, not a warning repeated after every widget."""
    if run.mode == "offline_test":
        st.info("Illustrative example only — this fictional simulation is not a verified live result.")
    elif run.status != "complete":
        st.warning("This saved analysis needs review. Some outputs are incomplete or lack verified evidence. "
                   "Open the relevant stage to see what is missing.")
    else:
        st.info("The workflow finished. Review the original sources and sales drafts before using the findings.")


def show_stage(run, index: int, *, details: bool = True) -> None:
    stage = run.stages[index]
    stage_head(index + 1, stage.name, stage.status, len(stage.warnings))
    stage_showcase(stage, run.sources, run.input, run.as_of_date)
    if stage.status in {"partial", "failed", "skipped"}:
        checks = check_requirements(run)
        if index < len(checks):
            check = checks[index]
            st.warning(f"**What is missing:** {check['details']}\n\n"
                       f"**Why it matters:** {check.get('why', 'This stage affects downstream decisions.')}\n\n"
                       f"**Next:** {check['next']}")
    if details:
        with st.expander("Full output and cited evidence", expanded=False):
            st.markdown(stage_markdown(stage, run.sources, include_warnings=False))
        if stage.warnings:
            with st.expander(f"What still needs checking ({len(stage.warnings)})", expanded=False):
                for warning in stage.warnings:
                    st.write("• " + warning)


def source_catalogue(run) -> None:
    rows = sorted(run.sources.items(), key=lambda pair: (
        pair[1].access not in {"inspected_page", "inspected_pdf"}, pair[1].title.casefold()))
    st.caption("An inspected page is not necessarily an independently verified claim. "
               "Source snippets, extracted text and dates can be incomplete.")
    if not rows:
        st.info("No retrieved evidence is available for this run.")
        return
    for sid, src in rows:
        verified_text = src.access in {"inspected_page", "inspected_pdf"}
        label = "Inspected page" if verified_text else "Search result / inaccessible"
        with st.expander(f"{src.title[:95]}  ·  {label}"):
            st.link_button("Open original source ↗", src.url)
            st.caption(f"Recorded ID: {sid} · Published: {src.publication_date or 'Not established'}")
            st.text((src.text or "No original page text was inspected.")[:8000])
            if not verified_text and src.search_context:
                st.caption("Search excerpt only — do not treat this as an inspected document.")
                st.text(src.search_context[:1500])


def downloads(run) -> None:
    st.caption("Download this recorded execution, including evidence and limitations. No API usage.")
    left, right, brief = st.columns(3)
    with left:
        st.download_button("↓ Download readable report", markdown_export(run),
                           file_name=f"{run.run_id}.md", mime="text/markdown", on_click="ignore")
    with right:
        st.download_button("↓ Download source-backed run data", json_export(run),
                           file_name=f"{run.run_id}.json", mime="application/json", on_click="ignore")
    with brief:
        st.download_button("↓ Download AE handoff", handoff_export(run),
                           file_name=f"{run.run_id}-ae-handoff.md", mime="text/markdown", on_click="ignore")


st.set_page_config(page_title="FlytBase | Inbound Intelligence", page_icon="✦",
                   layout="wide", initial_sidebar_state="expanded")
inject_styles(ROOT)
settings = Settings.from_env()
configured = has_api_key()
ledger = ProjectBudget(settings).summary()
final_demo = ProjectBudget(settings).demo_summary()

with st.sidebar:
    sidebar_brand()
    paint('<div class="fb-sidebar-label">WORKSPACE</div>')
    page_options = list(PAGES)
    if st.session_state.get("operator_visibility", False):
        page_options.append("Operator Tools")
    # The advanced page must not remain selected after the sidebar toggle hides it.
    if st.session_state.get("workspace_page") not in (None, *page_options):
        st.session_state["workspace_page"] = "Command Center"
    page = st.radio("Navigate", page_options, label_visibility="collapsed", key="workspace_page")
    paint('<div class="fb-sidebar-navfoot">Explore lead decisions, original evidence and a concise sales handoff. '
          'Technical controls are separate from the reviewer experience.</div>')
    # Stable location, sidebar only. The previous patch mounted this expander in
    # the main page only when scrolling reset, so it jumped and disappeared.
    with st.expander("Advanced tools (optional)", expanded=False):
        st.checkbox("Show operator workspace", key="operator_visibility",
                    help="Adds an optional Operator Tools page without changing the five review pages.")

# Only navigation and explicitly loading a saved analysis should reset scroll.
scroll_needed = (st.session_state.get("_last_workspace_page") != page
                 or st.session_state.pop("_show_loaded_run_at_top", False))
st.session_state["_last_workspace_page"] = page
if scroll_needed:
    scroll_page_to_top()

# Keep explicit approval available but tucked into a separate operator panel.
# The selected mode never grants approval on its own.
with st.sidebar:
    with st.expander("Execution controls · operator only", expanded=False):
        execution_mode = st.radio("Execution mode", ["Read-only demonstration", "Protected live execution"],
                                  key="execution_mode")
        read_only = execution_mode == "Read-only demonstration"
        allowance_version = (final_demo["id"], len(final_demo.get("amendments", []))) if final_demo else None
        if st.session_state.get("_allowance_approval_version") != allowance_version:
            st.session_state["live_action_approval"] = False
            st.session_state["final_demo_quota_confirmation"] = False
            st.session_state["_allowance_approval_version"] = allowance_version
        if read_only or st.session_state.pop("approval_consumed", False):
            st.session_state["live_action_approval"] = False
        live_phase_label = st.selectbox("Use allowance for", ["Finish incomplete steps", "Record fresh demo"],
                                        disabled=read_only, key="live_phase_choice")
        live_phase = "demo" if live_phase_label == "Record fresh demo" else "repair"
        quota_required = bool(final_demo and final_demo.get("quota_confirmation_required") and live_phase == "demo")
        quota_confirmed = False
        if quota_required:
            quota_confirmed = st.checkbox(f"I checked current free quotas: at least 69,759 Groq tokens, 30 Groq requests and {final_demo['limits']['tavily']} Tavily credits remain; paid billing is off",
                                           disabled=read_only, key="final_demo_quota_confirmation")
        live_approved = st.checkbox("I approve provider requests for this action", disabled=read_only,
                                    key="live_action_approval")
        st.caption("Finish incomplete steps uses the repair allowance. Record fresh demo uses the protected demo allowance. "
                   "Neither starts anything until you approve a specific action. No paid provider fallback or email sending.")
        if final_demo:
            st.caption(f"One-time final demo: {final_demo['state']}; "
                       f"{final_demo['groq_remaining']:,}/{final_demo['limits']['groq']:,} tokens and {final_demo['tavily_remaining']}/{final_demo['limits']['tavily']} credits remaining. "
                       "One run only; fresh AI generation may reuse dated research sources. Approval is still required.")

if not st.session_state.get("run") and not st.session_state.get("job"):
    saved_files = sorted(settings.run_path().glob("*/run.json"), reverse=True) if settings.run_path().exists() else []
    if saved_files:
        try:
            st.session_state.run = load_run(saved_files[0])
            st.session_state.replay = True
        except (ValueError, OSError, KeyError):
            pass
    if not st.session_state.get("run"):
        example = ROOT / "examples/recruiter_demo/offline_simulation/run.json"
        if example.exists():
            st.session_state.run = load_run(example)
            st.session_state.replay = True

run = st.session_state.get("run")
job = st.session_state.get("job")
busy = bool(job and job["thread"].is_alive())

def launch_work(enquiry: str, saved=None, stages=None, *, resume_same_demo=False, allowance_id="") -> None:
    """Start one explicit quota-bounded job; never start from a normal rerender."""
    if read_only or not live_approved:
        st.error("Live execution requires explicit approval in Operator controls.")
        return
    if st.session_state.get("job") and st.session_state.job["thread"].is_alive():
        return
    events = queue.Queue()
    approval_for_job, phase_for_job = bool(live_approved), live_phase
    quota_for_job = bool(quota_confirmed)
    st.session_state["approval_consumed"] = True

    def worker():
        try:
            if allowance_id:
                from flytbase_bdr.run_allowance import execute
                result = execute(settings, allowance_id, approved=approval_for_job,
                                 on_update=lambda item: events.put(("update", item.model_copy(deep=True))))
                events.put(("finished", result))
                return
            continuation = (saved if resume_same_demo else fork_resume(saved, settings)) if saved is not None else None
            with approved_live_execution(approval_for_job, phase=phase_for_job, confirmed_free_quota=quota_for_job):
                result = Workflow(settings).execute(
                    enquiry, on_update=lambda result: events.put(("update", result.model_copy(deep=True))),
                    resume=continuation, rerun_stages=stages)
            events.put(("finished", result))
        except Exception as error:
            # Do not expose provider response bodies, which might contain sensitive text.
            from flytbase_bdr.provider import ProviderError
            from flytbase_bdr.reporting import RunSaveError
            from flytbase_bdr.run_allowance import AllowanceError
            events.put(("error", str(error) if isinstance(error, (ProviderError, RunSaveError, AllowanceError)) else type(error).__name__))

    thread = threading.Thread(target=worker, daemon=True)
    st.session_state.job = {"thread": thread, "events": events, "started": time.monotonic()}
    st.session_state.replay = False
    st.session_state["_sample_loaded"] = False
    st.session_state["_live_started_just_now"] = True
    if saved is None or allowance_id:
        # Never mistake an old saved analysis for the one being generated.
        st.session_state.pop("run", None)
    thread.start()


def budget_panel(current) -> None:
    from flytbase_bdr.run_allowance import overview, plan
    view = overview(settings)
    section("RESOURCE SAFETY", "Usage and execution allowance", "Local ledger ≠ current provider balance")
    cols = st.columns(4)
    cols[0].metric("Historical Groq reported", f"{view['historical_groq_reported']:,}")
    cols[1].metric("Historical usage unknown", f"{view['historical_groq_unknown']:,}")
    cols[2].metric("Local Groq today · UTC", f"{view['local_groq_today_counted']:,}")
    cols[3].metric("Legacy repair available", f"{ledger['groq'].get('repair_remaining', 0):,}")
    st.caption(f"Legacy cumulative ceiling: {view['legacy_project_ceiling']:,}. Provider daily planning cap: "
               f"{view['provider_daily_limit_planning_cap']:,}; current account balance is unverified. "
               f"Emergency reserve: {ledger['groq'].get('emergency_reserve', 7759):,}; "
               f"protected demo reserve: {ledger['groq'].get('demo_reserve_at_approval', 38000):,}. "
               "Historical cumulative usage is not today's usage. New allowances require separate approval; nothing renews automatically.")
    with st.expander("Plan a zero-Tavily continuation · no API usage", expanded=False):
        if current is None or current.mode != "live":
            st.info("Open a saved live execution to estimate a cache-only continuation. Fictional examples remain read-only.")
            return
        try:
            proposal = plan(settings, settings.run_path() / current.run_id / "run.json")
        except (ValueError, OSError) as error:
            st.warning(str(error))
            return
        st.write(f"Estimated comparable workload: {proposal['groq_estimated_workload_tokens']:,} tokens; "
                 f"suggested cap with reserve: {proposal['recommended_new_run_cap']:,}. "
                 "Zero Tavily calls; reuse qualification and inspected research, regenerate stages 2–6. No automatic retries.")
        st.caption(proposal["estimate_limitations"] + " Cached source dates remain unchanged.")
        import json
        st.download_button("Download read-only execution plan", json.dumps(proposal, indent=2),
                           file_name=f"{current.run_id}-plan.json", mime="application/json", on_click="ignore")
        items = [a for a in view["new_run_allowances"] if a["state"] == "approved" and a["utc_day"] == view["utc_day"]]
        if not items:
            st.info("No new-run allowance is approved. Live continuation remains blocked. See the README for the separate budget and launch approval steps.")
        else:
            selected = st.selectbox("Separately approved cache-only allowance", [a["id"] for a in items])
            selected_item = next(a for a in items if a["id"] == selected)
            st.caption(f"Bound source: {selected_item['source_run_id']}; allowance remaining: {selected_item['groq_remaining']:,} tokens. "
                       "This may differ from the viewed run. Approval never sends emails.")
            if st.button("Run approved cached continuation", disabled=read_only or not live_approved or busy or not configured):
                launch_work(current.input, saved=current, allowance_id=selected)
                st.rerun()


def live_input() -> None:
    """Explicit two-step launch; loading a sample never makes an API request."""
    if "enquiry" not in st.session_state:
        st.session_state.enquiry = st.session_state.get("enquiry_saved", "")
    st.caption("Paste one buyer enquiry, or use the included sample. Loading a message is not a live run.")
    if st.button("↗ Use FlytBase sample enquiry", disabled=busy):
        st.session_state.enquiry = (ROOT / "examples/enquiry.txt").read_text(encoding="utf-8")
        st.session_state["_sample_loaded"] = True
    st.text_area("Customer message", key="enquiry", height=160, disabled=busy,
                 placeholder="Paste the inbound buyer's message here…")
    st.session_state["enquiry_saved"] = st.session_state.enquiry
    available = ledger["groq"]["remaining_for_reservation"]
    # The provider enforces the emergency reserve even in demo mode. The UI
    # must use the SAME effective allowance or it will enable a run only for
    # the first model call to be blocked after partial research has started.
    phase_remaining = (ledger["groq"].get("repair_remaining", available)
                       if live_phase == "repair" else
                       max(0, available - ledger["groq"].get("emergency_reserve", 0)))
    credits_remaining = ledger["tavily"]["remaining_for_reservation"]
    one_time = live_phase == "demo" and final_demo is not None
    if one_time:
        available = phase_remaining = final_demo["groq_remaining"]
        credits_remaining = final_demo["tavily_remaining"]
    enough_budget = (phase_remaining >= 13200 and
                     credits_remaining >= (min(12, final_demo["limits"]["tavily"]) if one_time else 15) and (not one_time or final_demo["state"] == "prepared"))
    allowed = (not read_only and live_approved and (not quota_required or quota_confirmed) and not busy and configured
               and bool(st.session_state.enquiry.strip()) and enough_budget)
    if st.session_state.get("_sample_loaded") and not busy:
        st.info("Sample enquiry loaded. **No AI workflow has started yet.** Select Protected live execution, "
                "check provider approval, then click Run once when ready to use free-tier quotas.")
    if st.button("Run six-stage analysis →", type="primary", disabled=not allowed):
        launch_work(st.session_state.enquiry)
        st.rerun()
    if busy:
        st.caption("A live run is underway. Do not start another run; follow the stage monitor above.")
    elif read_only:
        st.caption("Read-only mode: switch to Protected live execution to enable a new run. No API calls made.")
    elif not live_approved:
        st.warning("**Not running:** the checkbox **I approve provider requests for this action** "
                   "in the sidebar is unchecked. Loading a sample does not trigger analysis.")
    elif quota_required and not quota_confirmed:
        st.warning("Current provider balances have not been verified in this session. Check both dashboards and confirm free quota before launch; local allowances do not increase provider quotas.")
    elif not configured:
        st.warning("**Not running:** the configured Groq credentials are unavailable. Check local .env privately.")
    elif one_time and final_demo["state"] != "prepared":
        st.warning("The one-time demo has already started or finished. A second run is blocked. Open its saved result; do not reset the allowance.")
    elif not enough_budget:
        st.warning(
            "**Not running:** saved application allowance is below the new-run reservation "
            f"(Groq: {int(available):,}/13,200 tokens available; "
            f"phase: {int(phase_remaining):,}/13,200; "
            f"Tavily: {int(credits_remaining)}/{min(12, final_demo['limits']['tavily']) if one_time else 15} credits). "
            "These are APP ledger limits, not the provider's live quota. "
            "Nothing was requested. Preserve the ledger; inspect the saved run or "
            "continue only with a separately approved feasible plan."
        )
    elif not st.session_state.enquiry.strip():
        st.caption("Enter a buyer message before running the analysis.")
    else:
        st.caption("Ready for your explicitly approved run. Real Groq/Tavily free-tier quotas must also be available.")


def choose_run() -> None:
    """Open a saved analysis only when the user submits the form.

    Streamlit reruns on normal selectbox changes. Previously choosing a date
    immediately reran the app and jumped to the top *before* the user could
    press Open. A form batches selection and confirmation into one interaction.
    This changes only saved-run replay; it cannot invoke either provider.
    """
    saved = sorted(settings.run_path().glob("*/run.json"), reverse=True) if settings.run_path().exists() else []
    if not saved:
        st.caption("No private runs included. The bundled fictional preview is still available.")
        return
    with st.form("open_saved_analysis_form", clear_on_submit=False):
        chosen = st.selectbox(
            "Saved analyses", saved, index=None, format_func=friendly_run,
            key="saved_selector", placeholder="Choose a saved analysis…",
        )
        submitted = st.form_submit_button("Open saved analysis")
    st.caption("Choose a date, then click Open. Selecting a date alone will not reload the page.")
    if submitted:
        if chosen is None:
            st.warning("Select a saved analysis first.")
            return
        try:
            loaded = load_run(chosen)
        except (ValueError, OSError, KeyError):
            st.error("Could not open or validate that saved result.")
            return
        st.session_state.run = loaded
        st.session_state.replay = True
        st.session_state["_show_loaded_run_at_top"] = True
        st.session_state["_recently_opened_run"] = loaded.run_id
        st.rerun()


# The main stage monitor is rendered above EVERY workspace page while a job is
# active. Keeping an independently updating fragment out of the sidebar avoids
# concurrent rerenders in the same container as the navigation radio buttons.
STAGE_LABELS = (
    "Qualify the enquiry", "Research the account", "Draft five reply paths",
    "Match customer proof", "Determine partner route", "Prepare AE handoff",
)


def live_stage_visual(stages) -> None:
    """A small on-brand animation, driven ONLY by actual recorded checkpoints."""
    statuses = [s.status for s in stages] if stages else ["pending"] * 6
    labels = {"pending": "Queued", "running": "Working", "complete": "Completed",
              "partial": "Review needed", "failed": "Failed", "skipped": "Skipped"}
    done = sum(status in {"complete", "partial", "failed", "skipped"} for status in statuses)
    active = next((i for i, status in enumerate(statuses) if status == "running"), None)
    if active is None and done < 6:
        active = next((i for i, status in enumerate(statuses) if status == "pending"), None)
    cards = []
    for i, (label, status) in enumerate(zip(STAGE_LABELS, statuses)):
        emphasis = "fb-live-stage-active" if active == i else ""
        cards.append(
            f'<div class="fb-live-stage fb-live-stage-{e(status)} {emphasis}">'
            f'<span class="fb-live-stage-n">{i+1:02d}</span>'
            f'<span class="fb-live-stage-label">{e(label)}</span>'
            f'<span class="fb-live-stage-state">{e(labels.get(status, status))}</span></div>'
        )
    paint('<div class="fb-live-console" role="status" aria-label="Live AI workflow progress">'
          '<div class="fb-live-heading"><span class="fb-live-orbit" aria-hidden="true"><i></i></span>'
          '<div><small>FLYTBASE · LIVE SIGNAL</small><h3>Building your account intelligence.</h3>'
          '<p>Six connected decisions. Live checkpoints appear as each step finishes.</p></div></div>'
          + '<div class="fb-live-stage-grid">' + ''.join(cards) + '</div>'
          + f'<div class="fb-live-foot">{done} of 6 stages have reached an outcome · '
            'Queued means waiting for the previous stage, not a failed request.</div></div>')
    st.progress(done / 6, text=f"{done}/6 stages have completed an attempt — evidence review follows")


@st.fragment(run_every="1s")
def progress_panel() -> None:
    """Poll a live job without blocking navigation or making provider calls."""
    job_live = st.session_state.get("job")
    if not job_live:
        return
    while True:
        try:
            kind, value = job_live["events"].get_nowait()
        except queue.Empty:
            break
        if kind in {"update", "finished"}:
            st.session_state.run = value
            if kind == "finished":
                st.session_state["_last_live_result"] = (
                    f"Live execution finished with status '{value.status}'. "
                    "Inspect stage results and supporting sources; partial is not a pass."
                )
        elif kind == "error":
            st.session_state["_last_live_error"] = (
                f"Workflow interrupted ({value}). Inspect the most recent saved run "
                "and terminal; no automatic retry or duplicate provider calls."
            )
    current = st.session_state.get("run")
    live_stage_visual(current.stages if current else None)
    st.caption(f"Elapsed: {int(time.monotonic() - job_live['started'])} seconds. "
               "Free-tier pacing can pause requests; queued stages have not failed.")
    if current:
        st.caption(f"Live run ID: {current.run_id} · Saved status: {current.status}")
        if (current.stages[0].status == "running" and
                time.monotonic() - job_live["started"] > 240):
            st.warning("Qualification has been running more than four minutes. This first stage "
                       "normally needs just one model extraction; a stalled provider or worker is possible. "
                       "Do not start a second run. Diagnose the existing checkpoint before any recovery.")
        waits = [entry for entry in current.logs[-20:] if entry.get("event") in {"rate_wait", "retry_wait"}]
        if waits:
            most_recent = waits[-1]
            st.caption(f"Last recorded API pause: {most_recent.get('provider', 'provider')} "
                       f"({most_recent.get('event')}, {most_recent.get('seconds', '?')}s); "
                       "rate limiting is not model processing.")
        for i, item in enumerate(current.stages):
            if item.status == "failed":
                st.error(f"Stage {i + 1}: {item.name} failed. Inspect its saved warnings; do not rerun automatically.")
    else:
        st.caption("Starting the first checkpoint. Nothing has failed merely because later steps are queued.")
    if not job_live["thread"].is_alive():
        st.session_state.pop("job", None)
        st.rerun()  # One app-wide refresh after the worker exits.


if st.session_state.get("job"):
    # Render progress in the MAIN content, not in the sidebar navigation.
    progress_panel()


if page == "Command Center":
    hero(read_only=read_only)
    budget_panel(run)
    last_error = st.session_state.pop("_last_live_error", None)
    last_result = st.session_state.pop("_last_live_result", None)
    if last_error:
        st.error(last_error)
    elif last_result:
        if run and run.status == "complete":
            st.success(last_result)
        else:
            st.warning(last_result)
    # Put the only action that starts new research before the OLD saved results;
    # a saved analysis cannot change when the installed code is updated.
    # Recovery is for the ONE original live run whose background process was
    # interrupted. It does not open a fresh quota envelope or new run ID.
    # Operators MUST terminate the old Streamlit process first, to avoid two
    # workers writing to the same checkpoint; only an explicitly approved
    # demo-mode request may continue.
    interrupted_demo = (final_demo is not None and final_demo.get("state") == "started"
                        and run is not None and run.run_id == final_demo.get("run_id")
                        and run.mode == "live" and run.status == "running" and not busy)
    if interrupted_demo:
        with st.expander("Resume the interrupted live demo · same run", expanded=True):
            st.warning("Only use this after fully stopping the old Streamlit process and restarting the app. "
                       "This continues the SAME run with the original remaining quota; it is not a free retry. "
                       "Already saved schema-valid AI responses are reused when their inputs match.")
            resume_allowed = (not read_only and live_phase == "demo" and live_approved and configured
                              and final_demo.get("groq_remaining", 0) > 0)
            if st.button("Resume this SAME live run", type="primary", disabled=not resume_allowed):
                launch_work(run.input, saved=run, resume_same_demo=True)
                st.rerun()
            st.caption("Select Protected live execution → Record fresh demo → approval checkbox to enable. "
                       "No API requests occur until you press Resume.")
    with st.expander("New buyer message · Run an analysis", expanded=(not run or busy or st.session_state.get("_sample_loaded", False))):
        live_input()
    if run:
        st.caption(f"CURRENTLY VIEWING · {run.run_id} · {run.as_of_date} · "
                   f"{run.status.replace('_', ' ').title()}"
                   + (" · Saved analysis (not a new AI execution)" if st.session_state.get("replay") else ""))
        if st.session_state.pop("_recently_opened_run", None) == run.run_id:
            st.success("Saved analysis loaded. The figures may look similar because both runs use the same buyer enquiry.")
        qual = run.stages[0].output or {}
        lead = qual.get("lead") or {}
        handoff = run.stages[5].output or {}
        checks = check_requirements(run)
        ready = sum(c["state"] == "ready" for c in checks)
        paint('<div class="fb-eyebrow">CURRENT OPPORTUNITY</div>')
        paint(f'<div class="fb-opportunity"><div><small>ACCOUNT</small><h2>{e(lead.get("company") or "Lead not identified")}</h2>'
              f'<p>{e(lead.get("name") or "Buyer unknown")} · {e(lead.get("title") or "Role not confirmed")}</p></div>'
              f'<div class="fb-opportunity-action"><small>RECOMMENDED NEXT MOVE</small>'
              f'<p>{e(handoff.get("suggested_next_action") or "Review the verified evidence and plan discovery.")}</p></div></div>')
        cols = st.columns(4, gap="small")
        with cols[0]:
            kpi("Follow-up priority", str(qual.get("priority_score", "—")),
                "Engagement priority, not win probability", "purple", "/100")
        with cols[1]:
            kpi("Qualification known", str(qual.get("qualification_completeness_percent", "—")),
                "Budget · authority · need · timing", "cyan", "%")
        with cols[2]:
            kpi("Stages ready", str(ready), "Out of six evidence-checked outputs", "blue", "/6")
        with cols[3]:
            kpi("Originals inspected", str(inspected_count(run)), "Retrieved documents, not all verified", "amber")
        limit_notice(run)
        produced = sum(bool(item.output) for item in run.stages)
        st.caption(f"STAGE EXECUTION: {produced}/6 saved outputs · EVIDENCE READINESS: {ready}/6 cleared. "
                   "A generated output is not necessarily fact-checked or approved for outreach.")
        section("THE WORKFLOW", "Six connected decisions", "Open each page for details")
        workflow_track(run.stages)
        st.dataframe([{"Stage": f"{i + 1}. {item.name}", "Status": stage_status(item),
                       "Elapsed (s)": round(item.elapsed_seconds, 1), "Review notes": len(item.warnings)}
                      for i, item in enumerate(run.stages)], hide_index=True, width="stretch")
        if st.session_state.get("replay"):
            st.caption("SAVED RESULT — The stage colors describe this earlier run, not the repaired "
                       "code's current live performance. A new six-stage analysis requires "
                       "explicit provider approval and sufficient free-tier quota.")
        if ready < len(checks):
            outstanding = [c for c in checks if c["state"] != "ready"]
            with st.expander(f"{len(outstanding)} stages need attention · What remains", expanded=False):
                for item in outstanding:
                    st.markdown(f"**{item['name']}** — {item['details']}")
        st.caption("Priority describes follow-up urgency. Qualification completeness describes how many buying answers are confirmed.")
    else:
        section("GET STARTED", "Your next inbound opportunity")
        if st.session_state.get("job"):
            st.info("A **new live analysis is running**. Watch the animated six-stage monitor above. "
                    "Other stages remain queued until earlier stages finish. Don't click Run again.")
        else:
            st.info("No saved analysis is available yet. Paste the buyer's message to start.")
    story_ribbon()
    with st.expander("Switch to a previous analysis", expanded=False):
        choose_run()


elif page == "Account Intelligence":
    narrative_masthead("research")
    section("EVIDENCE BRIEF", "Verified findings & open questions",
            "Public evidence · commercial significance · unknowns")
    if not run:
        st.info("Research is being generated. See the live stage monitor above." if busy else "Open an analysis from Command Center to review company research.")
    else:
        limit_notice(run)
        show_stage(run, 1)
        with st.expander("Research gaps and questions for discovery"):
            topics = (run.stages[1].output or {}).get("topics", [])
            for topic in topics:
                if topic.get("gaps"):
                    st.markdown("**" + topic.get("name", "Research") + "**")
                    for missing in topic["gaps"]:
                        st.write("• " + missing)
        st.caption("A company-wide investment figure is not proof of an approved project budget. "
                   "Unknown reporting lines must remain unknown until verified.")

elif page == "Sales Strategy":
    narrative_masthead("strategy")
    section("THE PLAYBOOK", "Three connected sales decisions",
            "Personalized follow-up · customer proof · partner route")
    if not run:
        st.info("Sales decisions are queued behind research. See the live stage monitor above." if busy else "Open an analysis from Command Center to review proposed sales actions.")
    else:
        limit_notice(run)
        emails_tab, cases_tab, partners_tab = st.tabs(["Email progression", "Customer proof", "Partner strategy"])
        with emails_tab:
            st.caption("The five email branches are conditional drafts. No customer reply is assumed and nothing is sent.")
            show_stage(run, 2)
        with cases_tab:
            st.caption("Evidence-led comparison: the strongest match must be discovered from FlytBase sources, never hardcoded.")
            show_stage(run, 3)
        with partners_tab:
            st.caption("Commercial ownership and implementation capacity are distinct decisions. Availability is not presumed.")
            show_stage(run, 4)

elif page == "AE Handoff":
    narrative_masthead("handoff")
    section("THE DECISION BRIEF", "What the AE needs to know",
            "Buyer context · qualification gaps · three insights · next action")
    if not run:
        st.info("The handoff is queued until its upstream stages finish. See the live stage monitor above." if busy else "Open an analysis from Command Center to review the handoff.")
    else:
        limit_notice(run)
        show_stage(run, 5)
        handoff = run.stages[5].output or {}
        highlights = handoff.get("top_three_research_findings") or []
        section("BRIEFING POINTS", "Three account insights", "Exactly as recorded; confirm primary sources")
        if highlights:
            for number, claim in enumerate(highlights[:3], 1):
                st.markdown(f"**{number:02d} · {claim.get('text', 'No finding text recorded')}**")
                citations = [ref.get("source_id", "") for ref in claim.get("evidence", [])]
                if citations:
                    st.markdown("Evidence: " + " · ".join(source_link(sid, run.sources) for sid in citations))
                else:
                    st.caption("No cited original attached to this finding; do not present it as verified.")
        else:
            st.info("No research highlights are available in this saved handoff.")
        with st.expander("Discovery questions for the account executive"):
            for question in handoff.get("discovery_questions", []):
                st.write("• " + question)
        section("SHARE THE WORK", "Export the real run", "No email is sent")
        downloads(run)
        st.caption("A readable handoff may still contain unresolved evidence limitations. Verify cited originals before outreach.")

elif page == "How It Works & Evidence":
    evidence_experience()
    section("04 / TRANSPARENCY", "An inspectable agent — not a single prompt",
            "Architecture, citations and honest limitations")
    paint('''<div class="fb-architecture" role="img" aria-label="Workflow architecture: inbound message, qualification, public research, evidence checks, response and routing, and account executive handoff">
    <span>INBOUND MESSAGE</span><i>→</i><span>QUALIFY</span><i>→</i><span>SEARCH & INSPECT</span><i>→</i>
    <span>CHECK EVIDENCE</span><i>→</i><span>RESPOND & ROUTE</span><i>→</i><span>AE HANDOFF</span></div>''')
    left, right = st.columns(2)
    with left:
        st.markdown("**Groq · structured reasoning**")
        st.write("Interprets the enquiry, drafts grounded responses, compares proof and recommends next actions. "
                 "Output schemas are validated locally.")
    with right:
        st.markdown("**Tavily · public-source retrieval**")
        st.write("Finds original public websites and documents. The workflow records what was actually inspected "
                 "and what was only shown in search results.")
    st.markdown("**Quality gates** — citation checks, conservative selection rules, cached checkpoints, "
                "explicit live approval, free-tier project ceilings and no automated email sending.")
    if run:
        limit_notice(run)
        source_tab, review_tab, record_tab = st.tabs(["Source library", "Evidence review", "Run record"])
        with source_tab:
            provenance_strip(run)
            source_catalogue(run)
        with review_tab:
            review = assess_run(run)
            for issue in review.get("blocking_review_items", []):
                st.write("• " + issue)
            st.caption("Offline review detects some structural problems; it cannot guarantee every factual statement.")
            st.download_button("↓ Export review notes", review_markdown(review),
                               file_name=f"{run.run_id}-review.md", mime="text/markdown", on_click="ignore")
        with record_tab:
            st.write(f"Run date: {run.as_of_date} · Status: {run.status} · Mode: {run.mode}")
            with st.expander("Source run ID and machine-readable configuration"):
                st.code(run.run_id)
                st.json({"run_id": run.run_id, "mode": run.mode, "status": run.status,
                         "stage_status": [s.status for s in run.stages]})
            downloads(run)
    else:
        st.info("Source evidence will appear as the live run reaches checkpoints." if busy else "Open a saved analysis to inspect the sources and audit trail.")

elif page == "Operator Tools":
    operator_experience(read_only=read_only)
    section("OPERATOR WORKSPACE", "Configuration and recovery", "Not part of the evaluator's sales overview")
    st.warning("This workspace controls optional provider calls. It is not required to review saved outputs.")
    with st.expander("Provider configuration and private project limits"):
        st.json({"keys_present": credential_status(), "project_budget": ProjectBudget(settings).summary(),
                 "model": settings.groq_model, "maximum_search_requests": settings.max_search_requests,
                 "maximum_extract_requests": settings.max_extract_requests})
        st.caption("Key presence does not verify live free-tier availability. Keys are not displayed.")
    with st.expander("Open another saved run", expanded=False):
        choose_run()
    with st.expander("New enquiry and live run", expanded=False):
        live_input()
    if run:
        checks = check_requirements(run)
        section("RECOVERY", "Outstanding steps", "Current saved evidence remains unchanged")
        next_steps_board(checks)
        with st.expander("Retry one incomplete step · provider approval required"):
            options = {"Research the company": 1, "Refresh case-study matching": 3,
                       "Review local partner options": 4, "Regenerate emails": 2,
                       "Rebuild sales handoff": 5}
            selected = st.selectbox("Stage to review", list(options), key="operator_retry_stage")
            index = options[selected]
            plan = plan_resume(run, settings, {index})
            st.json({"budget_feasible": plan.get("budget_feasible"),
                     "rerun_stages": plan.get("rerun_stages"),
                     "groq_tokens_estimated": plan.get("groq_tokens_estimated")})
            confirmed = st.checkbox("I understand this may consume my approved free-tier repair allowance")
            allowed = (not read_only and live_approved and confirmed and configured and not busy
                       and live_phase == "repair" and run.mode == "live" and plan.get("budget_feasible"))
            if st.button("Retry selected step", disabled=not allowed):
                launch_work(run.input, saved=run.model_copy(deep=True), stages={index})
                st.rerun()
        with st.expander("Hypothetical buyer update · optional AI usage"):
            update = st.text_area("Hypothetical buyer message", key="operator_followup_update")
            no_reply = st.checkbox("No reply after agreed interval", key="operator_no_reply")
            can_generate = (not read_only and live_approved and configured and not busy and live_phase == "repair"
                            and ledger["groq"].get("repair_remaining", 0) >= 3500 and (update.strip() or no_reply))
            if st.button("Generate conditional draft", disabled=not can_generate):
                try:
                    continued = fork_resume(run, settings)
                    st.session_state["approval_consumed"] = True
                    with approved_live_execution(live_approved, phase="repair"):
                        reply = simulate_followup(continued, settings, update, no_reply)
                    continued.followup_updates.append(reply)
                    save_run(continued, settings.run_path())
                    st.session_state.run = continued
                except Exception as error:
                    from flytbase_bdr.provider import ProviderError
                    st.error(str(error) if isinstance(error, ProviderError) else "The follow-up request failed.")
            for reply in run.followup_updates:
                st.markdown(render_value(reply, run.sources))
        with st.expander("Machine-readable execution trail"):
            st.json({"usage": run.usage, "logs": run.logs, "queries": run.queries, "warnings": run.warnings})
        st.markdown("**Protected input and status**")
        st.code(run.input, language="text")
        for item in run.stages:
            st.markdown(f"**{item.name}: {stage_status(item)}**")


if run and not busy and page in {"Command Center", "Account Intelligence", "Sales Strategy"}:
    section("EXPORT THIS EXECUTION", "Reports and source data", "Recorded results · zero API usage")
    downloads(run)

footer()
