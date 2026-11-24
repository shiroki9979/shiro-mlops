"""Per-task model directories: atomic replacement, content hashes and no legacy joblib loading."""

import builtins
import ctypes
import errno
import io
import os
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest

from shiro_mlops.tasks import model_store
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import (
    MissingModelLockError,
    has_installed_model,
    load_model,
    load_model_with_sha256,
    model_directory_sha256,
    save_model,
)


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

    assert saved.directory == root / "sample_task"
    assert (saved.directory / "version.txt").read_text(encoding="utf-8") == "v1"


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


def _stub_renameat2(monkeypatch: pytest.MonkeyPatch, renameat2: Callable[..., int]) -> None:
    """Replace the C library lookup, the only OS boundary the atomic exchange crosses."""
    monkeypatch.setattr(
        ctypes, "CDLL", lambda *_args, **_kwargs: SimpleNamespace(renameat2=renameat2)
    )


def _failing_renameat2(error: int) -> Callable[..., int]:
    def renameat2(*_args: object) -> int:
        ctypes.set_errno(error)
        return -1

    return renameat2


def test_failed_atomic_exchange_keeps_the_previous_model(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))
    _stub_renameat2(monkeypatch, _failing_renameat2(errno.EIO))

    with pytest.raises(OSError, match="Input/output error"):
        save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v1"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


@pytest.mark.parametrize("unsupported", [errno.ENOSYS, errno.EINVAL])
def test_resaving_without_atomic_exchange_support_still_replaces_the_model(
    root: Path, monkeypatch: pytest.MonkeyPatch, unsupported: int
) -> None:
    """Retraining still replaces models on non-Linux or filesystems without RENAME_EXCHANGE."""
    save_model(root, "sample_task", _RecordingModel("v1"))
    _stub_renameat2(monkeypatch, _failing_renameat2(unsupported))

    save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v2"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


def test_saving_after_an_interrupted_swap_installs_the_model_and_clears_the_old_one(
    root: Path,
) -> None:
    """Saving after an interrupted two-rename swap restores the model and removes the orphaned old directory."""
    leftover = root / ".sample_task.previous"
    leftover.mkdir()
    (leftover / "version.txt").write_text("v1", encoding="utf-8")

    save_model(root, "sample_task", _RecordingModel("v2"))

    assert (root / "sample_task" / "version.txt").read_text(encoding="utf-8") == "v2"
    assert [path.name for path in root.iterdir() if path.is_dir()] == ["sample_task"]


def test_reader_waits_for_model_replacement(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader waits for the writer's exclusive lock and then reads the replacement model."""
    save_model(root, "sample_task", _RecordingModel("v1"))
    swapping = Event()
    resume = Event()
    reading = Event()

    def pause_then_report_unsupported(*_args: object) -> int:
        swapping.set()
        assert resume.wait(3)
        ctypes.set_errno(errno.ENOSYS)
        return -1

    def read_model() -> _RecordingModel | None:
        reading.set()
        task = SimpleNamespace(
            task_id="sample_task",
            task_type="recording",
            params=None,
            weather=SimpleNamespace(fields=()),
        )
        return load_model(root, task)

    _stub_renameat2(monkeypatch, pause_then_report_unsupported)
    monkeypatch.setattr(
        model_store,
        "get_task_type",
        lambda _name: SimpleNamespace(
            load=lambda directory, _params, _weather_fields: _RecordingModel(
                (directory / "version.txt").read_text(encoding="utf-8")
            )
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(save_model, root, "sample_task", _RecordingModel("v2"))
        assert swapping.wait(3)
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
    """Under ADR-0010, legacy model.joblib files do not count as models before retraining."""
    (root / "model.joblib").write_bytes(b"legacy pickle bytes")

    assert load_model(root, deployed_task(DYNAMIC_HORIZON_FORECAST)) is None


def _write_files(directory: Path, files: dict[str, bytes]) -> Path:
    for relative, content in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return directory


_MODEL_FILES = {"model.txt": b"booster", "params/task.json": b'{"lags": [1, 24]}'}


def test_model_hash_is_the_full_sha256_hex_digest(tmp_path: Path) -> None:
    digest = model_directory_sha256(_write_files(tmp_path / "model", _MODEL_FILES))

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_same_model_files_give_the_same_hash_wherever_and_in_whatever_order_they_were_written(
    tmp_path: Path,
) -> None:
    first = _write_files(tmp_path / "first", _MODEL_FILES)
    second = _write_files(tmp_path / "second", dict(reversed(list(_MODEL_FILES.items()))))

    assert model_directory_sha256(first) == model_directory_sha256(second)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"model.txt": b"booster v2"}, id="content-changed"),
        pytest.param({"extra.json": b"{}"}, id="file-added"),
    ],
)
def test_changing_or_adding_a_file_changes_the_hash(
    tmp_path: Path, change: dict[str, bytes]
) -> None:
    directory = _write_files(tmp_path / "model", _MODEL_FILES)
    before = model_directory_sha256(directory)

    _write_files(directory, change)

    assert model_directory_sha256(directory) != before


