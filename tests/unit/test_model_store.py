"""Per-task model directories: atomic replacement and no legacy joblib loading."""

from pathlib import Path

import pandas as pd
import pytest

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
    assert [path.name for path in root.iterdir()] == ["sample_task"]


def test_failed_save_keeps_the_previous_model(root: Path) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))

    with pytest.raises(OSError, match="disk full"):
        save_model(root, "sample_task", _RecordingModel("v2", fail=True))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v1"
    assert [path.name for path in root.iterdir()] == ["sample_task"]


def test_untrained_task_loads_no_model_even_beside_a_legacy_joblib(root: Path) -> None:
    """ADR-0010：既有 model.joblib 不提供相容載入，首次重新訓練前任務沒有模型。"""
    (root / "model.joblib").write_bytes(b"legacy pickle bytes")

    assert load_model(root, deployed_task(DYNAMIC_HORIZON_FORECAST)) is None
