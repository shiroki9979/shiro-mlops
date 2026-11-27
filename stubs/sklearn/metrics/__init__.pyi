from typing import Literal

from numpy.typing import ArrayLike

# average is narrowed to "binary", the only value this repo passes: it keeps the return a float,
# where sklearn also accepts None and returns one score per class as an ndarray.

def precision_score(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    *,
    labels: ArrayLike | None = None,
    pos_label: int | str = 1,
    average: Literal["binary"] = "binary",
    sample_weight: ArrayLike | None = None,
    zero_division: float | Literal["warn"] = "warn",
) -> float: ...
def recall_score(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    *,
    labels: ArrayLike | None = None,
    pos_label: int | str = 1,
    average: Literal["binary"] = "binary",
    sample_weight: ArrayLike | None = None,
    zero_division: float | Literal["warn"] = "warn",
) -> float: ...
def f1_score(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    *,
    labels: ArrayLike | None = None,
    pos_label: int | str = 1,
    average: Literal["binary"] = "binary",
    sample_weight: ArrayLike | None = None,
    zero_division: float | Literal["warn"] = "warn",
) -> float: ...
