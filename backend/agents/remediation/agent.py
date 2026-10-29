"""Anthropic-backed remediation agent."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from backend.agents.remediation.tools import (
    check_policy as _check_policy,
    find_runbook,
    submit_remediation_plan,
)
from backend.schemas import DiagnosisStatus, PlanStatus, RemediationPlan, RootCauseReport

_PROMPT_PATH = Path(__file__).with_name("prompt.md")
_MAX_TOOL_ROUNDS = 4
_TOTAL_TIMEOUT_SECONDS = 90
_DEFAULT_MODEL = "claude-sonnet-5-5"

_TOOLS: list[dict[str, object]] = [
    {
        "name": "find_runbook",
        "description": "Find the runbook that matches a root-cause category and service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Root-cause category",
                },
                "service": {"type": "string", "description": "The affected service name"},
            },
            "required": ["category", "service"],
        },
    },
    {
        "name": "check_policy",
        "description": "Check whether a proposed action is allowed for a target service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "The action"},
                "target_service": {"type": "string", "description": "The service"},
            },
            "required": ["action", "target_service"],
        },
    },
]


class RemediationConfigurationError(RuntimeError):
    """Raised when the agent cannot be configured to call Anthropic."""


class RemediationAgentError(RuntimeError):
    """Raised when the model does not produce a usable remediation plan."""


def _run_tool(tool_name: str, tool_input: dict[str, object]) -> object:
    if tool_name == "find_runbook":
        return find_runbook(str(tool_input["category"]), str(tool_input["service"]))
    if tool_name == "check_policy":
        return _check_policy(str(tool_input["action"]), str(tool_input["target_service"]))
    raise RemediationAgentError(f"Unsupported tool {tool_name!r}")


def _extract_json(text: str | None) -> str:
    if not text or not text.strip():
        raise ValueError("Remediation agent did not return JSON")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Remediation reply contained no JSON object")
    return text[start : end + 1]


def create_remediation_plan(
    report: RootCauseReport | dict,
    client: Any | None = None,
) -> RemediationPlan:
    """Turn a validated Root-Cause Report into a RemediationPlan via the Anthropic model."""
    if isinstance(report, dict):
        report = RootCauseReport.model_validate(report)

    if client is None:
        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RemediationConfigurationError(
                "ANTHROPIC_API_KEY is required to run the Remediation agent"
            )
        client = Anthropic(api_key=api_key, timeout=90.0)

    system_prompt = _PROMPT_PATH.read_text()ncoding="utf-8")

    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": (
                "Create a remediation plan from this Root-Cause Report. "
                "Return one JSON object matching RemediationPlan:\n"
                f"{report.model_dump_json()}"
            ),
        }
    ]

    tool_rounds = 0
    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RemediationAgentError(
                f"Remediation exceeded the {_TOTAL_TIMEOUT_SECONDS}-second limit"
            )

        tool_rounds += 1
        if tool_rounds > _MAX_TOOL_ROUNDS:
            raise RemediationAgentError("Too many tool rounds without a final plan")

        response = client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
            tools=_TOOLS,
        )

        tool_uses: list[dict[str, object]] = []
        text_parts: list[str] = []
        for block in response.content:
            block_type = getattr(block, "type", None) or block.get("type", "")
            if block_type == "tool_use":
                tool_uses.append(getattr(block, "model_dump", lambda: block)())
            elif block_type == "text":
                text = getattr(block, "text", None) or block.get("text", "")
                text_parts.append(text)

        if tool_uses:
            tool_results = []
            for block in tool_uses:
                tool_id = block.get("id", "")
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                try:
                    result = _run_tool(tool_name, tool_input)
                except Exception as exc:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Error: {exc}",
                        }
                    )
                    continue
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result.model_dump_json()
                        if hasattr(result, "model_dump_json")
                        else json.dumps(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        final_text = "\n".join(text_parts)
        if not final_text.strip():
            raise RemediationAgentError("Remediation agent returned no response")

        try:
            plan_json = json.loads(_extract_json(final_text))
        except (ValueError, json.JSONDecodeError) as exc:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "retry",
                            "content": f"Invalid JSON: {exc}. Return valid RemediationPlan JSON only.",
                        }
                    ],
                }
            )
            continue

        plan = RemediationPlan.model_validate(plan_json)
        plan.incident_id = report.incident_id
        plan.based_on_report_at = datetime.now(timezone.utc)
        plan.created_at = datetime.now(timezone.utc)

        # Needs human for insufficient evidence or failed diagnosis
        if report.status in (DiagnosisStatus.INSUFFICIENT_EVIDENCE, DiagnosisStatus.FAILED):
            if plan.status is PlanStatus.PENDING:
                plan.status = PlanStatus.NEEDS_HUMAN
                plan.reason = f"Diagnosis status {report.status.value} requires human review"

        # Validate recovery check and runbook for PENDING plans
        if plan.status is PlanStatus.PENDING:
            if not plan.recovery_check:
                raise RemediationAgentError("A pending plan must include a recovery check")
            if not plan.runbook:
                raise RemediationAgentError("A pending plan must include a runbook reference")

        # Stale-plan check: if report is older than 24 hours, mark stale
        if plan.based_on_report_at:
            age_hours = (datetime.now(timezone.utc) - plan.based_on_report_at).total_seconds() / 3600
            if age_hours > 24:
                plan.status = PlanStatus.STALE

        # No actions approved -> needs human
        if not plan.steps and plan.status is PlanStatus.PENDING:
            plan.status = PlanStatus.NEEDS_HUMAN
            plan.reason = "No actions were approved by policy; human approval required"

        submit_remediation_plan(
            plan_id=plan.plan_id or report.incident_id,
            incident_id=plan.incident_id,
            plan_data=plan.model_dump(),
        )

        return plan


__all__ = [
    "RemediationAgentError",
    "RemediationConfigurationError",
    "create_remediation_plan",
]
