"""Public-interface tests for the recursive_regression task type, fed with in-memory frames."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shiro_mlops.features.transformers import (
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
)
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import (
    HealthStatus,
    PredictionData,
    TrainingData,
    WeatherInput,
)
from shiro_mlops.tasks.types.recursive_regression import (
    RecursiveRegressionModel,
    RecursiveRegressionParams,
    training_features,
)
from tests.helpers import OFFICIAL_2026_WEEKDAY_DAYS_OFF, hourly_load_with_weather

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


@pytest.mark.parametrize("field", ["temperature", "relative_humidity"])
def test_trains_and_predicts_with_a_single_weather_field(field: str) -> None:
    """A task may declare one weather field; the absent one must not empty the training rows."""
    full = _training_data()
    data = TrainingData(
        load=full.load,
        weather=full.weather[["datetime", field]],
        validation_start=full.validation_start,
    )

    trained = task_type.train(PARAMS, data)

    assert trained.model.weather_columns == [field]
    assert field in trained.model.feature_names
    absent = {"temperature", "relative_humidity"} - {field}
    assert absent.isdisjoint(trained.model.feature_names)
    assert trained.metrics["mape"] < 5.0
    prediction_data = _prediction_data(full.load)
    forecast = trained.model.predict(
        PredictionData(
            anchor=prediction_data.anchor,
            load_history=prediction_data.load_history,
            weather=prediction_data.weather[["datetime", field]],
            horizon_hours=HORIZON_HOURS,
        )
    )
    assert len(forecast) == HORIZON_HOURS
    assert forecast["predicted_load_mw"].notna().all()


def test_saved_model_reloads_with_identical_predictions(trained, tmp_path: Path) -> None:
    data = _prediction_data(_training_data().load)

    trained.model.save(tmp_path / "model")
    reloaded = task_type.load(tmp_path / "model")

    pd.testing.assert_frame_equal(reloaded.predict(data), trained.model.predict(data))
    assert sorted(path.name for path in (tmp_path / "model").iterdir()) == [
        "metadata.json",
        "model.txt",
    ]


def test_validation_split_after_all_rows_reports_no_metrics_so_health_warns() -> None:
    """Without validation rows, reporting zero MAPE would make an unmeasured model appear healthy."""
    after_last_row = pd.Timestamp(LAST_HOUR) + pd.Timedelta(hours=1)
    thresholds = task_type.health_model.model_validate({"max_mape": 10.0})

    result = task_type.train(PARAMS, _training_data(validation_start=after_last_row))

    assert result.metrics == {}
    assert task_type.assess_health(thresholds, result.metrics).status is HealthStatus.WARNING


def test_validation_split_before_all_rows_refuses_to_train() -> None:
    before_first_row = pd.Timestamp(LAST_HOUR) - pd.Timedelta(days=30)

    with pytest.raises(ValueError, match="No training rows"):
        task_type.train(PARAMS, _training_data(validation_start=before_first_row))


def test_rows_beyond_a_two_hour_weather_gap_are_dropped_not_synthesized() -> None:
    """Observed weather can fill at most two past hours; missing validation weather cannot use constants or future values."""
    data = _training_data()
    weather_until = data.validation_start - pd.Timedelta(hours=3)
    gapped = TrainingData(
        load=data.load,
        weather=data.weather[data.weather["datetime"] <= weather_until],
        validation_start=data.validation_start,
    )

    result = task_type.train(PARAMS, gapped)

    assert result.metrics == {}


@pytest.mark.parametrize(
    ("mape", "expected"),
    [(9.99, HealthStatus.HEALTHY), (10.0, HealthStatus.WARNING), (25.0, HealthStatus.WARNING)],
)
def test_health_compares_validation_mape_with_the_configured_ceiling(
    mape: float, expected: HealthStatus
) -> None:
    thresholds = task_type.health_model.model_validate({"max_mape": 10.0})

    assessment = task_type.assess_health(thresholds, {"mape": mape, "rmse": 1.0, "mae": 1.0})

    assert assessment.status is expected
    assert "max_mape" in assessment.reason


def test_health_without_a_mape_metric_warns_instead_of_passing() -> None:
    thresholds = task_type.health_model.model_validate({"max_mape": 10.0})

    assessment = task_type.assess_health(thresholds, {"rmse": 1.0})

    assert assessment.status is HealthStatus.WARNING
    assert "mape" in assessment.reason


DAY_OFF_DROP_MW = 4000.0
# 2026-01-01 至 10-08：涵蓋 13 個落在平日的放假日，模型才看得到放假日與週末的差別。
DAY_OFF_TRAINING_HOURS = 281 * 24
DAY_OFF_PARAMS = RecursiveRegressionParams.model_validate({**PARAMS.model_dump(), "day_off": True})


def _load_with_days_off(last_hour: datetime, hours: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Patterned load that is DAY_OFF_DROP_MW lower on every 2026 office-calendar day off."""
    load, weather = hourly_load_with_weather(hours, last_hour)
    dates = load["datetime"].dt.strftime("%Y-%m-%d")
    is_day_off = (load["datetime"].dt.dayofweek >= 5) | dates.isin(OFFICIAL_2026_WEEKDAY_DAYS_OFF)
    return load.assign(load_mw=load["load_mw"] - DAY_OFF_DROP_MW * is_day_off), weather


