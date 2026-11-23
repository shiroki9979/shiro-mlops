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


class StubService:
    """A loopback stub whose response each test overrides per path."""

    def __init__(self, routes: dict[str, Response | list[Response]]) -> None:
        # A list is served in order, one response per request, then its last item repeats.
        self.routes = routes
        self.base_url = ""
        # Paths answered 403 unless the request's Host header is one of `allowed_hosts`,
        # as MLflow 3 answers its API (but not /health) for a host it was not told to serve.
        self.host_checked_paths: frozenset[str] = frozenset()
        self.allowed_hosts: frozenset[str] = frozenset()
        self.seen_hosts: list[tuple[str, str]] = []

    def respond_to(self, path: str, host: str) -> Response:
        self.seen_hosts.append((path, host))
        if path in self.host_checked_paths and host not in self.allowed_hosts:
            return Response(403, b"Invalid Host header", "text/plain")
        return self.respond(path)

    def respond(self, path: str) -> Response:
        route = self.routes.get(path, Response(404, b"not found", "text/plain"))
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route


def _serve(stub: StubService) -> Iterator[StubService]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            response = stub.respond_to(self.path, self.headers.get("Host", ""))
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
def api() -> Iterator[StubService]:
    yield from _serve(
        StubService({"/data/status": _json(200, DATA_STATUS), "/ready": _json(503, NOT_READY)})
    )


MLFLOW_API_PATH = "/api/2.0/mlflow/experiments/search?max_results=1"
COMPOSE_MLFLOW_HOST = "mlflow:5000"


@pytest.fixture
def mlflow() -> Iterator[StubService]:
    stub = StubService(
        {
            "/health": Response(200, b"OK", "text/plain"),
            MLFLOW_API_PATH: _json(200, {"experiments": []}),
        }
    )
    stub.host_checked_paths = frozenset({MLFLOW_API_PATH})
    stub.allowed_hosts = frozenset({COMPOSE_MLFLOW_HOST})
    yield from _serve(stub)


def _run(
    api: StubService, mlflow: StubService, capsys: pytest.CaptureFixture[str], *extra: str
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
    [data_status, mlflow_health, mlflow_api] = _failure_lines(output)
    assert mlflow_api.startswith("- MLflow tracking API as mlflow:5000: cannot reach")
    assert data_status == "- API /data/status: HTTP 500, expected 200"
    assert mlflow_health.startswith("- MLflow /health: cannot reach http://127.0.0.1:9/health")


def test_not_ready_without_a_reason_fails(api, mlflow, capsys) -> None:
    api.routes["/ready"] = _json(503, {**NOT_READY, "reason": None})

    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- API /ready: reason is None with HTTP 503, expected a non-empty string"
    ]


def test_mlflow_api_is_asked_under_the_host_name_the_other_containers_use(
    api, mlflow, capsys
) -> None:
    exit_code, _ = _run(api, mlflow, capsys)

    assert exit_code == 0
    assert (MLFLOW_API_PATH, COMPOSE_MLFLOW_HOST) in mlflow.seen_hosts


def test_mlflow_refusing_the_compose_host_name_fails_though_health_answers(
    api, mlflow, capsys
) -> None:
    """MLflow 3 serves /health to any host, so health alone passes while tracking is refused."""
    mlflow.allowed_hosts = frozenset({"localhost:5001", "127.0.0.1:5001"})

    exit_code, output = _run(api, mlflow, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- MLflow tracking API as mlflow:5000: HTTP 403, expected 200"
    ]


def test_the_in_network_mlflow_host_can_be_named(api, mlflow, capsys) -> None:
    mlflow.allowed_hosts = frozenset({"tracking:5000"})

    exit_code, _ = _run(api, mlflow, capsys, "--mlflow-internal-host", "tracking:5000")

    assert exit_code == 0


@pytest.mark.parametrize(
    "host", ["", "has space:5000", "mlflow:5000\r\nX-Injected: 1", "http://mlflow"]
)
def test_an_internal_host_that_is_not_a_host_header_value_is_an_argument_error(
    api, mlflow, capsys, host
) -> None:
    exit_code, _ = _run(api, mlflow, capsys, "--mlflow-internal-host", host)

    assert exit_code == 2
