import json
from types import SimpleNamespace

from backend.agents.triage.agent import run_triage
from backend.agents.triage.tools import load_incident_packet
from backend.schemas import DiagnosisStatus


class FakeAnthropicClient:
    def __init__(self, report_json):
        self.report_json = report_json
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    {
                        "type": "tool_use",
                        "id": "metrics-call",
                        "name": "get_metrics",
                        "input": {"incident_id": "inc-case1-payment"},
                    },
                    {
                        "type": "tool_use",
                        "id": "logs-call",
                        "name": "search_logs",
                        "input": {
                            "incident_id": "inc-case1-payment",
                            "service": "payment",
                            "severity": "error",
                        },
                    },
                    {
                        "type": "tool_use",
                        "id": "traces-call",
                        "name": "get_traces",
                        "input": {"incident_id": "inc-case1-payment"},
                    },
                ],
            )
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[{"type": "text", "text": self.report_json}],
        )


def test_case1_tool_use_returns_an_evidence_validated_report():
    packet = load_incident_packet("inc-case1-payment")
    payment_error = next(
        entry
        for entry in packet.logs
        if entry.service == "payment" and entry.severity == "error"
    )
    report_json = json.dumps(
        {
            "incident_id": packet.incident_id,
            "window": packet.window.model_dump(mode="json"),
            "affected_services": ["checkout", "payment"],
            "hypotheses": [
                {
                    "id": "H1",
                    "cause": "Payment authorization requests fail because of an invalid token.",
                    "category": "service_failure",
                    "service": "payment",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "source": "logs",
                            "ref": payment_error.ref,
                            "quote": payment_error.message,
                        }
                    ],
                }
            ],
            "unknowns": [],
        }
    )
    client = FakeAnthropicClient(report_json)

    report = run_triage(packet, client=client)

    assert report.status is DiagnosisStatus.OK
    assert report.hypotheses[0].evidence[0].quote == payment_error.message
    assert len(client.calls) == 2
    tool_results = client.calls[1]["messages"][-1]["content"]
    assert [result["tool_use_id"] for result in tool_results] == [
        "metrics-call",
        "logs-call",
        "traces-call",
    ]
