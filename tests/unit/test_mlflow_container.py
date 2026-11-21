"""Unit tests for the local MLflow tracking server container configuration (#205)."""

import re
import tomllib
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
COMPOSE_FILE = DOCKER_DIR / "docker-compose.yml"
DOCKERFILE = DOCKER_DIR / "Dockerfile.mlflow"
UV_LOCK = REPO_ROOT / "uv.lock"


def _compose_backend_store_uri() -> str:
    matches = re.findall(
        r"^\s*BACKEND_STORE_URI:\s*(\S+)\s*$",
        COMPOSE_FILE.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert len(matches) == 1, f"expected one BACKEND_STORE_URI in compose, found {matches}"
    return matches[0]


def test_compose_backend_store_uri_names_the_installed_postgres_driver() -> None:
    """URI 須明確指定 psycopg2；未指定時 SQLAlchemy 2.1 預設改用未安裝的 psycopg v3。"""
    url = make_url(_compose_backend_store_uri())
    assert url.get_backend_name() == "postgresql"
    assert url.drivername == "postgresql+psycopg2"


def _locked_version(package: str) -> str:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    versions = [entry["version"] for entry in lock["package"] if entry["name"] == package]
    assert len(versions) == 1, f"expected one {package} entry in uv.lock, found {versions}"
    return versions[0]


@pytest.mark.parametrize("package", ["mlflow", "psycopg2-binary", "sqlalchemy"])
def test_dockerfile_pins_tracking_server_packages_to_the_lockfile(package: str) -> None:
    """映像重建時不隨上游預設值變更，且 tracking server 與專案內 MLflow client 同版本。"""
    pins = re.findall(
        rf"(?<![\w-]){re.escape(package)}==(\S+)",
        DOCKERFILE.read_text(encoding="utf-8"),
    )
    assert pins == [_locked_version(package)]
