"""Verify a deployed Forecast View URL against hosting spec §5 and ADR-0015 §4.

Runs every check, then lists each one that failed with the status code or reason it got.
Exit code: 0 when all checks pass, 1 when any check fails, 2 for invalid arguments.
Redirects are never followed: any 3xx fails that check.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

REQUEST_TIMEOUT_SECONDS = 10
MAX_ISSUED_AGE = timedelta(hours=24)

# 預報檢視匯出的兩個固定檔名與缺檔探測路徑；此腳本以 `uv run --no-project` 執行、不能 import
# shiro_mlops，變更時須同步 src/shiro_mlops/data/forecast_view.py、tests/fixtures/published/，
# `/published/` 前綴另須同步 infra/terraform/main.tf 的 `local.published_prefix`。
LATEST_ISSUED_PATH = "/published/latest_issued_forecast.json"
TRACK_RECORD_PATH = "/published/forecast_track_record.json"
MISSING_PUBLISHED_PATH = "/published/definitely-missing-smoke-check.json"


class CheckFailedError(Exception):
    """One check did not hold; the message is the reason shown to the deployer."""


class NoRedirectHandler(HTTPRedirectHandler):
    # A 3xx surfaces as an HTTPError carrying its own status, so it fails the check.
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


OPENER = build_opener(NoRedirectHandler)


@dataclass(frozen=True)
class FetchedResponse:
    status: int
    body: bytes
    content_type: str


def fetch(base_url: str, path: str) -> FetchedResponse:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        with OPENER.open(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return FetchedResponse(
                response.status, response.read(), response.headers.get("Content-Type", "")
            )
    except HTTPError as error:
        return FetchedResponse(error.code, error.read(), error.headers.get("Content-Type", ""))
    except OSError as error:
        raise CheckFailedError(f"cannot reach {url}: {getattr(error, 'reason', error)}") from error


def require_ok(status: int) -> None:
    if status != 200:
        raise CheckFailedError(f"HTTP {status}, expected 200")


def check_html(base_url: str, path: str) -> None:
    response = fetch(base_url, path)
    require_ok(response.status)
    media_type = response.content_type.split(";", 1)[0].strip().lower()
    if media_type != "text/html":
        raise CheckFailedError(f"Content-Type {response.content_type!r}, expected text/html")


def fetch_json(base_url: str, path: str) -> object:
    response = fetch(base_url, path)
    require_ok(response.status)
    try:
        return json.loads(response.body.decode("utf-8"))
    except ValueError as error:
        raise CheckFailedError(f"body is not valid JSON: {error}") from error


def check_latest_issued(base_url: str, now: datetime) -> None:
    document = fetch_json(base_url, LATEST_ISSUED_PATH)
    if not isinstance(document, dict):
        raise CheckFailedError("body is not a JSON object")
    issued_at = document.get("issued_at")
    if issued_at is None:
        raise CheckFailedError("issued_at is null; no forecast has been published")
    try:
        issued = datetime.fromisoformat(issued_at)
    except (TypeError, ValueError) as error:
        raise CheckFailedError(f"issued_at {issued_at!r} is not an ISO 8601 timestamp") from error
    if issued.tzinfo is None:
        raise CheckFailedError(f"issued_at {issued_at!r} has no UTC offset")
    # Only staleness is checked; an issued_at later than --now is out of scope (spec §5).
    if now - issued > MAX_ISSUED_AGE:
        raise CheckFailedError(
            f"issued_at {issued_at} is more than 24 hours before {now.isoformat()}"
        )


def check_track_record(base_url: str) -> None:
    fetch_json(base_url, TRACK_RECORD_PATH)


def check_missing_published(base_url: str) -> None:
    """A missing export must not fall back to index.html, served with 200 or by a redirect."""
    status = fetch(base_url, MISSING_PUBLISHED_PATH).status
    if status == 200 or 300 <= status < 400:
        raise CheckFailedError(f"HTTP {status}, expected an error status")


def planned_checks(base_url: str, now: datetime) -> list[tuple[str, Callable[[], None]]]:
    return [
        ("/ is HTML", lambda: check_html(base_url, "/")),
        ("/history is HTML", lambda: check_html(base_url, "/history")),
        (f"{LATEST_ISSUED_PATH} is fresh", lambda: check_latest_issued(base_url, now)),
        (f"{TRACK_RECORD_PATH} is JSON", lambda: check_track_record(base_url)),
        (f"{MISSING_PUBLISHED_PATH} is not 200", lambda: check_missing_published(base_url)),
    ]


def parse_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise argparse.ArgumentTypeError(f"not an http(s) URL: {value!r}")
    return value


def parse_now(value: str) -> datetime:
    try:
        now = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 timestamp: {value!r}") from error
    if now.tzinfo is None:
        raise argparse.ArgumentTypeError(f"timestamp needs a UTC offset: {value!r}")
    return now


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        type=parse_base_url,
        help="Forecast View URL, e.g. `terraform output -raw forecast_view_url`",
    )
    parser.add_argument(
        "--now",
        type=parse_now,
        help="ISO 8601 timestamp with offset to judge issued_at against (default: now)",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    now = args.now or datetime.now().astimezone()

    planned = planned_checks(args.base_url, now)
    failures: list[str] = []
    for name, check in planned:
        try:
            check()
        except CheckFailedError as error:
            failures.append(f"  - {name}: {error}")

    if failures:
        print(
            f"Forecast View smoke check failed for {args.base_url}"
            f" ({len(failures)} of {len(planned)} checks):",
            file=sys.stderr,
        )
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Forecast View smoke check passed for {args.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
