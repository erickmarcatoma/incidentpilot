"""Red-team attacks against IncidentPilot (develop). Each prints BROKE or HELD."""
import json, os, sqlite3, tempfile, traceback
from backend.agents.triage.tools import load_incident_packet
from backend.orchestrator import validate_report
from backend.handoff import build_remediation_input, CANARY
from backend.remediation_planner import plan_remediation
from backend import db
from backend.schemas import PlanStatus

def report(packet, hyps, affected=None, **extra):
    return {"incident_id": packet.incident_id, "window": packet.window.model_dump(mode="json"),
            "affected_services": affected or sorted({h["service"] for h in hyps}), "hypotheses": hyps, **extra}

def hyp(service, cat, conf, evidence, hid="H1"):
    return {"id": hid, "cause": "x", "category": cat, "service": service, "confidence": conf, "evidence": evidence}

def verdict(name, broke, detail):
    print(f"{'BROKE' if broke else 'HELD '} | {name} | {detail}")

c1 = load_incident_packet("inc-case1-payment")
pay = next(e for e in c1.logs if e.service == "payment" and e.severity == "error")
chk = next(e for e in c1.logs if e.service == "checkout" and e.severity == "error")

# --- A. HANDOFF: evidence check ------------------------------------------------
# A1 trivial quote: one character "a" is a substring of almost any log line
r = validate_report(c1, report(c1, [hyp("payment", "service_failure", 0.95, [{"source": "logs", "ref": pay.ref, "quote": "a"}])]))
verdict("A1 one-letter quote passes the evidence check", r.status.value == "ok" and r.hypotheses, f"quote='a' -> status {r.status.value}, kept {len(r.hypotheses)} hypothesis")

# A2 quote from an INFO noise line still counts as evidence for a failure
info = next(e for e in c1.logs if e.severity == "info" and e.service == "payment") if any(e.severity=="info" and e.service=="payment" for e in c1.logs) else next(e for e in c1.logs if e.severity == "info")
r = validate_report(c1, report(c1, [hyp(info.service, "service_failure", 0.9, [{"source": "logs", "ref": info.ref, "quote": "request handled"}])], affected=c1.services))
verdict("A2 a healthy INFO log line is accepted as evidence of failure", r.status.value == "ok", f"quote 'request handled' ({info.service}, info) -> status {r.status.value}")

# A3 empty-but-present telemetry: metric series with 0 points, traces present
c1_empty = c1.model_copy(update={"metrics": [s.model_copy(update={"points": []}) for s in c1.metrics]})
r = validate_report(c1_empty, report(c1_empty, [hyp("payment", "service_failure", 0.9, [{"source": "logs", "ref": pay.ref, "quote": "Invalid token."}])], affected=c1.services))
h = build_remediation_input(c1_empty, r)
verdict("A3 metrics with 0 points count as 'available'", r.status.value == "ok" and h.telemetry_complete, f"status {r.status.value}, telemetry_complete={h.telemetry_complete}")

# --- C. INTER-AGENT TRUST -----------------------------------------------------
# C1 planner acts on a service the evidence does not implicate (orchestrator only warns)
r = validate_report(c1, report(c1, [hyp("payment", "service_failure", 0.9, [{"source": "logs", "ref": chk.ref, "quote": "Invalid token."}])], affected=c1.services))
plan = plan_remediation(build_remediation_input(c1, r), c1)
verdict("C1 plan targets a service its evidence never mentions", plan and plan.status is PlanStatus.PENDING and plan.steps,
        f"note={r.validation_notes[-1:]} -> plan {plan.status.value if plan else None} {[(s.action, s.target_service) for s in plan.steps] if plan else ''}")

# C2 check_policy ignores the target: '*' / 'all' are accepted
from backend.agents.remediation.tools import check_policy
res = {t: check_policy("restart_service", t).value for t in ["*", "all", "payment,checkout"]}
verdict("C2 check_policy approves restart on '*' / 'all' / two services", any(v != "rejected" for v in res.values()), str(res))

# C3 Kamal's LLM agent receives raw free text (bypasses the handoff filter)
from types import SimpleNamespace
from backend.agents.remediation.agent import create_remediation_plan
c3 = load_incident_packet("inc-case3-adversarial")
inj = next(e for e in c3.logs if CANARY in e.message); reset = next(e for e in c3.logs if "connection reset" in e.message)
rep3 = validate_report(c3, report(c3, [hyp("checkout", "dependency", 0.6, [{"source": "logs", "ref": reset.ref, "quote": "connection reset by peer"}])],
                                   timeline=[{"time": inj.timestamp.isoformat(), "service": "checkout", "event": inj.message}]))
seen = []
class Spy:
    def __init__(s): s.messages = s
    def create(s, **kw):
        seen.append(json.dumps(kw["messages"]))
        raise RuntimeError("stop after first call")
