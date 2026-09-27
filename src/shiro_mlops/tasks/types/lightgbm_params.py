"""Hyperparameters shared by the LightGBM regression and classification task types."""

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt


class LightGBMParams(BaseModel):
    """Tunable LightGBM parameters; each task type fixes its own objective and seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: PositiveInt
    learning_rate: PositiveFloat
    num_leaves: int = Field(ge=2)
