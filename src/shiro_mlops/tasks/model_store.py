"""Per-task model directories: the platform assigns ``<root>/<task_id>``; task types own the files.

Only native, non-executable formats are written or read (ADR-0010). A legacy
``model.joblib`` is never loaded; a task without a model directory is simply
untrained until its next training run.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2


def model_directory(root: Path, task_id: str) -> Path:
    """The directory holding the current model of one task."""
    return root / task_id


@contextmanager
def _model_lock(root: Path, task_id: str, *, exclusive: bool) -> Iterator[None]:
    """Serialize model directory swaps with readers across service and training processes."""
    with (root / f".{task_id}.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


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


def save_model(root: Path, task_id: str, model: TaskModel) -> Path:
    """Write the model into staging, then atomically install it on Linux.

    Readers never observe a half-written or missing model. A per-task lock keeps
    readers on one version while the old directory is removed after the swap.
    """
    root.mkdir(parents=True, exist_ok=True)
    target = model_directory(root, task_id)
    token = uuid.uuid4().hex
    staging = root / f".{task_id}.staging-{token}"
    try:
        model.save(staging)
        with _model_lock(root, task_id, exclusive=True):
            if target.exists():
                _exchange_directories(staging, target)
            else:
                staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def load_model(root: Path, task: TaskDefinition) -> TaskModel | None:
    """Load the task's current model, or ``None`` when it has never been trained."""
    if not root.is_dir():
        return None
    directory = model_directory(root, task.task_id)
    with _model_lock(root, task.task_id, exclusive=False):
        if not directory.is_dir():
            return None
        return get_task_type(task.task_type).load(directory)