def test_day_off_recipe_forecasts_the_drop_on_a_substitute_holiday() -> None:
    """2026-10-09 (Fri) is the National Day substitute holiday; lag and weekday say workday."""
    load, weather = _load_with_days_off(datetime(2026, 10, 8, 23, 0), DAY_OFF_TRAINING_HOURS)
    trained = task_type.train(
        DAY_OFF_PARAMS, TrainingData(load, weather, load["datetime"].iloc[-48])
    )
    actual, future_weather = _load_with_days_off(datetime(2026, 10, 9, 23, 0), 24)

    predictions = trained.model.predict(
        PredictionData(
            anchor=load["datetime"].max(),
            load_history=load,
            weather=future_weather,
            horizon_hours=24,
        )
    )

    errors = predictions["predicted_load_mw"].to_numpy() - actual["load_mw"].to_numpy()
    # 不用放假日特徵時誤差約等於整個降幅（模型照上班日預測）。
    assert np.abs(errors).mean() < DAY_OFF_DROP_MW / 2


def test_day_off_recipe_survives_save_and_load(tmp_path: Path) -> None:
    load, weather = _load_with_days_off(datetime(2026, 10, 8, 23, 0), DAY_OFF_TRAINING_HOURS)
    trained = task_type.train(
        DAY_OFF_PARAMS, TrainingData(load, weather, load["datetime"].iloc[-48])
    )
    _, future_weather = _load_with_days_off(datetime(2026, 10, 9, 23, 0), 24)
    data = PredictionData(
        anchor=load["datetime"].max(), load_history=load, weather=future_weather, horizon_hours=24
    )

    trained.model.save(tmp_path)
    reloaded = task_type.load(tmp_path)

    pd.testing.assert_frame_equal(reloaded.predict(data), trained.model.predict(data))


# --- step features against the training recipe ---------------------------------------------


def _recompute_everything_each_step(
    model: RecursiveRegressionModel, data: PredictionData
) -> list[float]:
    """The roll-forward spelled out with the training transformers over the whole buffer."""
    buffer = data.load_history[["datetime", "load_mw"]].sort_values("datetime")
    predictions: list[float] = []
    for _, step in data.weather.sort_values("datetime").head(data.horizon_hours).iterrows():
        candidate = pd.DataFrame([{"datetime": step["datetime"], "load_mw": np.nan}])
        extended = pd.concat([buffer, candidate], ignore_index=True)
        extended = create_calendar_features(extended, day_off=model.day_off)
        extended = create_lag_features(extended, lags=model.lags)
        extended = create_rolling_features(extended, windows=model.rolling_windows)
        row = extended.iloc[[-1]].copy()
        for column in model.weather_columns:
            row[column] = float(step[column])
        value = float(model.booster.predict(row[model.feature_names])[0])
        predictions.append(value)
        buffer = pd.concat(
            [buffer, pd.DataFrame([{"datetime": step["datetime"], "load_mw": value}])],
            ignore_index=True,
        )
    return predictions


