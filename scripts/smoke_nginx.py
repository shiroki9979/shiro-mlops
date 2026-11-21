"""Exercise the built local frontend apps through their shared Nginx HTTP entry point.

The Forecast View is served at the root and the Engineering Console under `/console/` (ADR-0014 §2.5).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
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
# The console's Vite `base` (CONSOLE_BASE_PATH in frontend/apps/engineering-console/vite.config.ts),
# which frontend/nginx.conf and frontend/Dockerfile follow too; keep in sync.
CONSOLE_BASE_PATH = "/console/"
MISSING_ASSET_NAME = "definitely-missing-smoke-check.js"

# 預報檢視匯出的兩個固定檔名；此腳本以 `uv run --no-project` 執行、不能 import shiro_mlops，
# 變更時須同步 src/shiro_mlops/data/forecast_view.py 與 tests/fixtures/published/。
PUBLISHED_FILES = ("latest_issued_forecast.json", "forecast_track_record.json")
# 重述 frontend/nginx.conf 中 /published/ 的 add_header Cache-Control；變更時須同步該處。
PUBLISHED_CACHE_CONTROL = "public, max-age=60"
MISSING_PUBLISHED_PATH = "/published/definitely-missing-smoke-check.json"


@dataclass(frozen=True)
class App:
    """One built app on the shared origin, as Nginx serves it."""

    name: str
    base_path: str
    # Client-side routes that must fall back to this app's own index.html.
    routes: tuple[str, ...]

    @property
    def assets_prefix(self) -> str:
        return self.base_path + "assets/"


APPS = (
    App(
        "Forecast View",
        "/",
        # /monitoring is a pre-split console URL: not redirected, so it falls through to the
        # Forecast View like any unknown path.
        ("/history", "/monitoring"),
    ),
    App("Engineering Console", CONSOLE_BASE_PATH, (CONSOLE_BASE_PATH + "data/power/load",)),
)


class AssetFinder(HTMLParser):
    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.prefix = prefix
        self.asset_path: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.asset_path is not None:
            return
        attr = dict(attrs)
        path = attr.get("src") if tag == "script" else attr.get("href")
        if path and path.startswith(self.prefix):
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


def check_apps(base_url: str) -> None:
    served: list[str] = []
    for app in APPS:
        served.append(check_app(base_url, app, served))


def check_app(base_url: str, app: App, other_indexes: list[str]) -> str:
    index = check_app_index(base_url, app)
    require(
        index not in other_indexes,
        f"{app.name} root {app.base_path} serves another app's index.html",
    )
    for route in app.routes:
        check_route_serves(base_url, route, index, app.name)
    check_built_asset(base_url, index, app.assets_prefix)
    check_missing_asset(base_url, app.assets_prefix)
    return index


def check_app_index(base_url: str, app: App) -> str:
    path = app.base_path
    status, document, headers = fetch(base_url, path)
    require(status == 200, f"{app.name} root {path} returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), f"{app.name} root {path} is not HTML")
    require('<div id="root"></div>' in document, f"{app.name} root document is missing at {path}")
    cache_control = headers.get("Cache-Control", "")
    require(
        "no-cache" in cache_control or "no-store" in cache_control,
        f"{app.name} index.html at {path} can be cached long-term",
    )
    return document


def check_route_serves(base_url: str, path: str, expected: str, app: str) -> None:
    status, document, headers = fetch(base_url, path)
    require(status == 200, f"SPA route {path} returned HTTP {status}")
    require("text/html" in headers.get("Content-Type", ""), f"SPA route {path} is not HTML")
    require(document == expected, f"SPA route {path} did not return the {app} index.html")


def check_built_asset(base_url: str, document: str, prefix: str) -> None:
    finder = AssetFinder(prefix)
    finder.feed(document)
    require(finder.asset_path is not None, f"Built index has no {prefix} reference")
    status, _, headers = fetch(base_url, finder.asset_path)
    require(status == 200, f"Built asset {finder.asset_path} returned HTTP {status}")
    content_type = headers.get("Content-Type", "")
    require(
        "javascript" in content_type or "text/css" in content_type,
        f"Built asset has unexpected Content-Type: {content_type}",
    )
    require(
        "immutable" in headers.get("Cache-Control", ""),
        f"Built asset {finder.asset_path} is not cached as immutable",
    )


def check_missing_asset(base_url: str, prefix: str) -> None:
    path = prefix + MISSING_ASSET_NAME
    status, _, _ = fetch(base_url, path)
    require(status == 404, f"Missing static asset {path} returned HTTP {status}, expected 404")


def check_published(base_url: str) -> None:
    for name in PUBLISHED_FILES:
        check_published_file(base_url, f"/published/{name}")
    check_missing_published_file(base_url)


def check_published_file(base_url: str, path: str) -> None:
    status, body, headers = fetch(base_url, path)
    require(status == 200, f"{path} returned HTTP {status}; has the export run yet?")
    require("application/json" in headers.get("Content-Type", ""), f"{path} is not JSON")
    cache_control = headers.get("Cache-Control", "")
    require(
        cache_control == PUBLISHED_CACHE_CONTROL,
        f"{path} has Cache-Control {cache_control!r}, expected {PUBLISHED_CACHE_CONTROL!r}",
    )
    require(isinstance(json.loads(body), dict), f"{path} is not a JSON object")


def check_missing_published_file(base_url: str) -> None:
    """A missing export must not fall back to index.html with 200, as CloudFront does not."""
    status, _, _ = fetch(base_url, MISSING_PUBLISHED_PATH)
    require(status != 200, f"Missing published file {MISSING_PUBLISHED_PATH} returned HTTP 200")


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
        check_apps(args.base_url)
        check_published(args.base_url)
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
