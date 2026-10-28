"""Mock telemetry server: answers like Prometheus, OpenSearch and Jaeger,
but serves the data in fixtures/<scenario>.json.

Standard library only, so nothing to install.

    python -m mock_server.server                      # case1_payment on port 9999
    python -m mock_server.server --scenario case2_memory_leak --port 9999

Then in .env:
    PROMETHEUS_URL=http://localhost:9999
    OPENSEARCH_URL=http://localhost:9999
    OPENSEARCH_LOG_INDEX=otel-logs
    JAEGER_URL=http://localhost:9999

Switch scenario while running:  POST http://localhost:9999/_mock/scenario/case2_memory_leak
List scenarios:                 GET  http://localhost:9999/_mock/scenarios

Endpoints (the same paths the real services use):
    GET  /api/v1/query_range?query=error_rate{service="checkout"}&start=&end=&step=   (Prometheus)
    POST /{index}/_search                                                             (OpenSearch)
    GET  /api/traces?service=checkout&start=&end=&limit=                              (Jaeger, times in microseconds)
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# How each scenario misbehaves on purpose (PRD eval case 3).
BEHAVIOR = {
    "case3_adversarial": {"jaeger": "timeout"},
}
TIMEOUT_SECONDS = 30  # longer than any sane client timeout

STATE = {"scenario": "case1_payment"}


def load(scenario: str) -> dict:
    return json.loads((FIXTURES / f"{scenario}.json").read_text())


def scenarios() -> list[str]:
    return sorted(p.stem for p in FIXTURES.glob("case*.json"))


def to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def parse_time(raw: str | None, default: float, micros: bool = False) -> float:
    """Accept epoch seconds (Prometheus), epoch microseconds (Jaeger) or ISO text."""
    if not raw:
        return default
    try:
        number = float(raw)
        return number / 1_000_000 if micros else number
    except ValueError:
        return to_epoch(raw)


# --------------------------------------------------------------------------- Prometheus

QUERY_RE = re.compile(r'^\s*([a-zA-Z_:][\w:]*)\s*(?:\{([^}]*)\})?\s*$')
LABEL_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def prometheus_range(packet: dict, query: str, start: float, end: float) -> dict:
    match = QUERY_RE.match(query or "")
    if not match:
        return {"status": "error", "errorType": "bad_data", "error": f"cannot parse query {query!r}"}
    name, labels = match.group(1), dict(LABEL_RE.findall(match.group(2) or ""))
    wanted_service = labels.get("service") or labels.get("service_name")
    result = []
    for series in packet["metrics"]:
        if series["metric"] != name or (wanted_service and series["service"] != wanted_service):
            continue
        values = [[to_epoch(p["timestamp"]), str(p["value"])] for p in series["points"]
                  if start <= to_epoch(p["timestamp"]) <= end]
        if values:
            result.append({
                "metric": {"__name__": name, "service": series["service"],
                           "ref": series["ref"], "baseline": str(series.get("baseline"))},
                "values": values,
            })
    return {"status": "success", "data": {"resultType": "matrix", "result": result}}


# --------------------------------------------------------------------------- OpenSearch

def opensearch_search(packet: dict, body: dict) -> dict:
    """Supports the filters our search_logs tool sends:
    terms on service / severity, a range on @timestamp, and size."""
    services = severities = None
    start, end = float("-inf"), float("inf")
    filters = body.get("query", {}).get("bool", {}).get("filter", [])
    for clause in filters if isinstance(filters, list) else [filters]:
        terms = clause.get("terms", {})
        services = terms.get("service", services)
        severities = terms.get("severity", severities)
        rng = clause.get("range", {}).get("@timestamp")
        if rng:
            start = parse_time(rng.get("gte"), start)
            end = parse_time(rng.get("lte"), end)
    size = int(body.get("size", 200))
    hits = []
    for log in packet["logs"]:
        ts = to_epoch(log["timestamp"])
        if services and log["service"] not in services:
            continue
        if severities and log["severity"] not in severities:
            continue
        if not start <= ts <= end:
            continue
        hits.append({"_index": "otel-logs", "_id": log["ref"], "_source": {
            "@timestamp": log["timestamp"], "service": log["service"],
            "severity": log["severity"], "message": log["message"], "ref": log["ref"]}})
    return {"took": 3, "timed_out": False,
            "hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": hits[:size]}}


# --------------------------------------------------------------------------- Jaeger

def jaeger_traces(packet: dict, service: str | None, limit: int) -> dict:
    data = []
    for trace in packet["traces"]:
        if service and all(s["service"] != service for s in trace["spans"]):
            continue
        processes, spans = {}, []
        for i, s in enumerate(trace["spans"]):
            pid = f"p{i + 1}"
            processes[pid] = {"serviceName": s["service"], "tags": []}
            tags = [{"key": "error", "type": "bool", "value": True}] if s["error"] else []
            if s.get("error_message"):
                tags.append({"key": "otel.status_description", "type": "string", "value": s["error_message"]})
            spans.append({"traceID": trace["trace_id"], "spanID": f"{trace['trace_id']}-{i}",
                          "operationName": s["operation"], "duration": int(s["duration_ms"] * 1000),
                          "processID": pid, "tags": tags})
        data.append({"traceID": trace["trace_id"], "ref": trace["ref"], "spans": spans, "processes": processes})
    return {"data": data[:limit], "total": len(data[:limit]), "limit": limit, "offset": 0, "errors": None}


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "IncidentPilotMock/1.0"

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        scenario = STATE["scenario"]
        packet = load(scenario)
        window = (to_epoch(packet["window"]["start"]), to_epoch(packet["window"]["end"]))

        if url.path == "/_mock/scenarios":
            return self.send_json({"current": scenario, "available": scenarios()})
        if url.path == "/api/v1/query_range":
            start = parse_time(query.get("start"), window[0])
            end = parse_time(query.get("end"), window[1])
            return self.send_json(prometheus_range(packet, query.get("query", ""), start, end))
        if url.path in ("/api/traces", "/jaeger/ui/api/traces"):
            if BEHAVIOR.get(scenario, {}).get("jaeger") == "timeout":
                time.sleep(TIMEOUT_SECONDS)
                return self.send_json({"data": [], "errors": [{"code": 504, "msg": "timeout"}]}, 504)
            return self.send_json(jaeger_traces(packet, query.get("service"), int(query.get("limit", 20))))
        if url.path in ("/api/services", "/jaeger/ui/api/services"):
            return self.send_json({"data": packet["services"], "total": len(packet["services"])})
        return self.send_json({"error": f"unknown path {url.path}"}, 404)

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"

        switch = re.fullmatch(r"/_mock/scenario/([\w-]+)", url.path)
        if switch:
            name = switch.group(1)
            if name not in scenarios():
                return self.send_json({"error": f"unknown scenario {name}", "available": scenarios()}, 404)
            STATE["scenario"] = name
            return self.send_json({"current": name})
        if url.path.endswith("/_search"):
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"error": "invalid JSON body"}, 400)
            return self.send_json(opensearch_search(load(STATE["scenario"]), body))
        return self.send_json({"error": f"unknown path {url.path}"}, 404)

    def log_message(self, fmt, *args):
        print(f"[mock:{STATE['scenario']}] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="case1_payment")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()
    if args.scenario not in scenarios():
        raise SystemExit(f"Unknown scenario {args.scenario!r}. Available: {scenarios()}. "
                         "Run `python -m mock_server.make_fixtures` first.")
    STATE["scenario"] = args.scenario
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Mock telemetry server on http://127.0.0.1:{args.port} serving {args.scenario}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
