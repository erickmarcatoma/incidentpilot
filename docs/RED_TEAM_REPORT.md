# IncidentPilot: Red-Team Report

**Tested:** `develop` at `92ee01b` (Thursday, October 29, 2026)
**Method:** malformed and adversarial input fed straight to each component (orchestrator, handoff, planner, Remediation agent, approval queue, executor). Script: `redteam/attacks.py` (prints BROKE or HELD for each attack).
**Result:** 13 attacks, 13 broke something. **A1, D1, A3, C1 and B1 are fixed** (Thursday, October 29); rerun `python redteam/attacks.py` to see the current state. Nothing reached production, because no executor path can run today, but several breaks would let a wrong plan reach the approval screen labeled as trustworthy.

## Summary

| # | Surface | What broke | Severity | Status |
| --- | --- | --- | --- | --- |
| A1 | Handoff (evidence check) | A one-letter quote (`"a"`) passes as verified evidence | **Critical** | ✅ Fixed |
| D1 | Handoff (input trust) | A forged log in the POSTed packet becomes "verified" evidence | **Critical** | ✅ Fixed |
| C1 | Inter-agent trust | The planner acts on a service its evidence never mentions | **High** | ✅ Fixed |
| C2 | Inter-agent trust (policy) | `check_policy` approves `restart_service` on `*`, `all`, or two services | **High** | Open |
| C3 | Inter-agent trust (LLM) | Injected log text reaches the Remediation LLM's prompt | **High** | Open |
| B1 | Shared state (queue) | An approved plan survives a newer diagnosis: two live plans | **High** | ✅ Fixed |
| B2 | Shared state (executor) | The stale-plan check always says "fresh" | **High** | Open |
| A2 | Handoff (evidence check) | A healthy INFO log is accepted as evidence of failure | Medium | Open |
| A3 | Handoff (completeness) | Metrics with 0 points count as "available" | Medium | ✅ Fixed |
| B3 | Shared state (executor) | The executor can't even import (`get_connection` missing) | Medium | Open |
| B4 | Shared state (two DBs) | Kamal's submit tool writes to `approvals.db`; the screen reads `incidentpilot.sqlite3` | Medium | Open |
| D2 | Malformed input | No size limits: a 10 MB timeline is accepted | Low | Open |
| D3 | Malformed input | A missing tool argument crashes the agent loop (`KeyError`) | Low | Open |

## Findings

### A1 · One-letter quotes pass the evidence check (Critical) · ✅ Fixed
- **Fixed:** log and trace quotes need ≥ 12 characters and ≥ 2 words; a metric quote must be an exact value from that series (`orchestrator._quote_problem`). Tests in `test_orchestrator.py`; added to the corrupted-report evals.
- **Trigger:** a hypothesis with evidence `{"ref": "<real payment log>", "quote": "a"}`.
- **Result:** status `ok`; the hypothesis is kept.
- **Why:** `orchestrator.py` checks `quote in source_text`. Any substring counts, even one letter. The PRD's "every claim backed by a quoted log line" is not enforced.
- **Fix:** require a minimum quote length (e.g. ≥ 12 characters and ≥ 2 words), or match whole log messages and metric values only.

### D1 · The API trusts the client's incident packet (Critical) · ✅ Fixed
- **Fixed:** `POST /api/incidents` takes only `incident_id` and loads the packet server-side; an unknown id is a 404. Tests in `test_main.py`.
- **Trigger:** POST a packet with an extra log `"cart database corrupted"`, then a report that quotes it.
- **Result:** status `ok`, and H1 = cart, "verified".
- **Why:** `POST /api/incidents` validates evidence against the packet the **caller sent**, while the Triage tools read the fixture from disk. Evidence can be forged by whoever calls the API.
- **Fix:** take only `incident_id` in the request and load the packet server-side (`load_incident_packet`). Never validate against client-supplied telemetry.

### C1 · The planner acts on a service the evidence doesn't implicate (High) · ✅ Fixed
- **Fixed:** the handoff carries `h1_evidence_matches_service`, computed by code. When it's false, the planner returns `needs_human`. Test in `test_remediation_planner.py`.
- **Trigger:** H1 blames `payment`, but its only quote is from a `checkout` log.
- **Result:** the orchestrator notes "H1 blames payment, but none of its evidence comes from payment", yet the planner still makes a **pending** plan to toggle a flag on payment.
- **Why:** the note only downgrades the status to `uncertain`, and uncertain plans are allowed.
- **Fix:** carry a structured flag in the handoff (`h1_evidence_matches_service: bool`), and make the planner return `needs_human` when it's false.