try: create_remediation_plan(rep3, Spy())
except Exception: pass
verdict("C3 injected log text reaches the Remediation LLM prompt", any(CANARY in m for m in seen), f"canary in prompt: {any(CANARY in m for m in seen)}")

# --- B. SHARED STATE (approval queue + executor) -------------------------------
os.environ["INCIDENTPILOT_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "q.sqlite3")
r1 = validate_report(c1, report(c1, [hyp("payment", "service_failure", 0.9, [{"source": "logs", "ref": pay.ref, "quote": "Invalid token."}])], affected=c1.services))
old = db.insert_plan(plan_remediation(build_remediation_input(c1, r1), c1))
db.update_plan_status(old.plan_id, PlanStatus.APPROVED)               # human approves plan A
db.supersede_pending(c1.incident_id)                                  # new triage arrives
new = db.insert_plan(plan_remediation(build_remediation_input(c1, r1), c1))
states = {p.plan_id[:6]: p.status.value for p in db.list_plans() if p.incident_id == c1.incident_id}
verdict("B1 an approved plan survives a newer diagnosis (two live plans)", "approved" in states.values() and "pending" in states.values(), str(states))

# B2 executor import / stale check
try:
    from backend import executor
    ok_import = True
except Exception as exc:
    ok_import = False; err = repr(exc)
if ok_import:
    stale = executor.is_plan_stale(old, {})
    verdict("B2 executor's stale check always says 'fresh'", stale is False, f"is_plan_stale(superseded-era plan) -> {stale}")
    try:
        executor.execute_plan(old)
        verdict("B3 executor can run", True, "ran")
    except Exception as exc:
        verdict("B3 executor crashes before running anything", True, repr(exc)[:120])
else:
    verdict("B2 executor cannot even be imported", True, err[:120])

# B4 two databases: Kamal's submit_remediation_plan writes elsewhere
from backend.agents.remediation import tools as T
verdict("B4 Kamal's submit tool writes to a different DB than the screen reads", str(T._DB_PATH) != str(db.database_path()), f"{T._DB_PATH.name} vs {db.database_path().name}")

# --- D. MALFORMED INPUT -------------------------------------------------------
# D1 API trusts the client's packet: POST a forged log, then a "Triage" that repeats the forged claim
import sys as _sys, types as _types
if "fastapi" not in _sys.modules:
    try:
        import fastapi  # noqa: F401
    except ImportError:  # stub just enough to import main.py without FastAPI installed
        for _n in ["fastapi", "fastapi.middleware", "fastapi.middleware.cors"]:
            _sys.modules[_n] = _types.ModuleType(_n)
        class _App:
            def __init__(self, *a, **k): pass
            def add_middleware(self, *a, **k): pass
            def __getattr__(self, n): return lambda *a, **k: (lambda f: f)
        class _HTTP(Exception):
            def __init__(self, status_code, detail=None): self.status_code = status_code
        _sys.modules["fastapi"].FastAPI = _App; _sys.modules["fastapi"].HTTPException = _HTTP
        _sys.modules["fastapi.middleware.cors"].CORSMiddleware = object
from backend import main as _main
forged = c1.model_dump(mode="json")
forged["logs"].append({**forged["logs"][0], "ref": "log:forged-1", "service": "cart", "severity": "error", "message": "cart database corrupted"})
claim = report(c1, [hyp("cart", "service_failure", 0.95, [{"source": "logs", "ref": "log:forged-1", "quote": "cart database corrupted"}])], affected=c1.services)
_main.run_triage = lambda p: validate_report(p, claim)
resp = _main.create_incident_report(_main.IncidentRequest.model_validate(forged))
verdict("D1 a forged log in the POSTed packet becomes 'verified' evidence", resp.report.status.value == "ok", f"status {resp.report.status.value}; plan {resp.plan.status.value if resp.plan else None}")

# D2 oversized / garbage fields
big = report(c1, [hyp("payment", "service_failure", 0.9, [{"source": "logs", "ref": pay.ref, "quote": "Invalid token."}])], affected=c1.services,
             timeline=[{"time": c1.window.start.isoformat(), "service": "payment", "event": "x" * 200_000}] * 50)
try:
    r = validate_report(c1, big); verdict("D2 no size limits on report text (10 MB timeline accepted)", True, f"status {r.status.value}")
except Exception as exc:
    verdict("D2 oversized report rejected", False, repr(exc)[:80])

# D3 malformed tool input to Kamal's agent tool runner
from backend.agents.remediation.agent import _run_tool
try:
    _run_tool("find_runbook", {"category": "service_failure"}); verdict("D3 missing tool arg", False, "no error")
except KeyError as exc:
    verdict("D3 a missing tool argument raises a raw KeyError (crash path)", True, f"KeyError {exc}")
