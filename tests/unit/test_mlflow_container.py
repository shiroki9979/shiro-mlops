"""Unit tests for the local MLflow tracking server container configuration (#205)."""

import re
import tomllib
from pathlib import Path

import yaml
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


def _dockerfile_shell() -> str:
    """Dockerfile text with line continuations joined, one instruction per line."""
    return DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")


def _locked_packages() -> set[str]:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    return {entry["name"] for entry in lock["package"]}


def test_dockerfile_installs_tracking_server_under_lockfile_constraints() -> None:
    """映像重建時不隨上游預設值變更：所有套件（含 SQLAlchemy 等間接相依）都取 uv.lock 的版本。"""
    shell = _dockerfile_shell()
    exports = re.findall(r"uv export --frozen\b[^&\n]*?-o (\S+)", shell)
    assert len(exports) == 1, f"expected one frozen uv export, found {exports}"
    installs = re.findall(r"uv pip install\b([^&\n]*)", shell)
    assert len(installs) == 1, f"expected one uv pip install, found {installs}"
    args = installs[0].split()
    assert args[args.index("-c") + 1] == exports[0]
    assert "==" not in shell, "versions come from uv.lock, not hand-written pins"


def test_dockerfile_installs_only_packages_the_lockfile_constrains() -> None:
    """constraints 只約束 uv.lock 內的套件；不在 lockfile 的套件會以未鎖版本安裝。"""
    args = re.findall(r"uv pip install\b([^&\n]*)", _dockerfile_shell())[0].split()
    packages = [
        arg for i, arg in enumerate(args) if not arg.startswith("-") and args[i - 1] != "-c"
    ]
    assert {"mlflow", "psycopg2-binary"} <= set(packages)
    assert set(packages) <= _locked_packages()


def test_services_waiting_on_mlflow_wait_for_a_passing_healthcheck() -> None:
    """MLflow 遇到無法執行的 schema 會反覆重啟；等到健康才啟動，compose up 才會報出失敗。"""
    services = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]
    assert "healthcheck" in services["mlflow"]
    waits = {
        name: service["depends_on"]["mlflow"]["condition"]
        for name, service in services.items()
        if "mlflow" in service.get("depends_on", {})
    }
    assert waits, "no service waits on mlflow"
    assert set(waits.values()) == {"service_healthy"}, waits
