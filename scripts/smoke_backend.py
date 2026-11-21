"""Verify the backend Compose services answer: API data status, API readiness and MLflow health.

Runs every check, repeating the whole round until all pass or `--wait-seconds` runs out, then lists
each check that failed in the last round with the status code or reason it got.
Exit code: 0 when all checks pass, 1 when any check fails, 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

REQUEST_TIMEOUT_SECONDS = 10
# docs/reference/rest-api.md §2; this script runs with `uv run --no-project` and cannot import
# shiro_mlops, so keep it in sync with ReadyResponse in src/shiro_mlops/service/api.py.
READY_MODES = ("normal", "degraded")


class CheckFailedError(Exception):
    """One check did not hold; the message is the reason shown in the CI log."""


@dataclass(frozen=True)
class FetchedResponse:
    status: int
    body: bytes


def fetch(base_url: str, path: str) -> FetchedResponse:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
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
            f"status is {_describe(body, 'status')} with HTTP {response.status},"
            f" expected {expected_status!r}"
        )
    if response.status == 200 and body.get("mode") not in READY_MODES:
        raise CheckFailedError(
            f"mode is {_describe(body, 'mode')} with HTTP 200, expected 'normal' or 'degraded'"
        )
    if not isinstance(body.get("model_loaded"), bool):
        raise CheckFailedError(
            f"model_loaded is {_describe(body, 'model_loaded')}, expected a boolean"
        )


def _describe(body: dict[str, object], key: str) -> str:
    return repr(body[key]) if key in body else "missing"


def check_mlflow_health(mlflow_url: str) -> None:
    require_status(fetch(mlflow_url, "/health"), 200)


def planned_checks(api_url: str, mlflow_url: str) -> list[tuple[str, Callable[[], None]]]:
    return [
        ("API /data/status", lambda: check_data_status(api_url)),
        ("API /ready", lambda: check_ready(api_url)),
        ("MLflow /health", lambda: check_mlflow_health(mlflow_url)),
    ]


def run_checks(planned: list[tuple[str, Callable[[], None]]]) -> list[str]:
    failures: list[str] = []
    for name, check in planned:
        try:
            check()
        except CheckFailedError as error:
            failures.append(f"  - {name}: {error}")
    return failures


def run_until_deadline(
    planned: list[tuple[str, Callable[[], None]]], wait_seconds: float, interval_seconds: float
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, type=parse_base_url, help="FastAPI base URL")
    parser.add_argument(
        "--mlflow-url", required=True, type=parse_base_url, help="MLflow server base URL"
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

    planned = planned_checks(args.api_url, args.mlflow_url)
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
