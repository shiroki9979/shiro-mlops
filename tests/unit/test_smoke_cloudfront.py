"""Offline tests for the cloud Forecast View smoke check in scripts/smoke_cloudfront.py.

Each test serves a loopback `http.server` stub shaped like the CloudFront distribution
(hosting spec §5): `site/` routes as HTML, the two published exports from
tests/fixtures/published/, and 403 for anything else, as OAC without `s3:ListBucket` does.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from smoke_cloudfront import main

PUBLISHED_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "published"
INDEX_HTML = b'<!doctype html><html><body><div id="root"></div></body></html>'
# The fixture forecast was issued at 2026-11-20T10:15:00+08:00.
NOW = "2026-11-20T12:00:00+08:00"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "text/plain"
    location: str | None = None


def _html() -> Response:
    return Response(200, INDEX_HTML, "text/html")


def _json(document: object) -> Response:
    return Response(200, json.dumps(document).encode("utf-8"), "application/json")


def _fixture(name: str) -> dict:
    return json.loads((PUBLISHED_FIXTURES / name).read_text(encoding="utf-8"))


def _latest_issued(issued_at: str | None) -> Response:
    document = _fixture("latest_issued_forecast.json")
    document["issued_at"] = issued_at
    return _json(document)


class Distribution:
    """A stub distribution whose responses each test overrides per path."""

    def __init__(self) -> None:
        self.routes: dict[str, Response] = {
            "/": _html(),
            "/history": _html(),
            "/published/latest_issued_forecast.json": _json(
                _fixture("latest_issued_forecast.json")
            ),
            "/published/forecast_track_record.json": _json(_fixture("forecast_track_record.json")),
        }
        self.missing = Response(403, b"<Error><Code>AccessDenied</Code></Error>", "application/xml")
        self.base_url = ""

    def respond(self, path: str) -> Response:
        return self.routes.get(path, self.missing)


@pytest.fixture
def distribution() -> Iterator[Distribution]:
    stub = Distribution()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            response = stub.respond(self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            if response.location is not None:
                self.send_header("Location", response.location)
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


def _run(distribution: Distribution, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    exit_code = main(["--base-url", distribution.base_url, "--now", NOW])
    captured = capsys.readouterr()
    return exit_code, captured.out + captured.err


def test_healthy_distribution_passes(distribution, capsys) -> None:
    exit_code, output = _run(distribution, capsys)

    assert exit_code == 0
    assert "passed" in output


def _failure_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("- ")]


def test_history_forbidden_fails_with_its_status(distribution, capsys) -> None:
    distribution.routes["/history"] = Response(403, b"denied")

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == ["- /history is HTML: HTTP 403, expected 200"]


def test_missing_published_file_served_as_html_fails(distribution, capsys) -> None:
    distribution.missing = _html()

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- /published/definitely-missing-smoke-check.json is not 200:"
        " HTTP 200, expected an error status"
    ]


def test_issued_at_older_than_24_hours_fails(distribution, capsys) -> None:
    distribution.routes["/published/latest_issued_forecast.json"] = _latest_issued(
        "2026-11-19T11:59:59+08:00"
    )

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    [line] = _failure_lines(output)
    assert line.startswith("- /published/latest_issued_forecast.json is fresh:")
    assert "more than 24 hours" in line


def test_issued_at_exactly_24_hours_old_passes(distribution, capsys) -> None:
    distribution.routes["/published/latest_issued_forecast.json"] = _latest_issued(
        "2026-11-19T04:00:00Z"
    )

    exit_code, _ = _run(distribution, capsys)

    assert exit_code == 0


def test_issued_at_after_now_is_not_checked(distribution, capsys) -> None:
    distribution.routes["/published/latest_issued_forecast.json"] = _latest_issued(
        "2026-11-25T10:15:00+08:00"
    )

    exit_code, _ = _run(distribution, capsys)

    assert exit_code == 0


def test_null_issued_at_fails(distribution, capsys) -> None:
    distribution.routes["/published/latest_issued_forecast.json"] = _latest_issued(None)

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    [line] = _failure_lines(output)
    assert line.startswith("- /published/latest_issued_forecast.json is fresh:")
    assert "issued_at is null" in line


def test_unparseable_json_fails(distribution, capsys) -> None:
    distribution.routes["/published/forecast_track_record.json"] = Response(
        200, b"<!doctype html>", "application/json"
    )

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    [line] = _failure_lines(output)
    assert line.startswith(
        "- /published/forecast_track_record.json is JSON: body is not valid JSON"
    )


def test_root_redirect_is_not_followed(distribution, capsys) -> None:
    distribution.routes["/"] = Response(301, location="/history")

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == ["- / is HTML: HTTP 301, expected 200"]


def test_root_served_as_non_html_fails(distribution, capsys) -> None:
    distribution.routes["/"] = Response(200, b"{}", "application/json")

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    assert _failure_lines(output) == [
        "- / is HTML: Content-Type 'application/json', expected text/html"
    ]


def test_every_failing_check_is_listed(distribution, capsys) -> None:
    # An empty bucket right after `terraform apply`: OAC answers 403 for every object.
    distribution.routes.clear()

    exit_code, output = _run(distribution, capsys)

    assert exit_code == 1
    assert "4 of 5 checks" in output
    assert _failure_lines(output) == [
        "- / is HTML: HTTP 403, expected 200",
        "- /history is HTML: HTTP 403, expected 200",
        "- /published/latest_issued_forecast.json is fresh: HTTP 403, expected 200",
        "- /published/forecast_track_record.json is JSON: HTTP 403, expected 200",
    ]


def test_unreachable_host_fails_every_check(capsys) -> None:
    unreachable = Distribution()
    unreachable.base_url = "http://127.0.0.1:9"

    exit_code, output = _run(unreachable, capsys)

    assert exit_code == 1
    assert len(_failure_lines(output)) == 5
    assert all("cannot reach" in line for line in _failure_lines(output))


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--base-url", "d123.cloudfront.net"],
        ["--base-url", "https://d123.cloudfront.net", "--now", "2026-11-20T12:00:00"],
        ["--base-url", "https://d123.cloudfront.net", "--now", "yesterday"],
    ],
    ids=["no-base-url", "no-scheme", "now-without-offset", "now-not-iso"],
)
def test_invalid_arguments_exit_with_2(argv, capsys) -> None:
    assert main(argv) == 2
