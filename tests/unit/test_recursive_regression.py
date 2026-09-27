"""Public-interface tests for the recursive_regression task type, fed with in-memory frames."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import PredictionData, TrainingData, WeatherInput
from shiro_mlops.tasks.types.recursive_regression import RecursiveRegressionParams
from tests.helpers import hourly_load_with_weather

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
TRAINING_HOURS = 24 * 21
HORIZON_HOURS = 6
PARAMS = RecursiveRegressionParams.model_validate(
    {
        "lags": [1, 2, 24, 48, 168],
        "rolling_windows": [6, 24],
        "model": {"n_estimators": 30, "learning_rate": 0.1, "num_leaves": 15},
    }
)
task_type = get_task_type("recursive_regression")


def _training_data(validation_start: pd.Timestamp | None = None) -> TrainingData:
    load, weather = hourly_load_with_weather(TRAINING_HOURS, LAST_HOUR)
    split = validation_start or load["datetime"].iloc[int(len(load) * 0.8)]
    return TrainingData(load=load, weather=weather, validation_start=split)


def _prediction_data(load: pd.DataFrame, temperature_shift: float = 0.0) -> PredictionData:
    anchor = load["datetime"].max()
    future = pd.date_range(anchor + pd.Timedelta(hours=1), periods=HORIZON_HOURS, freq="h")
    _, weather = hourly_load_with_weather(HORIZON_HOURS, future[-1].to_pydatetime())
    history = load[load["datetime"] > anchor - pd.Timedelta(hours=PARAMS.lookback_hours + 1)]
    return PredictionData(
        anchor=anchor,
        load_history=history,
        weather=weather.assign(temperature=weather["temperature"] + temperature_shift),
        horizon_hours=HORIZON_HOURS,
    )


@pytest.fixture(scope="module")
def trained():
    return task_type.train(PARAMS, _training_data())


def test_requirements_ask_for_forecast_weather_and_the_longest_lag_or_window() -> None:
    requirements = task_type.requirements(PARAMS)

    assert requirements.weather is WeatherInput.FORECAST
    assert requirements.lookback_hours == 168


def test_trains_from_dataframes_and_reports_out_of_time_metrics(trained) -> None:
    assert set(trained.metrics) == {"mape", "rmse", "mae"}
    assert 0.0 < trained.metrics["mape"] < 5.0


def test_predicts_each_horizon_hour_after_the_anchor(trained) -> None:
    load = _training_data().load
    data = _prediction_data(load)

    predictions = trained.model.predict(data)

    expected_times = pd.date_range(
        data.anchor + pd.Timedelta(hours=1), periods=HORIZON_HOURS, freq="h"
    )
    assert list(predictions["datetime"]) == list(expected_times)
    assert predictions["predicted_load_mw"].between(20000.0, 40000.0).all()


def test_predictions_follow_the_supplied_weather(trained) -> None:
    load = _training_data().load

    baseline = trained.model.predict(_prediction_data(load))
    hotter = trained.model.predict(_prediction_data(load, temperature_shift=8.0))

    assert not np.allclose(baseline["predicted_load_mw"], hotter["predicted_load_mw"])


def test_missing_weather_field_fails_instead_of_using_a_constant(trained) -> None:
    data = _prediction_data(_training_data().load)
    without_humidity = PredictionData(
        anchor=data.anchor,
        load_history=data.load_history,
        weather=data.weather.drop(columns=["relative_humidity"]),
        horizon_hours=HORIZON_HOURS,
    )

    with pytest.raises(KeyError, match="relative_humidity"):
        trained.model.predict(without_humidity)


def test_saved_model_reloads_with_identical_predictions(trained, tmp_path: Path) -> None:
    data = _prediction_data(_training_data().load)

    trained.model.save(tmp_path / "model")
    reloaded = task_type.load(tmp_path / "model")

    pd.testing.assert_frame_equal(reloaded.predict(data), trained.model.predict(data))
    assert sorted(path.name for path in (tmp_path / "model").iterdir()) == [
        "metadata.json",
        "model.txt",
    ]


def test_validation_split_after_all_rows_leaves_metrics_empty() -> None:
    after_last_row = pd.Timestamp(LAST_HOUR) + pd.Timedelta(hours=1)

    result = task_type.train(PARAMS, _training_data(validation_start=after_last_row))

    assert result.metrics == {"mape": 0.0, "rmse": 0.0, "mae": 0.0}


def test_validation_split_before_all_rows_refuses_to_train() -> None:
    before_first_row = pd.Timestamp(LAST_HOUR) - pd.Timedelta(days=30)

    with pytest.raises(ValueError, match="No training rows"):
        task_type.train(PARAMS, _training_data(validation_start=before_first_row))
