# AETHER v4 — Human-first FlytBase intelligence workspace

## Launch on Windows

1. Extract the ZIP so the folder is `F:\Downloads\AETHER-FlytBase-v4`, alongside the existing `F:\Downloads\Flytbase-inbound-agent` source project.
2. Open **AETHER-FlytBase-v4** in a new VS Code window.
3. In its PowerShell terminal run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1
   ```

4. Open **http://localhost:8503** (the port differs from the earlier AETHER v2 interface on 8502).
5. In **ACTIVE ANALYSIS**, choose the latest **LIVE** saved run. The app auto-detects the original project's `runs` folder. Otherwise, enter its exact path under **Load saved executions**.

## Changes requested after screenshots

- **Case study decision**: readable title, evidence outcome, matched considerations, research context, rejection reasons, limitations, and official source link. No printed JSON object in AE handoff.
- **Evidence & audit**: 32+ raw technical notices are grouped into human-readable topics, with what they mean, a suggested next step, and source links where their source IDs match inspected registered sources. Original notes remain available in expandable details.
- **Sidebar scroll**: a viewport-height, independently scrollable sidebar with visible scrollbar, improved selected-state hover, and a prominent **Run new analysis** link at the top.
- **Page scroll**: a revision-forced navigation handler resets the main scroll after switching pages and analyses. Uses the Streamlit parent scroll hosts and repeated post-render resets.
- **Cursor + visual feel**: blue/cyan trailing pointer aura, subtle glowing point on interactive elements, motion-sensitive fallback, animated brand icon and selected navigation sweep.
- **New analysis**: available at the top of the sidebar and main view. It opens **http://localhost:8501**, the existing source project's protected six-stage live workflow. This read-only reviewer does not issue Groq/Tavily calls itself.

## Source boundaries and submission

The bundled fixture is clearly marked as an offline simulation. Real outputs and source records remain in your original project's `runs/` directory and are not altered. The interface never substitutes fake research or quietly approves failed evidence gates. It does not change the Groq ledger or start new requests.

The actual FlytBase assignment additionally requires inspectable workflow source, genuine six-stage live run output, and an 8–12 minute walkthrough; include those original deliverables when submitting.

## Checks

- Python syntax: passed
- Offline mock Streamlit replay across six pages: passed using the saved real run and synthetic fixture
- Case decision and grouped warnings data tests: passed
- Live browser verification on your Windows machine: still required (Streamlit was not installed in this build container)
