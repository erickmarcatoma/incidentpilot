"""Anthropic-backed triage agent with access limited to recorded telemetry tools."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from backend.agents.triage.tools import get_metrics, get_traces, search_logs
from backend.orchestrator import validate_report
from backend.schemas import IncidentPacket, RootCauseReport

_PROMPT_PATH = Path(__file__).with_name("prompt.md")
_MAX_TOOL_ROUNDS = 8
_MAX_REPORT_RETRIES = 1  # PRD 3e: one retry with the error, then fail
_DEFAULT_MODEL = "claude-sonnet-5-5"
_TOOLS: list[dict[str, object]] = [
    {
        "name": "get_metrics",
        "description": "Get recorded metric series for this incident.",
        "input_schema": {
            "type": "object",
            "properties": {"incident_id": {"type": "string"}},
            "required": ["incident_id"],
        },
    },
    {
        "name": "search_logs",
        "description": "Search recorded logs for this incident.",
        "input_schema": {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string"},
                "service": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["debug", "info", "warning", "error", "critical"],
                },
                "query": {"type": "string"},
            },
            "required": ["incident_id"],
        },
    },
    {
        "name": "get_traces",
        "description": "Get recorded traces for this incident.",
        "input_schema": {
            "type": "object",
            "properties": {"incident_id": {"type": "string"}},
            "required": ["incident_id"],
        },
    },
]


class TriageConfigurationError(RuntimeError):
    """Raised when the agent cannot be configured to call Anthropic."""


class TriageAgentError(RuntimeError):
    """Raised when the model does not produce a usable triage report."""


def run_triage(
    packet: IncidentPacket,
    client: Any | None = None,
) -> RootCauseReport:
    """Investigate a packet, then validate the model's report against its evidence."""
    if client is None:
        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise TriageConfigurationError(
                "ANTHROPIC_API_KEY is required to run the Triage agent"
            )
        client = Anthropic(api_key=api_key, timeout=90.0)

    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": (
                "Investigate this incident packet and return the required JSON report:\n"
                f"{packet.model_dump_json()}"
            ),
        }
    ]
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    report_text: str | None = None

    retries_left = _MAX_REPORT_RETRIES
    rounds = 0
    while True:
        round_number = rounds
        rounds += 1
        response = client.messages.create(
            model=os.getenv("TRIAGE_MODEL") or os.getenv("ANTHROPIC_MODEL") or _DEFAULT_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=_TOOLS,
        )
        tool_uses = [
            block for block in response.content if _block_value(block, "type") == "tool_use"
        ]
        if not tool_uses:
            report_text = "\n".join(
                str(_block_value(block, "text"))
                for block in response.content
                if _block_value(block, "type") == "text"
            )
            try:
                report = RootCauseReport.model_validate_json(_extract_json(report_text))
            except (ValidationError, ValueError) as exc:
                if retries_left <= 0:
                    raise TriageAgentError(
                        f"Triage returned a report that failed validation: {_short_error(exc)}"
                    ) from exc
                retries_left -= 1
                messages.append(
                    {
                        "role": "assistant",
                        "content": [_block_as_dict(block) for block in response.content],
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your report was rejected by the schema validator:\n"
                            f"{_short_error(exc)}\n"
                            "Reply again with only the corrected JSON object, "
                            "using exactly the fields in the Output section."
                        ),
                    }
                )
                continue
            return validate_report(packet, report)
        if round_number == _MAX_TOOL_ROUNDS:
            raise TriageAgentError(
                f"Triage exceeded the {_MAX_TOOL_ROUNDS}-round tool-use limit"
            )

        messages.append(
            {
                "role": "assistant",
                "content": [_block_as_dict(block) for block in response.content],
            }
        )
        tool_results = []
        for block in tool_uses:
            tool_name = _block_value(block, "name")
            tool_input = _block_value(block, "input")
            tool_id = _block_value(block, "id")
            try:
                result = _run_tool(packet.incident_id, tool_name, tool_input)
            except (FileNotFoundError, ValueError) as exc:
                raise TriageAgentError(
                    f"Triage tool {tool_name!r} could not complete"
                ) from exc
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})



def _extract_json(text: str | None) -> str:
    """Pull the JSON object out of a reply that may have code fences or prose around it."""
    if not text or not text.strip():
        raise ValueError("Triage did not return a JSON report")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Triage reply contained no JSON object")
    return text[start : end + 1]


def _short_error(exc: Exception, limit: int = 1500) -> str:
    message = str(exc)
    return message if len(message) <= limit else message[:limit] + " ..."


def _run_tool(
    expected_incident_id: str,
    tool_name: object,
    tool_input: object,
) -> object:
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        raise TriageAgentError("Triage returned a malformed tool call")
    if tool_input.get("incident_id") != expected_incident_id:
        raise TriageAgentError("Triage tool call used a different incident id")

    if tool_name == "get_metrics":
        return get_metrics(expected_incident_id)
    if tool_name == "get_traces":
        return get_traces(expected_incident_id)
    if tool_name == "search_logs":
        allowed = {"incident_id", "service", "severity", "query"}
        if set(tool_input) - allowed:
            raise TriageAgentError("Triage supplied unsupported log-search arguments")
        for key in ("service", "severity", "query"):
            value = tool_input.get(key)
            if value is not None and not isinstance(value, str):
                raise TriageAgentError(f"Triage supplied an invalid {key!r} filter")
        return search_logs(
            expected_incident_id,
            service=tool_input.get("service"),
            severity=tool_input.get("severity"),
            query=tool_input.get("query"),
        )
    raise TriageAgentError(f"Triage requested unsupported tool {tool_name!r}")


def _block_value(block: object, key: str) -> object:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _block_as_dict(block: object) -> dict[str, object]:
    if isinstance(block, dict):
        return block
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    raise TriageAgentError("Anthropic returned an unsupported message block")


__all__ = [
    "TriageAgentError",
    "TriageConfigurationError",
    "run_triage",
]