"""Offline tests for the backend Compose smoke check in scripts/smoke_backend.py.

Each test serves two loopback `http.server` stubs, one shaped like the FastAPI service and one
like the MLflow tracking server, and overrides their responses per path.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from smoke_backend import main

DATA_STATUS = {"timezone": "Asia/Taipei", "datasets": []}
# CI has no trained model, so the API reports the forecast task as not ready.
NOT_READY = {
    "status": "not_ready",
    "mode": None,
    "model_loaded": False,
    "reason": "model is not loaded",
}


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "application/json"


def _json(status: int, document: object) -> Response:
    return Response(status, json.dumps(document).encode("utf-8"))


class Server:
    """A loopback stub whose response each test overrides per path."""

    def __init__(self, routes: dict[str, Response | list[Response]]) -> None:
        # A list is served in order, one response per request, then its last item repeats.
        self.routes = routes
        self.base_url = ""

    def respond(self, path: str) -> Response:
        route = self.routes.get(path, Response(404, b"not found", "text/plain"))
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route


def _serve(stub: Server) -> Iterator[Server]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            response = stub.respond(self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    stub.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield stub
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def api() -> Iterator[Server]:
    yield from _serve(
        Server({"/data/status": _json(200, DATA_STATUS), "/ready": _json(503, NOT_READY)})
    )


@pytest.fixture
def mlflow() -> Iterator[Server]:
    yield from _serve(Server({"/health": Response(200, b"OK", "text/plain")}))


def _run(
    api: Server, mlflow: Server, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, str]:
    exit_code = main(["--api-url", api.base_url, "--mlflow-url", mlflow.base_url, *extra])
    captured = capsys.readouterr()
    return exit_code, captured.out + captured.err


def _failure_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("- ")]


def test_backend_without_a_model_passes(api, mlflow, capsys) -> None:
    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 0
    assert "passed" in output


def test_not_ready_body_without_model_loaded_fails(api, mlflow, capsys) -> None:
    body = {key: value for key, value in NOT_READY.items() if key != "model_loaded"}
    api.routes["/ready"] = _json(503, body)

    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == ["- API /ready: model_loaded is missing, expected a boolean"]


@pytest.mark.parametrize("mode", ["normal", "degraded"])
def test_ready_with_a_forecast_mode_passes(api, mlflow, capsys, mode) -> None:
    api.routes["/ready"] = _json(
        200, {"status": "ready", "mode": mode, "model_loaded": True, "reason": None}
    )

    exit_code, _ = _run(api, mlflow, capsys)

    assert exit_code == 0


def test_ready_without_a_mode_fails(api, mlflow, capsys) -> None:
    api.routes["/ready"] = _json(
        200, {"status": "ready", "mode": None, "model_loaded": True, "reason": None}
    )

    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- API /ready: mode is None with HTTP 200, expected 'normal' or 'degraded'"
    ]


def test_status_that_disagrees_with_http_status_fails(api, mlflow, capsys) -> None:
    api.routes["/ready"] = _json(503, {**NOT_READY, "status": "ready"})

    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- API /ready: status is 'ready' with HTTP 503, expected 'not_ready'"
    ]


def test_starting_services_pass_once_they_answer_within_the_wait(api, mlflow, capsys) -> None:
    starting = Response(502, b"bad gateway", "text/plain")
    mlflow.routes["/health"] = [starting, starting, Response(200, b"OK", "text/plain")]

    exit_code, _ = _run(api, mlflow, capsys, "--wait-seconds", "5", "--interval-seconds", "0.01")

    assert exit_code == 0


def test_every_check_still_failing_at_the_deadline_is_listed(api, mlflow, capsys) -> None:
    api.routes["/data/status"] = _json(500, {"detail": "relation does not exist"})
    mlflow.base_url = "http://127.0.0.1:9"

    exit_code, output = _run(
        api, mlflow, capsys, "--wait-seconds", "0.05", "--interval-seconds", "0.01"
    )

    assert exit_code == 1
    [data_status, mlflow_health] = _failure_lines(output)
    assert data_status == "- API /data/status: HTTP 500, expected 200"
    assert mlflow_health.startswith("- MLflow /health: cannot reach http://127.0.0.1:9/health")
