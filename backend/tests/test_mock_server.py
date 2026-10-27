import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from mock_server import server as mock_server


def test_server_exposes_fixture_data_and_switches_scenarios():
    previous_scenario = mock_server.STATE["scenario"]
    mock_server.STATE["scenario"] = "case1_payment"
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base_url}/_mock/scenarios") as response:
            scenarios = json.load(response)
        assert scenarios["current"] == "case1_payment"
        assert scenarios["available"] == [
            "case1_payment",
            "case2_memory_leak",
            "case3_adversarial",
        ]

        query = "error_rate%7Bservice%3D%22payment%22%7D"
        with urlopen(f"{base_url}/api/v1/query_range?query={query}") as response:
            metrics = json.load(response)
        assert metrics["status"] == "success"
        assert len(metrics["data"]["result"]) == 1
        assert float(metrics["data"]["result"][0]["values"][-1][1]) == 0.9103

        body = json.dumps(
            {"query": {"bool": {"filter": [{"terms": {"severity": ["error"]}}]}}}
        ).encode()
        request = Request(
            f"{base_url}/otel-logs/_search",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            logs = json.load(response)
        assert logs["hits"]["total"]["value"] == 16
        assert any(
            "Payment request failed. Invalid token."
            in hit["_source"]["message"]
            for hit in logs["hits"]["hits"]
        )

        request = Request(
            f"{base_url}/_mock/scenario/case2_memory_leak",
            data=b"",
            method="POST",
        )
        with urlopen(request) as response:
            assert json.load(response)["current"] == "case2_memory_leak"

        with urlopen(f"{base_url}/api/traces") as response:
            traces = json.load(response)
        assert traces["total"] == 3
    finally:
        mock_server.STATE["scenario"] = previous_scenario
        server.shutdown()
        server.server_close()
        thread.join()
