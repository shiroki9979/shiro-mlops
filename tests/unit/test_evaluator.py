"""Unit tests for evaluation metrics."""

import numpy as np

from shiro_mlops.models.evaluator import (
    evaluate_forecast,
    mean_absolute_error,
    mean_absolute_percentage_error,
    root_mean_squared_error,
)


def test_evaluator_metrics() -> None:
    """Test standard metric computations on known values."""
    y_true = np.array([100.0, 200.0, 300.0])
    y_pred = np.array([110.0, 190.0, 300.0])

    mape = mean_absolute_percentage_error(y_true, y_pred)
    # (|10/100| + |10/200| + |0/300|) / 3 * 100 = (0.1 + 0.05 + 0) / 3 * 100 = 5.0%
    assert np.isclose(mape, 5.0)

    mae = mean_absolute_error(y_true, y_pred)
    # (10 + 10 + 0) / 3 = 6.6667
    assert np.isclose(mae, 20.0 / 3.0)

    rmse = root_mean_squared_error(y_true, y_pred)
    # sqrt((100 + 100 + 0) / 3) = sqrt(200/3) = 8.1649658
    assert np.isclose(rmse, np.sqrt(200.0 / 3.0))

    summary = evaluate_forecast(y_true, y_pred)
    assert "mape" in summary
    assert "rmse" in summary
    assert "mae" in summary
