"""Exercise the built local frontend through its Nginx HTTP entry point."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, build_opener

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
LOOPBACK_HOST = "127.0.0.1"
REQUIRED_HOST_PORTS = (("frontend", "8080"), ("api", "8000"))
NESTED_SPA_ROUTE = "/data/power/load"
MISSING_ASSET_PATH = "/assets/definitely-missing-smoke-check.js"


class AssetFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.asset_path: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.asset_path is not None:
            return
        attr = dict(attrs)
        path = attr.get("src") if tag == "script" else attr.get("href")
        if path and path.startswith("/assets/"):
            self.asset_path = path


class NoRedirectHandler(HTTPRedirectHandler):
    # Redirects are asserted on directly; following them would hide a Location that drops the port.
    def redirect_request(self, *args, **kwargs) -> None:
        return None


OPENER = build_opener(NoRedirectHandler)


def fetch(base_url: str, path: str) -> tuple[int, str, dict[str, str]]:
    url = gateway_url(base_url, path)
    try:
        with OPENER.open(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)
    except HTTPError as error:
        return error.code, error.read().decode("utf-8"), dict(error.headers)
    except URLError as error:
        raise AssertionError(f"Cannot reach {url}: {error.reason}") from error


def gateway_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_spa(base_url: str) -> None:
    home = check_spa_root(base_url)
    check_nested_route(base_url, home)
    check_built_asset(base_url, home)
    check_missing_asset(base_url)


def check_spa_root(base_url: str) -> str:
    status, home, headers = fetch(base_url, "/")
    require(status == 200, f"SPA root returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), "SPA root is not HTML")
    require('<div id="root"></div>' in home, "SPA root document is missing")
    cache_control = headers.get("Cache-Control", "")
    require(
        "no-cache" in cache_control or "no-store" in cache_control,
        "SPA index.html can be cached long-term",
    )
    return home


def check_nested_route(base_url: str, home: str) -> None:
    status, nested, headers = fetch(base_url, NESTED_SPA_ROUTE)
    require(status == 200, f"Nested SPA route returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), "Nested SPA route is not HTML")
    require(nested == home, "Nested SPA route did not return the built index.html")


def check_built_asset(base_url: str, home: str) -> None:
    finder = AssetFinder()
    finder.feed(home)
    require(finder.asset_path is not None, "Built SPA index has no /assets/ reference")
    status, _, headers = fetch(base_url, finder.asset_path)
    require(status == 200, f"Built asset {finder.asset_path} returned HTTP {status}")
    content_type = headers.get("Content-Type", "")
    require(
        "javascript" in content_type or "text/css" in content_type,
        f"Built asset has unexpected Content-Type: {content_type}",
    )


def check_missing_asset(base_url: str) -> None:
    status, _, _ = fetch(base_url, MISSING_ASSET_PATH)
    require(status == 404, f"Missing static asset returned HTTP {status}, expected 404")


def check_api(base_url: str, expected_upstream_path: str | None) -> None:
    check_api_health(base_url, expected_upstream_path)
    check_api_prefix_redirect(base_url)


def check_api_health(base_url: str, expected_upstream_path: str | None) -> None:
    status, body, headers = fetch(base_url, "/api/health")
    require(status == 200, f"Gateway API health returned HTTP {status}")
    require("application/json" in headers.get("Content-Type", ""), "Gateway API health is not JSON")
    if expected_upstream_path is None:
        return
    upstream_path = json.loads(body).get("path")
    require(
        upstream_path == expected_upstream_path,
        f"API upstream received {upstream_path!r}, expected {expected_upstream_path!r}",
    )


def check_api_prefix_redirect(base_url: str) -> None:
    status, _, headers = fetch(base_url, "/api")
    require(300 <= status < 400, f"Bare /api returned HTTP {status}, expected a redirect")
    request_url = gateway_url(base_url, "/api")
    target = urljoin(request_url, headers.get("Location", ""))
    expected = gateway_url(base_url, "/api/")
    require(target == expected, f"Bare /api redirects to {target}, expected {expected}")


def check_direct_api(direct_api_url: str) -> None:
    status, _, _ = fetch(direct_api_url, "/health")
    require(status == 200, f"Direct API health returned HTTP {status}")


def check_compose_bindings() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", "docker/docker-compose.yml", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    for name, service in services.items():
        for port in service.get("ports", []):
            require(
                port.get("host_ip") == LOOPBACK_HOST, f"{name} publishes a non-loopback host port"
            )
    for name, published in REQUIRED_HOST_PORTS:
        ports = services.get(name, {}).get("ports", [])
        require(
            any(port.get("published") == published for port in ports),
            f"{name} does not publish host port {published}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--direct-api-url")
    parser.add_argument("--expected-upstream-path")
    parser.add_argument("--check-compose-bindings", action="store_true")
    args = parser.parse_args()

    try:
        if args.check_compose_bindings:
            check_compose_bindings()
        check_spa(args.base_url)
        check_api(args.base_url, args.expected_upstream_path)
        if args.direct_api_url:
            check_direct_api(args.direct_api_url)
    except (AssertionError, KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Nginx smoke check failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print("Nginx smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
