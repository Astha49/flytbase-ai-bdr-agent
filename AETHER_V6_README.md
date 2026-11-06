# AETHER v6 · Usability and performance repair

This version retains the working v5 Python backend and its protected new-enquiry page.

## Fixes
- Heading anchor icons are hidden. Actual public source links remain visible.
- Outreach email iframe uses a Streamlit resize message and a scrollable fallback, including after Edit is clicked.
- Sidebar top whitespace is reduced.
- Saved run JSON is parsed once per file version via an imported LRU cache, rather than on every navigation action.

## New enquiry: what is and is not verified
The form takes the new pasted buyer email, `execute_enquiry` creates a `new_run` from that email, and the real Python `Workflow.execute` runs all six stages. The new email is SHA256-bound to a new allowance, and the original project saves its run JSON. This is real workflow code, not a SQM replay. However, provider-dependent research quality for a new company has **not been live-tested** in this release; results may be partial, especially where public sources are missing. It is designed for *FlytBase sales inquiries*, not arbitrary general-purpose tasks.

Execution requires valid Free Groq and Tavily credentials, sufficient quota, a local original project/ledger, and separate budget/launch approvals.

## Starting
Extract next to `Flytbase-inbound-agent`, open this folder in VS Code, and run `powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1`. Visit http://localhost:8505.

## Release verification
Python compile, backend budget tests, six-page replay, and editor/anchor/cache source assertions have been performed offline. Browser-level interaction and live provider calls require local verification.
