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
from urllib.request import urlopen


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


def fetch(base_url: str, path: str) -> tuple[int, str, dict[str, str]]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        with urlopen(url, timeout=10) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)
    except HTTPError as error:
        return error.code, error.read().decode("utf-8"), dict(error.headers)
    except URLError as error:
        raise AssertionError(f"Cannot reach {url}: {error.reason}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_spa(base_url: str) -> None:
    status, home, headers = fetch(base_url, "/")
    require(status == 200, f"SPA root returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), "SPA root is not HTML")
    require('<div id="root"></div>' in home, "SPA root document is missing")
    require(
        "no-cache" in headers.get("Cache-Control", "")
        or "no-store" in headers.get("Cache-Control", ""),
        "SPA index.html can be cached long-term",
    )

    status, nested, headers = fetch(base_url, "/data/power/load")
    require(status == 200, f"Nested SPA route returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), "Nested SPA route is not HTML")
    require(nested == home, "Nested SPA route did not return the built index.html")

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

    status, _, _ = fetch(base_url, "/assets/definitely-missing-smoke-check.js")
    require(status == 404, f"Missing static asset returned HTTP {status}, expected 404")


def check_api(base_url: str, expected_upstream_path: str | None) -> None:
    status, body, headers = fetch(base_url, "/api/health")
    require(status == 200, f"Gateway API health returned HTTP {status}")
    require("application/json" in headers.get("Content-Type", ""), "Gateway API health is not JSON")
    if expected_upstream_path is not None:
        payload = json.loads(body)
        require(
            payload.get("path") == expected_upstream_path,
            f"API upstream received {payload.get('path')!r}, expected {expected_upstream_path!r}",
        )


def check_compose_bindings() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "compose", "-f", "docker/docker-compose.yml", "config", "--format", "json"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    for name, service in services.items():
        for port in service.get("ports", []):
            require(
                port.get("host_ip") == "127.0.0.1", f"{name} publishes a non-loopback host port"
            )
    for name, published in (("frontend", "8080"), ("api", "8000")):
        require(
            any(port.get("published") == published for port in services[name]["ports"]),
            f"{name} does not publish host port {published}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
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
            status, _, _ = fetch(args.direct_api_url, "/health")
            require(status == 200, f"Direct API health returned HTTP {status}")
    except (AssertionError, ValueError) as error:
        print(f"Nginx smoke check failed: {error}", file=sys.stderr)
        return 1

    print("Nginx smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
