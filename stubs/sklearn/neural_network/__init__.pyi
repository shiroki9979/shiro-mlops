from abc import ABCMeta
from collections.abc import Sequence
from typing import Literal, Self, TypeAlias

import numpy as np
from numpy.typing import ArrayLike

_Activation: TypeAlias = Literal["identity", "logistic", "tanh", "relu"]
# One (fan_in, fan_out) weight matrix and one fan_out bias vector per layer; model.npz stores them
# as they are (ADR-0010).
_Weights: TypeAlias = list[np.ndarray[tuple[int, int], np.dtype[np.float64]]]
_Biases: TypeAlias = list[np.ndarray[tuple[int], np.dtype[np.float64]]]

class MLPRegressor(metaclass=ABCMeta):
    activation: _Activation
    out_activation_: str
    coefs_: _Weights
    intercepts_: _Biases
    def __init__(
        self,
        loss: Literal["squared_error", "poisson"] = "squared_error",
        hidden_layer_sizes: Sequence[int] = (100,),
        activation: _Activation = "relu",
        *,
        solver: Literal["lbfgs", "sgd", "adam"] = "adam",
        alpha: float = 0.0001,
        batch_size: int | Literal["auto"] = "auto",
        learning_rate: Literal["constant", "invscaling", "adaptive"] = "constant",
        learning_rate_init: float = 0.001,
        power_t: float = 0.5,
        max_iter: int = 200,
        shuffle: bool = True,
        random_state: int | np.random.RandomState | None = None,
        tol: float = 0.0001,
        verbose: bool = False,
        warm_start: bool = False,
        momentum: float = 0.9,
        nesterovs_momentum: bool = True,
        early_stopping: bool = False,
        validation_fraction: float = 0.1,
        beta_1: float = 0.9,
        beta_2: float = 0.999,
        epsilon: float = 1e-08,
        n_iter_no_change: int = 10,
        max_fun: int = 15000,
    ) -> None: ...
    def fit(
        self,
        X: ArrayLike,  # noqa: N803 - stubtest requires sklearn's own parameter name
        y: ArrayLike,
        sample_weight: ArrayLike | None = None,
    ) -> Self: ...