def test_moving_content_to_another_file_name_changes_the_hash(tmp_path: Path) -> None:
    original = _write_files(tmp_path / "original", {"a.txt": b"same"})
    renamed = _write_files(tmp_path / "renamed", {"b.txt": b"same"})

    assert model_directory_sha256(original) != model_directory_sha256(renamed)


def test_file_timestamps_do_not_change_the_hash(tmp_path: Path) -> None:
    directory = _write_files(tmp_path / "model", _MODEL_FILES)
    before = model_directory_sha256(directory)

    for path in directory.rglob("*"):
        os.utime(path, (0, 0))

    assert model_directory_sha256(directory) == before


def _hash_of_saved(tmp_path: Path, version: str) -> str:
    """The hash an independently saved copy of one recorded version has."""
    return save_model(tmp_path / "reference", version, _RecordingModel(version)).sha256


def _stub_recording_task_type(
    monkeypatch: pytest.MonkeyPatch, on_load: Callable[[], None] = lambda: None
) -> None:
    def load(directory: Path, _params: object, _weather_fields: object) -> _RecordingModel:
        model = _RecordingModel((directory / "version.txt").read_text(encoding="utf-8"))
        on_load()
        return model

    monkeypatch.setattr(model_store, "get_task_type", lambda _name: SimpleNamespace(load=load))


_RECORDING_TASK = SimpleNamespace(
    task_id="sample_task", task_type="recording", params=None, weather=SimpleNamespace(fields=())
)


def test_saving_reports_the_hash_of_the_installed_model(root: Path, tmp_path: Path) -> None:
    saved = save_model(root, "sample_task", _RecordingModel("v1"))

    assert saved.sha256 == _hash_of_saved(tmp_path, "v1")
    assert saved.sha256 == model_directory_sha256(root / "sample_task")


