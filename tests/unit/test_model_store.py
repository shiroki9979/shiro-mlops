"""Per-task model directories: atomic replacement and no legacy joblib loading."""

import errno
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest

from shiro_mlops.tasks import model_store
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import load_model, save_model


@pytest.fixture
def root(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    models.mkdir()
    return models


class _RecordingModel:
    """A task model double whose saved files reveal which version was written."""

    def __init__(self, version: str, fail: bool = False):
        self.version = version
        self.fail = fail

    def predict(self, data) -> pd.DataFrame:  # pragma: no cover - never called
        raise NotImplementedError

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        (directory / "version.txt").write_text(self.version, encoding="utf-8")
        if self.fail:
            raise OSError("disk full")


def test_saves_into_the_task_directory(root: Path) -> None:
    saved = save_model(root, "sample_task", _RecordingModel("v1"))

    assert saved == root / "sample_task"
    assert (saved / "version.txt").read_text(encoding="utf-8") == "v1"


def test_resaving_replaces_the_previous_model_and_leaves_no_staging_files(root: Path) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))

    save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v2"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


def test_failed_save_keeps_the_previous_model(root: Path) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))

    with pytest.raises(OSError, match="disk full"):
        save_model(root, "sample_task", _RecordingModel("v2", fail=True))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v1"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


def test_failed_atomic_exchange_keeps_the_previous_model(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))

    def fail_exchange(_staging: Path, _target: Path) -> None:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(model_store, "_exchange_directories", fail_exchange)

    with pytest.raises(OSError, match="Input/output error"):
        save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v1"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


@pytest.mark.parametrize("unsupported", [errno.ENOSYS, errno.EINVAL])
def test_resaving_without_atomic_exchange_support_still_replaces_the_model(
    root: Path, monkeypatch: pytest.MonkeyPatch, unsupported: int
) -> None:
    """非 Linux 核心或不支援 RENAME_EXCHANGE 的檔案系統仍須能重新訓練。"""
    save_model(root, "sample_task", _RecordingModel("v1"))

    def exchange_unsupported(_staging: Path, _target: Path) -> None:
        raise OSError(unsupported, "exchange unsupported")

    monkeypatch.setattr(model_store, "_exchange_directories", exchange_unsupported)

    save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v2"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


def test_reader_waits_for_model_replacement(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))
    swapped = Event()
    resume = Event()
    reading = Event()
    install = model_store._install

    def pause_after_install(staging: Path, target: Path) -> None:
        install(staging, target)
        swapped.set()
        assert resume.wait(3)

    def read_model() -> _RecordingModel | None:
        reading.set()
        return load_model(root, SimpleNamespace(task_id="sample_task", task_type="recording"))

    monkeypatch.setattr(model_store, "_install", pause_after_install)
    monkeypatch.setattr(
        model_store,
        "get_task_type",
        lambda _name: SimpleNamespace(
            load=lambda directory: _RecordingModel(
                (directory / "version.txt").read_text(encoding="utf-8")
            )
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(save_model, root, "sample_task", _RecordingModel("v2"))
        assert swapped.wait(3)
        reader = executor.submit(read_model)
        try:
            assert reading.wait(3)
            with pytest.raises(FutureTimeoutError):
                reader.result(timeout=0.1)
        finally:
            resume.set()
        writer.result()
        assert reader.result().version == "v2"


def test_untrained_task_loads_no_model_even_beside_a_legacy_joblib(root: Path) -> None:
    """ADR-0010：既有 model.joblib 不提供相容載入，首次重新訓練前任務沒有模型。"""
    (root / "model.joblib").write_bytes(b"legacy pickle bytes")

    assert load_model(root, deployed_task(DYNAMIC_HORIZON_FORECAST)) is None
