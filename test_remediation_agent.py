"""Test the remediation agent with the case 1 fixture."""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from backend.agents.remediation.agent import create_remediation_plan
from backend.schemas import RootCauseReport

# Load case 1 fixture
fixture_path = Path("fixtures/case1.json")
with fixture_path.open() as f:
    report_data = json.load(f)

print(f"Loading fixture: {fixture_path}")
print(f"Report data: {json.dumps(report_data, indent=2)}")

report = RootCauseReport.model_validate(report_data)
print(f"\nValidated report: status={report.status}, hypotheses={len(report.hypotheses)}")

print("\nRunning remediation agent...")
try:
    plan = create_remediation_plan(report)
    print(f"\n✅ SUCCESS!")
    print(f"Plan ID: {plan.plan_id}")
    print(f"Status: {plan.status}")
    print(f"Steps: {len(plan.steps)}")
    for step in plan.steps:
        print(f"  - {step.action} on {step.target_service} ({step.policy_result})")
    print(f"Runbook: {plan.runbook}")
    print(f"Recovery check: {plan.recovery_check}")
except Exception as e:
    print(f"\n❌ FAILED: {e}")
    import traceback
    traceback.print_exc()