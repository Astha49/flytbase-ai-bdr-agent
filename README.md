# AETHER / FlytBase — Inbound BDR Intelligence v7

A dark, information-first interface to the genuine six-stage FlytBase inbound agent.

**Quick start (Windows / PowerShell)**:

```powershell
powershell -ExecutionPolicy Bypass -File .\START_AETHER.ps1
```

Open <http://localhost:8506> and choose **New analysis** to process a new buyer inquiry. The in-app form connects to the original FlytBase project's Python workflow and provider ledger. Approve a free-only budget separately from authorizing a live run.

The v6 release removes distracting heading anchors, repairs email-editor clipping, trims sidebar padding and caches saved execution reads for faster page switches. See [AETHER_V6_README.md](AETHER_V6_README.md).

**Known limitations:** The new-enquiry path is source-code connected and tested offline but has not been live verified for a second company. Streamlit reruns and remote source lookups may still take time. The app is a sales workflow for FlytBase prospects, not a general-purpose search engine. No customer messages are automatically sent.

**v7 sidebar fix:** a persistent accessible navigation toggle (`☰`/`‹`) is present even when the Streamlit sidebar is collapsed. See [AETHER_V7_README.md](AETHER_V7_README.md).
