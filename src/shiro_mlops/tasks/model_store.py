"""Per-task model directories: the platform assigns ``<root>/<task_id>``; task types own the files.

Only native, non-executable formats are written or read (ADR-0010). A legacy
``model.joblib`` is never loaded; a task without a model directory is simply
untrained until its next training run.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
# 核心沒有 renameat2（如 macOS）或檔案系統不支援 RENAME_EXCHANGE 時改以 rename 模擬交換。
_EXCHANGE_UNSUPPORTED = frozenset({errno.ENOSYS, errno.EINVAL})


def model_directory(root: Path, task_id: str) -> Path:
    """The directory holding the current model of one task."""
    return root / task_id


def model_directory_sha256(directory: Path) -> str:
    """Identify a model version by its files alone, independent of MLflow.

    Files are visited in order of their relative POSIX path; each contributes its
    UTF-8 path, a NUL byte, its size as 8-byte big-endian and its content. Timestamps
    and listing order therefore never change the 64-character hex digest.
    """
    files = sorted(
        (path.relative_to(directory).as_posix(), path)
        for path in directory.rglob("*")
        if path.is_file()
    )
    digest = hashlib.sha256()
    for relative, path in files:
        content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class MissingModelLockError(RuntimeError):
    """A model directory has no lock file, so the model store never installed it."""


def _lock_path(root: Path, task_id: str) -> Path:
    return root / f".{task_id}.lock"


@contextmanager
def _holding(descriptor: int, operation: int) -> Iterator[None]:
    try:
        fcntl.flock(descriptor, operation)
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_lock(root: Path, task_id: str) -> Iterator[None]:
    """Serialize a model directory swap with readers across service and training processes."""
    descriptor = os.open(_lock_path(root, task_id), os.O_RDWR | os.O_CREAT, 0o666)
    with _holding(descriptor, fcntl.LOCK_EX):
        yield


@contextmanager
def _shared_lock(root: Path, task_id: str) -> Iterator[bool]:
    """Hold the task's lock as a reader; yields ``False``, holding nothing, when it is untrained."""
    descriptor = _open_lock_for_reading(root, task_id)
    if descriptor is None:
        yield False
        return
    with _holding(descriptor, fcntl.LOCK_SH):
        yield True


def _open_lock_for_reading(root: Path, task_id: str) -> int | None:
    """Open the lock read-only, since ``LOCK_SH`` needs no write access and the API mounts the models read-only.

    Only a writer creates the lock file, before installing the first model, so a
    missing lock file beside a missing model directory means the task is untrained.
    A directory found after the lock was missing may be a first training finishing
    meanwhile, so the lock is looked for once more before the directory is rejected.
    """
    path = _lock_path(root, task_id)
    try:
        return os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        if not model_directory(root, task_id).exists():
            return None
    try:
        return os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        raise MissingModelLockError(
            f"{model_directory(root, task_id)} has no {path.name}, so the model store did not"
            " install it; retrain the task to replace it."
        ) from None


def _exchange_directories(staging: Path, target: Path) -> None:
    """Atomically exchange two non-empty directories on Linux."""
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "Atomic directory exchange is unavailable")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if (
        renameat2(_AT_FDCWD, os.fsencode(staging), _AT_FDCWD, os.fsencode(target), _RENAME_EXCHANGE)
        != 0
    ):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), f"{staging} <-> {target}")


def _previous_directory(target: Path) -> Path:
    return target.with_name(f".{target.name}.previous")


def _swap_by_renames(staging: Path, target: Path) -> None:
    """Emulate the exchange with renames; readers wait on the lock, so only a crash sees the gap.

    A crash between the renames leaves the task without a model until its next
    training, which clears the stranded old directory before installing.
    """
    previous = _previous_directory(target)
    target.rename(previous)
    try:
        staging.rename(target)
    except OSError:
        previous.rename(target)
        raise
    previous.rename(staging)


def _clear_previous_left_by_a_crash(target: Path) -> None:
    """A crash inside ``_swap_by_renames`` strands the old model; nothing else removes it."""
    previous = _previous_directory(target)
    if previous.exists():
        shutil.rmtree(previous)


def _install(staging: Path, target: Path) -> None:
    """Leave the new model at ``target`` and any previous model at ``staging``.

    Runs under the task's exclusive lock, so clearing a stranded old model races no reader.
    """
    _clear_previous_left_by_a_crash(target)
    if not target.exists():
        staging.rename(target)
        return
    try:
        _exchange_directories(staging, target)
    except OSError as error:
        if error.errno not in _EXCHANGE_UNSUPPORTED:
            raise
        _swap_by_renames(staging, target)


@dataclass(frozen=True)
class SavedModel:
    """Where a model was installed and the hash of the files installed there."""

    directory: Path
    sha256: str


@dataclass(frozen=True)
class LoadedModel:
    """A loaded model paired with the hash of the very directory version it was read from."""

    model: TaskModel
    sha256: str


def save_model(root: Path, task_id: str, model: TaskModel) -> SavedModel:
    """Write the model into staging, then install it under the task's exclusive lock.

    Readers never observe a half-written or missing model. On Linux the swap is
    one atomic exchange; elsewhere it falls back to renames. A per-task lock keeps
    readers on one version while the old directory is removed after the swap.
    The hash is taken from staging, whose files are exactly the ones installed.
    """
    root.mkdir(parents=True, exist_ok=True)
    target = model_directory(root, task_id)
    token = uuid.uuid4().hex
    staging = root / f".{task_id}.staging-{token}"
    try:
        model.save(staging)
        sha256 = model_directory_sha256(staging)
        with _exclusive_lock(root, task_id):
            _install(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return SavedModel(directory=target, sha256=sha256)


def load_model_with_sha256(root: Path, task: TaskDefinition) -> LoadedModel | None:
    """Load the task's current model and hash its directory under one shared lock.

    A swap waits for the lock, so the model and the hash always belong to the same
    directory version. ``None`` when the task has never been trained; raises
    ``MissingModelLockError`` for a model directory the store did not install.
    """
    if not root.is_dir():
        return None
    directory = model_directory(root, task.task_id)
    with _shared_lock(root, task.task_id) as locked:
        if not locked or not directory.is_dir():
            return None
        model = get_task_type(task.task_type).load(directory)
        return LoadedModel(model=model, sha256=model_directory_sha256(directory))


def load_model(root: Path, task: TaskDefinition) -> TaskModel | None:
    """Load the task's current model, or ``None`` when it has never been trained."""
    loaded = load_model_with_sha256(root, task)
    return None if loaded is None else loaded.model