### C2 · Policy approves any target (High)
- **Trigger:** `check_policy("restart_service", "*")`, `"all"`, or `"payment,checkout"`.
- **Result:** `requires_approval` every time.
- **Why:** `check_policy` reads `max_scope` but never checks the target string.
- **Fix:** reject any target that isn't a single known service name (`^[a-z][a-z0-9-]*$` and in the incident's services).

### C3 · Injected text reaches the Remediation LLM (High)
- **Trigger:** case 3 with the injected log line in the report timeline.
- **Result:** the canary appears in the prompt sent by `remediation/agent.py`.
- **Why:** `create_remediation_plan` sends `report.model_dump_json()` instead of the filtered handoff.
- **Fix:** pass `build_remediation_input(packet, report)`, as the planner does. `test_handoff.py` already proves the filter works.

### B1 · An approved plan survives a newer diagnosis (High) · ✅ Fixed
- **Fixed:** a newer diagnosis supersedes undecided plans and marks approved-but-not-run plans `stale`. A stale plan can't be approved again (`db.RETIRE_ON_NEW_DIAGNOSIS`). Test in `test_remediation_planner.py`.
- **Trigger:** approve plan A, then run triage again for the same incident.
- **Result:** plan A stays `approved` and plan B is `pending`, so there are two live decisions for one incident.
- **Why:** `supersede_pending()` only touches `pending` and `needs_human` plans.
- **Fix:** also mark `approved`-but-not-executed plans as `stale` when a newer report arrives. The executor must refuse `stale` (see B2).

### B2 · The stale check is a placeholder (High)
- **Trigger:** `executor.is_plan_stale(any_plan, {})`.
- **Result:** always `False`.
- **Fix:** stale if a newer plan exists for the incident, or if `based_on_report_at` is older than the latest report.

### A2 · Healthy log lines count as evidence (Medium)
- **Trigger:** quote `"request handled"` from an `info` log as evidence of a service failure.
- **Result:** status `ok`.
- **Fix:** for failure categories, require at least one `warning` or `error` log, or an anomalous metric.

### A3 · Empty metric series count as available (Medium) · ✅ Fixed
- **Fixed:** `IncidentPacket.missing_sources()` counts a source only if it has data inside the incident window. Used by both the orchestrator and the handoff. Tests in `test_remediation_planner.py`.
- **Trigger:** every metric series with `points: []`.
- **Result:** status `ok`, and `telemetry_complete = true`.
- **Fix:** a source counts as present only if it has data points inside the incident window.

### B3 · The executor can't import (Medium)
- **Trigger:** `from backend import executor`, then `execute_plan(...)`.
- **Result:** `ImportError: cannot import name 'get_connection'`.
- **Fix:** use `db.get_plan()` and `db.update_plan_status()`. Run only the **stored, approved** plan's steps, never the steps passed in.

### B4 · Two approval databases (Medium)
- Kamal's `submit_remediation_plan` writes to `approvals.db` (columns in a different order), and the API reads `backend/incidentpilot.sqlite3`. Plans from his agent would never show on screen.
- **Fix:** make `submit_remediation_plan` call `db.insert_plan()`.

### D2 · No size limits (Low)
- A 10 MB timeline is accepted.
- **Fix:** `max_length` on timeline, unknowns and text fields in `schemas.py`.

### D3 · A raw `KeyError` from tool input (Low)
- `_run_tool("find_runbook", {"category": ...})` raises `KeyError: 'service'`.
- **Fix:** validate tool input and return an error `tool_result` instead of crashing.

## Top recommendation

**Fix A1 and D1 first.** Every other safety guarantee (status labels, the planner, the approval screen) rests on "the evidence is real". Today evidence can be one letter, or come from a packet the caller made up. With those two fixed, the green "Verified" badge actually means verified.

## What held

- The schema rejected extra fields and unknown categories in every report.
- The handoff filter kept every injected text out of the planner (canary test).
- A `needs_human` plan cannot be approved; the queue only moves `pending` plans.
- The planner never proposed a step outside the matched runbook or on a second service.
