"""Verify the backend Compose services answer: API data status, API readiness, MLflow health
and the MLflow tracking API under the host name the other containers call it by.

Runs every check, repeating the whole round until all pass or `--wait-seconds` runs out, then lists
each check that failed in the last round with the status code or reason it got.
Exit code: 0 when all checks pass, 1 when any check fails, 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

REQUEST_TIMEOUT_SECONDS = 10
# SYNC(docs/reference/rest-api.md, src/shiro_mlops/data/weather_resolution.py): the modes a ready
# task reports (`ForecastMode`); this script runs with `uv run --no-project` and
# cannot import shiro_mlops.
READY_MODES = ("normal", "degraded")
# SYNC(docker/docker-compose.yml): the host and port of MLFLOW_TRACKING_URI there, which is
# the Host header the api and dagster containers send; it must also be listed in the mlflow
# service's MLFLOW_SERVER_ALLOWED_HOSTS.
DEFAULT_MLFLOW_INTERNAL_HOST = "mlflow:5000"
MLFLOW_API_PATH = "/api/2.0/mlflow/experiments/search?max_results=1"
HOST_HEADER_VALUE = re.compile(r"[A-Za-z0-9.-]+(:\d{1,5})?")


PlannedCheck = tuple[str, Callable[[], None]]


class CheckFailedError(Exception):
    """One check did not hold; the message is the reason shown in the CI log."""


@dataclass(frozen=True)
class FetchedResponse:
    status: int
    body: bytes


def fetch(base_url: str, path: str, *, host: str | None = None) -> FetchedResponse:
    """GET `path`; `host` replaces the Host header, to ask as a client inside the network."""
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = Request(url, headers={} if host is None else {"Host": host})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return FetchedResponse(response.status, response.read())
    except HTTPError as error:
        return FetchedResponse(error.code, error.read())
    except OSError as error:
        raise CheckFailedError(f"cannot reach {url}: {getattr(error, 'reason', error)}") from error


def require_status(response: FetchedResponse, *expected: int) -> None:
    if response.status not in expected:
        wanted = " or ".join(str(status) for status in expected)
        raise CheckFailedError(f"HTTP {response.status}, expected {wanted}")


def parse_json(response: FetchedResponse) -> object:
    try:
        return json.loads(response.body.decode("utf-8"))
    except ValueError as error:
        raise CheckFailedError(f"body is not valid JSON: {error}") from error


def check_data_status(api_url: str) -> None:
    response = fetch(api_url, "/data/status")
    require_status(response, 200)
    parse_json(response)


def check_ready(api_url: str) -> None:
    response = fetch(api_url, "/ready")
    require_status(response, 200, 503)
    body = parse_json(response)
    if not isinstance(body, dict):
        raise CheckFailedError("body is not a JSON object")
    expected_status = "ready" if response.status == 200 else "not_ready"
    if body.get("status") != expected_status:
        raise CheckFailedError(
            f"status is {_repr_or_missing(body, 'status')} with HTTP {response.status},"
            f" expected {expected_status!r}"
        )
    if response.status == 200 and body.get("mode") not in READY_MODES:
        expected_modes = " or ".join(repr(mode) for mode in READY_MODES)
        raise CheckFailedError(
            f"mode is {_repr_or_missing(body, 'mode')} with HTTP 200, expected {expected_modes}"
        )
    reason = body.get("reason")
    if response.status == 503 and not (isinstance(reason, str) and reason):
        raise CheckFailedError(
            f"reason is {_repr_or_missing(body, 'reason')} with HTTP 503,"
            " expected a non-empty string"
        )
    if not isinstance(body.get("model_loaded"), bool):
        raise CheckFailedError(
            f"model_loaded is {_repr_or_missing(body, 'model_loaded')}, expected a boolean"
        )


def _repr_or_missing(body: dict[str, object], key: str) -> str:
    return repr(body[key]) if key in body else "missing"


def check_mlflow_health(mlflow_url: str) -> None:
    require_status(fetch(mlflow_url, "/health"), 200)


def check_mlflow_tracking_api(mlflow_url: str, internal_host: str) -> None:
    """The tracking API must answer the Host header a container sends, not only /health.

    MLflow 3 refuses API requests whose Host it was not told to serve but answers /health to
    anyone, so health alone stays green while every training run fails to record itself.
    """
    require_status(fetch(mlflow_url, MLFLOW_API_PATH, host=internal_host), 200)


def planned_checks(api_url: str, mlflow_url: str, mlflow_internal_host: str) -> list[PlannedCheck]:
    return [
        ("API /data/status", lambda: check_data_status(api_url)),
        ("API /ready", lambda: check_ready(api_url)),
        ("MLflow /health", lambda: check_mlflow_health(mlflow_url)),
        (
            f"MLflow tracking API as {mlflow_internal_host}",
            lambda: check_mlflow_tracking_api(mlflow_url, mlflow_internal_host),
        ),
    ]


def run_checks(planned: list[PlannedCheck]) -> list[str]:
    failures: list[str] = []
    for name, check in planned:
        try:
            check()
        except CheckFailedError as error:
            failures.append(f"  - {name}: {error}")
    return failures


def run_until_deadline(
    planned: list[PlannedCheck], wait_seconds: float, interval_seconds: float
) -> list[str]:
    deadline = time.monotonic() + wait_seconds
    while True:
        failures = run_checks(planned)
        if not failures or time.monotonic() + interval_seconds > deadline:
            return failures
        time.sleep(interval_seconds)


def parse_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a number of seconds: {value!r}") from error
    if seconds < 0:
        raise argparse.ArgumentTypeError(f"seconds must not be negative: {value!r}")
    return seconds


def parse_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise argparse.ArgumentTypeError(f"not an http(s) URL: {value!r}")
    return value


def parse_host_header(value: str) -> str:
    if not HOST_HEADER_VALUE.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a host or host:port: {value!r}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, type=parse_base_url, help="FastAPI base URL")
    parser.add_argument(
        "--mlflow-url", required=True, type=parse_base_url, help="MLflow server base URL"
    )
    parser.add_argument(
        "--mlflow-internal-host",
        type=parse_host_header,
        default=DEFAULT_MLFLOW_INTERNAL_HOST,
        help="Host header the other containers send to MLflow "
        f"(default: {DEFAULT_MLFLOW_INTERNAL_HOST})",
    )
    parser.add_argument(
        "--wait-seconds",
        type=parse_seconds,
        default=0.0,
        help="keep retrying failed rounds for this long while the services start (default: 0)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=parse_seconds,
        default=2.0,
        help="pause between rounds (default: 2)",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)

    planned = planned_checks(args.api_url, args.mlflow_url, args.mlflow_internal_host)
    failures = run_until_deadline(planned, args.wait_seconds, args.interval_seconds)
    if failures:
        print(
            f"Backend smoke check failed ({len(failures)} of {len(planned)} checks):",
            file=sys.stderr,
        )
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Backend smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