def test_loading_returns_the_model_with_the_hash_of_its_directory(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_model(root, "sample_task", _RecordingModel("v1"))
    _stub_recording_task_type(monkeypatch)

    loaded = load_model_with_sha256(root, _RECORDING_TASK)

    assert loaded is not None
    assert loaded.model.version == "v1"
    assert loaded.sha256 == _hash_of_saved(tmp_path, "v1")


def test_untrained_task_loads_no_model_and_no_hash(root: Path) -> None:
    assert load_model_with_sha256(root, _RECORDING_TASK) is None


def test_retraining_during_a_load_cannot_pair_the_loaded_model_with_another_hash(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swap requested mid-load waits until both the model and its hash are read."""
    save_model(root, "sample_task", _RecordingModel("v1"))
    expected = _hash_of_saved(tmp_path, "v1")

    with ThreadPoolExecutor(max_workers=1) as executor:
        writers = []

        def retrain_mid_load() -> None:
            writer = executor.submit(save_model, root, "sample_task", _RecordingModel("v2"))
            writers.append(writer)
            with pytest.raises(FutureTimeoutError):
                writer.result(timeout=0.2)

        _stub_recording_task_type(monkeypatch, on_load=retrain_mid_load)
        loaded = load_model_with_sha256(root, _RECORDING_TASK)
        writers[0].result()

    assert loaded is not None
    assert (loaded.model.version, loaded.sha256) == ("v1", expected)
    assert model_directory_sha256(root / "sample_task") == _hash_of_saved(tmp_path, "v2")


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _mount_read_only(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Refuse every write or create under ``root`` as a read-only mount does, even for root users."""

    def refuse(path) -> None:
        if Path(path).is_relative_to(root):
            raise OSError(errno.EROFS, os.strerror(errno.EROFS), str(path))

    real_os_open, real_io_open = os.open, io.open

    def os_open(path, flags, *args, **kwargs):
        if flags & _WRITE_FLAGS:
            refuse(path)
        return real_os_open(path, flags, *args, **kwargs)

    def io_open(file, mode="r", *args, **kwargs):
        if isinstance(file, str | os.PathLike) and set(mode) & set("wax+"):
            refuse(file)
        return real_io_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(io, "open", io_open)
    monkeypatch.setattr(builtins, "open", io_open)


def test_trained_task_loads_from_a_read_only_model_root(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API mounts the models read-only; a shared lock must not need write access (#204)."""
    save_model(root, "sample_task", _RecordingModel("v1"))
    _stub_recording_task_type(monkeypatch)
    expected = _hash_of_saved(tmp_path, "v1")
    _mount_read_only(monkeypatch, root)

    loaded = load_model_with_sha256(root, _RECORDING_TASK)

    assert loaded is not None
    assert (loaded.model.version, loaded.sha256) == ("v1", expected)


def test_untrained_task_loads_no_model_from_a_read_only_model_root(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task never trained has no lock file either; a reader must not try to create one."""
    _mount_read_only(monkeypatch, root)

    assert load_model_with_sha256(root, _RECORDING_TASK) is None


def test_model_directory_without_a_lock_file_fails_to_load_instead_of_reading_unlocked(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory copied in by hand was never installed by the store; retraining replaces it."""
    _RecordingModel("hand-copied").save(root / "sample_task")
    _stub_recording_task_type(monkeypatch)
    _mount_read_only(monkeypatch, root)

    with pytest.raises(MissingModelLockError, match="retrain"):
        load_model_with_sha256(root, _RECORDING_TASK)


def test_first_training_finishing_while_a_reader_looks_for_the_lock_still_loads(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer may create the lock and install the model just after the reader missed the lock."""
    _stub_recording_task_type(monkeypatch)
    lock = root / ".sample_task.lock"
    real_os_open = os.open
    first_look = Event()

    def os_open(path, flags, *args, **kwargs):
        if Path(path) == lock and not flags & _WRITE_FLAGS and not first_look.is_set():
            first_look.set()
            missed = FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))
            monkeypatch.setattr(os, "open", real_os_open)
            save_model(root, "sample_task", _RecordingModel("v1"))
            monkeypatch.setattr(os, "open", os_open)
            raise missed
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", os_open)

    loaded = load_model_with_sha256(root, _RECORDING_TASK)

    assert loaded is not None
    assert loaded.model.version == "v1"


def test_presence_counts_only_a_model_the_store_installed(root: Path) -> None:
    """Presence follows the load rule without loading: untrained and hand-copied tasks have none."""
    assert not has_installed_model(root / "absent_root", "sample_task")
    assert not has_installed_model(root, "sample_task")

    _RecordingModel("hand-copied").save(root / "sample_task")
    assert not has_installed_model(root, "sample_task")

    save_model(root, "other_task", _RecordingModel("v1"))
    assert has_installed_model(root, "other_task")


def test_presence_ends_when_the_installed_directory_is_removed(root: Path) -> None:
    """The lock file stays behind; without the directory the task has no model to load."""
    saved = save_model(root, "sample_task", _RecordingModel("v1"))
    shutil.rmtree(saved.directory)

    assert not has_installed_model(root, "sample_task")
    assert load_model_with_sha256(root, _RECORDING_TASK) is None
