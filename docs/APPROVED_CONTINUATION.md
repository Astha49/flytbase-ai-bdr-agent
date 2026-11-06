# Protected cache-only live continuation

Nothing on this page has been executed against live providers. Budget approval and launch approval are **two different actions**. The application defaults to read-only. Do not run approval or execution commands until the owner explicitly authorizes that step.

## Read-only preparation

For the owner's existing workspace:

```powershell
Set-Location 'F:\Downloads\Flytbase-inbound-agent'
$sourceRun = '.\runs\20261105T195016_6b3a6fb0d3\run.json'
.\.venv\Scripts\python.exe -X utf8 -B -m flytbase_bdr.run_allowance plan --source $sourceRun
```

This reads source records and accounting only. It makes no API requests, creates no allowance, reserves nothing and does not edit history. A public source checkout has no private execution to continue: use its labelled fictional example for zero-credit review instead.

The plan reuses qualification and five inspected research caches; it regenerates research, case comparison, partner advice, five drafts and audits, then rebuilds the AE handoff. Structured model-response caches are not presented as new AI output. Source inspection timestamps remain old; there is no claim of fresh research. The new execution uses the actual run date and a new ID. Old results and usage remain in their original records.

The comparable recorded workload suggests **63,000 combined Groq tokens including a 20% planning reserve**, not a guarantee of consumption or success. The new allowance has a firm cap, 24 Groq attempts, zero automatic retries and **zero Tavily requests, including quota probes**. Scheduling reserves estimated input plus output and uses the existing rolling window, at most 8,000 TPM with a 10% margin and at most 25 RPM. Task-specific completion targets and schema floors stay enforced. Provider response limits can further restrict requests; nothing bypasses them.

## Separate budget approval — only after permission

The owner must check the current Groq Free dashboard and confirm paid billing is disabled. A published 200,000 TPD limit is **not** a remaining balance. Enter actual usage for the provider's current daily quota window, including work outside this application. The UTC day in local accounting is a planning period, not proof the provider reset its quota.

After the owner authorizes a new budget, and immediately after checking the dashboard:

```powershell
$tokensUsedToday = [int](Read-Host 'Groq tokens used in the current provider daily window')
$checkedAt = (Get-Date).ToUniversalTime().ToString('o')
.\.venv\Scripts\python.exe -X utf8 -B -m flytbase_bdr.run_allowance approve --source $sourceRun --tokens 63000 --used-today $tokensUsedToday --checked-at $checkedAt --approve-budget --confirm-free-only
```

Approval is local only and spends no API tokens. It appends a record under `execution_allowances`, preserving entries, old cumulative ceilings, demo history and protected reserves. It is not a fifth demo envelope. The checks use the greater of local counted usage and the attested dashboard usage plus later local reservations, add other pending approvals, and retain emergency/demo headroom. An exhausted cumulative legacy allowance does not masquerade as exhausted daily quota or get reset to create headroom.

With the existing default reserves, 63,000 tokens require at least 108,759 tokens of conservative daily headroom. Other pending reservations may increase that requirement. If unavailable, approval fails without changing the ledger. Unknown usage stays reserved. Dashboard attestations are operator-provided, not independently verified account balances. No API endpoint in this app can prove Groq's billing-plan status.

## Separate launch approval — only after permission

Copy the returned allowance ID (it begins `run-`). It is bound to the source SHA-256 and cannot be applied to another source or run. Approval must be used on the same UTC day, with a dashboard observation less than 15 minutes old when starting.

```powershell
$allowanceId = Read-Host 'Approved allowance ID'
.\.venv\Scripts\python.exe -X utf8 -B -m flytbase_bdr.run_allowance execute --allowance $allowanceId --approve-live
```

Alternatively, in Streamlit select **Protected live execution**, explicitly approve provider requests in the sidebar, then open **Plan a zero-Tavily continuation** in Command Center, select the approved allowance and press **Run approved cached continuation** once. The allowance's bound source is authoritative; it may differ from the viewed saved run. No budget approval is inferred from an input field or checkbox.

Duplicate launches, wrong/changed source records, expired approvals, request/token exhaustion, and insufficient conservative daily headroom stop execution. The provider may still refuse a request; with zero retries the application preserves the new partial/failed result and reports it. Early wrapper failures are saved as failed instead of remaining forever running. The one-run record closes on exit and is never automatically replenished.

To cancel a never-started stale approval, only after deciding to cancel it:

```powershell
.\.venv\Scripts\python.exe -m flytbase_bdr.run_allowance cancel --allowance $allowanceId --confirm-cancel
```

This retains its audit record. Started usage/reservations are never removed or refunded by cancellation. A later approval needs a new explicit decision and a fresh dashboard observation.

## Inspection before recording

Inspect every new stage, quotation, financial scope/date/currency, case match and commodity/site limit, partner capability/country/availability distinction, five draft triggers and AE brief. Download JSON, complete Markdown and AE handoff. Partial evidence stays partial; candid unknowns do not justify inventing three findings. No email is sent. Only after this inspected continuation is satisfactory should a fresh recording execution be separately planned. Never label cached research, saved replay or fictional fixtures as newly researched facts.
