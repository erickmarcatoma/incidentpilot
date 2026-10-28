# IncidentPilot — Build Plan

**Code deadline:** Thursday, October 29, 2026 · **Presentation:** Monday, November 2, 2026 · **Class days:** Mon–Thu · **Team:** Erick Marcatoma, Kamal Mohamed

**Goal:** an alert goes in, a validated Root-Cause Report and a policy-checked plan come out, and a person approves the plan on the approval screen. Nothing runs without approval.

## Status (Wednesday, October 28)

- **Triage side: done.** Triage Agent, orchestrator, handoff filter, evals (5/5 corrupted reports caught), API and approval screen are on `develop`.
- **Remediation side: blocked.** Runbooks, policy, tools and a basic executor are on `remediation-agent`, not merged. The Remediation Agent (`agent.py`) is empty; last push Oct 24.
- **Gate not passed:** no plans reach the approval screen yet.
- **Decision at 5 pm today:** if the Remediation Agent isn't pushed, build the rule-based fallback planner so plans work before the code deadline.

## Who owns what

| Area | Owner | Folder |
| :---- | :---- | :---- |
| Triage & Log Agent \+ test scenarios | Erick | `backend/agents/triage/`, `fixtures/` |
| Remediation Agent \+ runbooks, policy, executor | Kamal | `backend/agents/remediation/`, `knowledge/`, `backend/executor.py` |
| Schemas, orchestrator, API | Together | `backend/schemas.py`, `backend/orchestrator.py`, `backend/main.py` |
| Approval screen | Together (pair) | `frontend/` |
| Evals \+ demo | Together | `evals/` |

## How we work

- **Branches:** `triage-agent` and `remediation-agent` → `develop` (testing) → `main`. Nobody pushes straight to `main`.  
- **Pull requests:** the other person reviews and merges. Tests must pass.  
- **Contracts first:** `schemas.py` and the API are agreed together. Whoever changes them tells the other person the same day.  
- **Fixtures only:** both agents run on the 3 hand-built incidents in `fixtures/`, served by `mock_server/`. We do not run the OpenTelemetry Demo.  
- **Daily check-in (10 min, start of class):** what I finished, what I'm doing today, and what's blocking me.  
- **Frontend pairing:** one person drives and the other reviews, swapping every 45 minutes.

## Schedule

### Thu Oct 22: contrast & tools

- [x] **Together:** lock `schemas.py` (IncidentPacket, RootCauseReport, RemediationPlan) and the API endpoints
- [x] **Together:** repo skeleton, branches, README  
- [x] ~~**Erick:** start the OpenTelemetry Demo locally~~ Replaced by the mock telemetry server and hand-built fixtures (the demo needs more memory than our laptops have)
- [x] **Erick:** draft the Triage prompt v0
- [x] **Kamal:** write 2 runbooks (payment failure, memory leak) and `allowed-actions.yaml` (on `remediation-agent`, not merged)
- [x] **Erick:** `get_metrics`, `search_logs` and `get_traces` in fixture mode
- [x] **Erick:** record 3 incident packets into `fixtures/`
- [x] **Kamal:** `find_runbook`, `check_policy` and `submit_remediation_plan` (SQLite) (on `remediation-agent`, not merged; `find_runbook` returns the wrong section)  
- [ ] **Kamal:** hand-write a valid sample RootCauseReport for case 1 (file is empty; gold reports for all 3 cases are in `evals/reference/`)  
- [x] **Together:** orchestrator validator (structure, consistency, evidence, status) \+ unit tests

### Fri–Sun Oct 23–25: optional

- [x] **Erick:** Triage tool-use loop  
- [ ] **Kamal:** Remediation tool-use loop

### Mon Oct 26: agents work alone

- [x] **Erick:** Triage agent returns a valid report for case 1
- [ ] **Kamal:** Remediation agent returns a valid plan from the sample report (`agent.py` is empty)  
- [x] **Together:** FastAPI endpoints \+ frontend scaffold

### Tue Oct 27: join everything (gate)

- [x] **Erick:** Triage on cases 2 and 3; one retry; 90-second timeout  
- [ ] **Kamal:** executor (allow-list, one service), recovery check, stale-plan check before running (partly: allow-list and one service done; recovery and stale checks are placeholders)  
- [x] **Together:** approval screen: queue, plan detail, approve / reject  
- [ ] **Gate:** case 1 goes from alert to a plan on the approval screen (blocked: no plans yet)

### Wed Oct 28: evals \+ freeze

- [x] **Erick:** eval runner \+ metrics; corrupted-report tests (fake log line, deleted evidence, swapped incident\_id)  
- [ ] **Kamal:** `uncertain` and `needs_human` plans; edit flow; one active plan per incident  
- [x] **Together:** fix eval failures: handoff filter (no free text reaches Remediation) and blamed-service evidence check
- [ ] **Together:** **code freeze at end of day** (merge `develop` into `main`)

### Thu Oct 29: deliver

- [ ] **Together:** rerun the evals 3 times and record results against the targets  
- [ ] **Together:** rehearse the demo twice

## Definition of done

- [ ] Eval cases 1–3 end on their expected path  
- [x] Every corrupted report takes its PRD 3e path (5/5)  
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
| OTel Demo won't run on our laptops | Happened: 8 GB RAM is not enough | Done: hand-built fixtures + mock telemetry server |
| Agents disagree on the schema | Validator fails on real output Mon 26 | Fix `schemas.py` together that day |
| LLM output varies between runs | Eval results differ across runs | Tighten prompts; report the pass rate honestly |
