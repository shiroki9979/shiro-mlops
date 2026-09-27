"""LightGBM settings and native persistence shared by the regression and classification types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from shiro_mlops.tasks.types.metadata import ModelFormat, read_metadata, write_metadata

MODEL_FILE = "model.txt"
# 固定種子讓同一份訓練資料重新訓練時得到相同模型；各任務類型只再補上自己的 objective。
LIGHTGBM_BASE_PARAMS = {"boosting_type": "gbdt", "random_state": 42, "verbose": -1}


class LightGBMParams(BaseModel):
    """Tunable LightGBM parameters; each task type fixes its own objective and seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: PositiveInt
    learning_rate: PositiveFloat
    num_leaves: int = Field(ge=2)


@dataclass(frozen=True)
class NativeBoosterFiles:
    """A booster in LightGBM's native text format beside its JSON metadata (ADR-0010)."""

    model_format: ModelFormat

    def save(self, directory: Path, booster: lgb.Booster, metadata: Mapping[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(directory / MODEL_FILE))
        write_metadata(directory, self.model_format, metadata)

    def load(self, directory: Path) -> tuple[lgb.Booster, dict[str, Any]]:
        """Refuse another task type's or format's directory before reading the booster."""
        metadata = read_metadata(directory, self.model_format)
        return lgb.Booster(model_file=str(directory / MODEL_FILE)), metadata
