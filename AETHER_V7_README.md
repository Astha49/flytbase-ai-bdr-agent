# AETHER v7 — Persistent sidebar access

Fixed the missing sidebar reopen control. The app now retains Streamlit's native sidebar header controls, and provides a dedicated AETHER navigation toggle (☰ / ‹) fixed to the upper-left of the page. The toggle follows the expanded sidebar edge and remains visible when the sidebar is collapsed. This does not alter the workflow engine, results, or provider usage.

## Start
Run `powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1` from the extracted project folder and browse to `http://localhost:8506`.

## Verify in the browser
1. Open Overview and click the `‹` button at the upper-right edge of the sidebar to collapse it.
2. Click the `☰` button at the upper-left of the content to reopen it.
3. Navigate to another page, repeat, and verify the sidebar remains usable.

This version uses port 8506 so it can run alongside v6 on port 8505.
