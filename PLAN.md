# IncidentPilot — Build Plan

**Deadline:** Thursday, October 29, 2026 · **Class days:** Mon–Thu · **Team:** Erick Marcatoma, Kamal Mohamed

**Goal:** an alert goes in, a validated Root-Cause Report and a policy-checked plan come out, and a person approves the plan on the approval screen. Nothing runs without approval.

## Who owns what

| Area | Owner | Folder |
| :---- | :---- | :---- |
| Triage & Log Agent \+ test scenarios | Erick | `backend/agents/triage/`, `fixtures/` |
| Remediation Agent \+ runbooks, policy, executor | Kamal | `backend/agents/remediation/`, `knowledge/`, `backend/executor.py` |
| Schemas, orchestrator, API | Together | `backend/schemas.py`, `backend/orchestrator.py`, `backend/main.py` |
| Approval screen | Together (pair) | `frontend/` |
| Evals \+ demo | Together | `evals/` |

## How we work

- **Branches:** `triage-agent`, `remediation-agent` and `frontend`. Nobody pushes straight to `main`.  
- **Pull requests:** the other person reviews and merges. Tests must pass.  
- **Contracts first:** `schemas.py` and the API are agreed together. Whoever changes them tells the other person the same day.  
- **Fixtures first:** both agents run on the recorded incidents in `fixtures/` before touching the live stack, so neither of us blocks the other.  
- **Daily check-in (10 min, start of class):** what I finished, what I'm doing today, and what's blocking me.  
- **Frontend pairing:** one person drives and the other reviews, swapping every 45 minutes.

## Schedule

### Thu Oct 22: contrast & tools

- [x] **Together:** lock `schemas.py` (IncidentPacket, RootCauseReport, RemediationPlan) and the API endpoints
- [ ] **Together:** repo skeleton, branches, README  
- [ ] **Erick:** start the OpenTelemetry Demo locally
- [x] **Erick:** draft the Triage prompt v0
- [ ] **Kamal:** write 2 runbooks (payment failure, memory leak) and `allowed-actions.yaml`
- [x] **Erick:** `get_metrics`, `search_logs` and `get_traces` in fixture mode
- [x] **Erick:** record 3 incident packets into `fixtures/`
- [ ] **Kamal:** `find_runbook`, `check_policy` and `submit_remediation_plan` (SQLite)  
- [ ] **Kamal:** hand-write a valid sample RootCauseReport for case 1  
- [x] **Together:** orchestrator validator (structure, consistency, evidence, status) \+ unit tests

### Fri–Sun Oct 23–25: optional

- [ ] **Erick:** Triage tool-use loop  
- [ ] **Kamal:** Remediation tool-use loop

### Mon Oct 26: agents work alone

- [x] **Erick:** Triage agent returns a valid report for case 1
- [ ] **Kamal:** Remediation agent returns a valid plan from the sample report  
- [x] **Together:** FastAPI endpoints \+ frontend scaffold

### Tue Oct 27: join everything (gate)

- [ ] **Erick:** Triage on cases 2 and 3; one retry; 90-second timeout  
- [ ] **Kamal:** executor (allow-list, one service), recovery check, stale-plan check before running  
- [ ] **Together:** approval screen: queue, plan detail, approve / reject  
- [ ] **Gate:** case 1 goes from alert to a plan on the approval screen

### Wed Oct 28: evals \+ freeze

- [ ] **Erick:** eval runner \+ metrics; corrupted-report tests (fake log line, deleted evidence, swapped incident\_id)  
- [ ] **Kamal:** `uncertain` and `needs_human` plans; edit flow; one active plan per incident  
- [ ] **Together:** fix eval failures; **code freeze at end of day**

### Thu Oct 29: deliver

- [ ] **Together:** rerun the evals 3 times and record results against the targets  
- [ ] **Together:** rehearse the demo twice, then present

## Definition of done

- [ ] Eval cases 1–3 end on their expected path  
- [ ] Every corrupted report takes its PRD 3e path  
- [ ] Every PRD metric has a measured number next to its target  
- [ ] 0 actions run without an approval  
- [ ] README setup steps work on a fresh clone

## If we fall behind

If the Tuesday gate slips, cut in this order:

1. The Edit action (keep Approve and Reject)  
2. The live executor (show a "would run" result instead)  
3. Case 2's side-by-side H1/H2 view (keep the Uncertain label)

**Never cut:** the evidence check, status labels, case 3, or human approval.

## Risks

| Risk | Early sign | Fallback |
| :---- | :---- | :---- |
| OTel Demo won't run on our laptops | Not up by end of Thu 22 | Demo from fixtures only |
| Agents disagree on the schema | Validator fails on real output Mon 26 | Fix `schemas.py` together that day |
| LLM output varies between runs | Eval results differ across runs | Tighten prompts; report the pass rate honestly |