def _week_ahead(load: pd.DataFrame, history: pd.DataFrame) -> PredictionData:
    anchor = load["datetime"].max()
    future = pd.date_range(anchor + pd.Timedelta(hours=1), periods=168, freq="h")
    _, weather = hourly_load_with_weather(168, future[-1].to_pydatetime())
    return PredictionData(anchor=anchor, load_history=history, weather=weather, horizon_hours=168)


def test_week_ahead_forecast_matches_recomputing_every_feature_each_step(trained) -> None:
    load = _training_data().load
    data = _week_ahead(load, load.tail(PARAMS.lookback_hours))

    forecast = trained.model.predict(data)

    assert forecast["datetime"].tolist() == data.weather["datetime"].tolist()
    assert forecast["predicted_load_mw"].to_numpy() == pytest.approx(
        _recompute_everything_each_step(trained.model, data), rel=1e-9
    )


def test_forecast_over_gappy_history_matches_recomputing_every_feature(trained) -> None:
    """Missing hours stay missing for lags and thin out the rolling windows; nothing shifts."""
    load = _training_data().load
    history = load.tail(PARAMS.lookback_hours).reset_index(drop=True)
    history = history.drop(index=[3, 4, 5, 100, 166]).sample(frac=1.0, random_state=3)
    history.loc[history.index[10], "load_mw"] = np.nan
    data = _week_ahead(load, history)

    forecast = trained.model.predict(data)

    assert forecast["predicted_load_mw"].to_numpy() == pytest.approx(
        _recompute_everything_each_step(trained.model, data), rel=1e-9
    )


def test_one_step_features_equal_the_training_row_for_that_hour(trained) -> None:
    """Train/serve parity: an hour forecast from actual history sees its own training features."""
    data = _training_data()
    features = training_features(PARAMS, data)
    target = features.iloc[-1]
    history = data.load[data.load["datetime"] < target["datetime"]]
    weather = data.weather[data.weather["datetime"] == target["datetime"]]

    forecast = trained.model.predict(
        PredictionData(
            anchor=history["datetime"].max(),
            load_history=history,
            weather=weather,
            horizon_hours=1,
        )
    )

    expected = trained.model.booster.predict(features.iloc[[-1]][trained.model.feature_names])
    assert forecast["predicted_load_mw"].iloc[0] == pytest.approx(expected[0], rel=1e-9)


def test_forecast_reads_timezone_aware_times_as_taiwan_local(trained) -> None:
    load = _training_data().load
    naive = _week_ahead(load, load.tail(PARAMS.lookback_hours))
    aware = PredictionData(
        anchor=naive.anchor,
        load_history=naive.load_history.assign(
            datetime=naive.load_history["datetime"].dt.tz_localize("Asia/Taipei")
        ),
        weather=naive.weather,
        horizon_hours=24,
    )

    forecast = trained.model.predict(aware)

    assert forecast["predicted_load_mw"].to_numpy() == pytest.approx(
        trained.model.predict(naive)["predicted_load_mw"].to_numpy()[:24], rel=1e-9
    )


def test_empty_weather_yields_an_empty_forecast(trained) -> None:
    load = _training_data().load
    data = _prediction_data(load)

    forecast = trained.model.predict(
        PredictionData(
            anchor=data.anchor,
            load_history=data.load_history,
            weather=data.weather.head(0),
            horizon_hours=HORIZON_HOURS,
        )
    )

    assert list(forecast.columns) == ["datetime", "predicted_load_mw"]
    assert forecast.empty
