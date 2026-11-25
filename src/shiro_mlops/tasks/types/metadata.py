"""JSON metadata beside each native model file (ADR-0010).

Every task type stamps its name and format version, and refuses on load a model
written by another task type or format, so a wrong directory fails loudly
instead of predicting with mismatched arrays.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METADATA_FILE = "metadata.json"


@dataclass(frozen=True)
class ModelFormat:
    """Which task type wrote a model directory, and in which layout version."""

    task_type: str
    version: int


def write_metadata(directory: Path, model_format: ModelFormat, fields: Mapping[str, Any]) -> None:
    metadata = {"format_version": model_format.version, "task_type": model_format.task_type}
    metadata.update(fields)
    (directory / METADATA_FILE).write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def read_metadata(directory: Path, model_format: ModelFormat) -> dict[str, Any]:
    metadata: dict[str, Any] = json.loads((directory / METADATA_FILE).read_text(encoding="utf-8"))
    if metadata.get("task_type") != model_format.task_type:
        raise ValueError(
            f"Model in {directory} belongs to task type {metadata.get('task_type')!r}, "
            f"not {model_format.task_type!r}"
        )
    if metadata.get("format_version") != model_format.version:
        raise ValueError(
            f"Unsupported model format version {metadata.get('format_version')!r} in {directory}"
        )
    return metadata
