"""Public-interface tests for the direct_classification task type (high-load alert)."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import (
    HealthStatus,
    HistoryCoverage,
    ModelRecipeMismatchError,
    PredictionData,
    TrainingData,
    WeatherInput,
)
from shiro_mlops.tasks.types.direct_classification import (
    DirectClassificationParams,
    training_rows,
)
from tests.helpers import hourly_load_with_weather

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
# 門檻窗縮為 7 日，讓測試以 21 日資料就有足夠的完整門檻窗錨點。
WINDOW_DAYS = 7
TRAINING_HOURS = 24 * 21
HORIZON_HOURS = 6
MAX_LEAD_HOURS = 168
PARAMS = DirectClassificationParams.model_validate(
    {
        "threshold": {"window_days": WINDOW_DAYS, "quantile": 0.9},
        "lags": [1, 24, 168],
        "rolling_windows": [6, 24],
        "model": {"n_estimators": 30, "learning_rate": 0.1, "num_leaves": 15},
    }
)
task_type = get_task_type("direct_classification")
WEATHER_FIELDS = ("temperature", "relative_humidity")
HEALTH = {"min_precision": 0.6, "min_recall": 0.5, "min_f1": 0.55}


def _training_data(
    load: pd.DataFrame | None = None, validation_start: pd.Timestamp | None = None
) -> TrainingData:
    default_load, weather = hourly_load_with_weather(TRAINING_HOURS, LAST_HOUR)
    load = default_load if load is None else load
    split = validation_start or load["datetime"].iloc[int(len(load) * 0.8)]
    return TrainingData(load=load, weather=weather, validation_start=split)


def _prediction_data(load: pd.DataFrame, horizon_hours: int = HORIZON_HOURS) -> PredictionData:
    anchor = load["datetime"].max()
    future = pd.date_range(anchor + pd.Timedelta(hours=1), periods=horizon_hours, freq="h")
    _, weather = hourly_load_with_weather(horizon_hours, future[-1].to_pydatetime())
    lookback = task_type.requirements(PARAMS).lookback_hours
    history = load[load["datetime"] >= anchor - pd.Timedelta(hours=lookback)]
    return PredictionData(
        anchor=anchor, load_history=history, weather=weather, horizon_hours=horizon_hours
    )


def _window_load(values: list[float], anchor: pd.Timestamp) -> pd.DataFrame:
    times = pd.date_range(end=anchor, periods=len(values), freq="h")
    return pd.DataFrame({"datetime": times, "subject": "nationwide", "load_mw": values})


@pytest.fixture(scope="module")
def trained():
    return task_type.train(PARAMS, _training_data())


def test_requirements_cover_the_threshold_window_plus_the_longest_lag() -> None:
    requirements = task_type.requirements(PARAMS)

    assert requirements.weather is WeatherInput.FORECAST
    assert requirements.lookback_hours == WINDOW_DAYS * 24 + 168


def test_requirements_need_every_hour_of_the_threshold_window() -> None:
    """A 7-day threshold needs all 168 hourly loads before serving."""
    coverage = task_type.requirements(PARAMS).history_coverage

    assert coverage == HistoryCoverage(window_hours=WINDOW_DAYS * 24, min_valid_hours=168)


def test_anchors_whose_threshold_window_misses_one_hour_get_no_training_rows() -> None:
    data = _training_data()
    gap = data.load["datetime"].min() + pd.Timedelta(hours=200)
    gapped = data.load[data.load["datetime"] != gap]

    anchors = training_rows(PARAMS, replace(data, load=gapped))["anchor"]

    window = pd.Timedelta(hours=WINDOW_DAYS * 24 - 1)
    assert not anchors.between(gap, gap + window).any()
    assert (anchors == gap + window + pd.Timedelta(hours=1)).any()


def test_threshold_is_the_configured_quantile_of_the_window_ending_at_the_anchor(
    trained,
) -> None:
    """P90 of 1..168 MW (linear interpolation) is 1 + 0.9 * 167 = 151.3 MW."""
    anchor = pd.Timestamp(LAST_HOUR)
    window_values = [float(value) for value in range(1, WINDOW_DAYS * 24 + 1)]
    older_spike = [1_000_000.0] * 24
    load = _window_load(older_spike + window_values, anchor)

    predictions = trained.model.predict(_prediction_data(load))

    assert predictions["threshold_mw"].tolist() == pytest.approx([151.3] * HORIZON_HOURS)


def test_training_threshold_uses_no_load_after_the_anchor() -> None:
    data = _training_data()
    anchor = data.validation_start - pd.Timedelta(hours=48)
    later = data.load["datetime"] > anchor
    spiked = data.load.assign(load_mw=data.load["load_mw"].where(~later, 1_000_000.0))

    original = training_rows(PARAMS, data)
    changed = training_rows(PARAMS, _training_data(load=spiked))

    at_anchor = original[original["anchor"] == anchor]
    assert not at_anchor.empty
    pd.testing.assert_series_equal(
        changed.loc[changed["anchor"] == anchor, "threshold_mw"],
        at_anchor["threshold_mw"],
    )
    assert changed.loc[changed["anchor"] == anchor, "is_high_load"].all()


def test_training_rows_start_at_the_first_anchor_with_enough_threshold_window_hours() -> None:
    """The first anchor follows a complete 168-hour threshold window."""
    data = _training_data()

    rows = training_rows(PARAMS, data)

    assert rows["anchor"].min() == data.load["datetime"].min() + pd.Timedelta(hours=167)


def test_training_rows_describe_the_target_hour_by_its_lead_from_the_anchor() -> None:
    data = _training_data()
    load_at = data.load.set_index("datetime")["load_mw"]
    temperature_at = data.weather.set_index("datetime")["temperature"]
    anchor = data.load["datetime"].min() + pd.Timedelta(hours=200)

    rows = training_rows(PARAMS, data)
    from_anchor = rows[rows["anchor"] == anchor].sort_values("lead_hours")

    assert from_anchor["lead_hours"].tolist() == list(range(1, MAX_LEAD_HOURS + 1))
    assert (
        from_anchor["datetime"] - anchor == pd.to_timedelta(from_anchor["lead_hours"], "h")
    ).all()
    assert (from_anchor["hour"] == from_anchor["datetime"].dt.hour).all()
    assert from_anchor["temperature"].tolist() == temperature_at[from_anchor["datetime"]].tolist()
    assert (from_anchor["load_mw_lag_24"] == load_at[anchor - pd.Timedelta(hours=24)]).all()
    assert (from_anchor["anchor_load_mw"] == load_at[anchor]).all()


def test_trains_one_classifier_and_reports_precision_recall_f1(trained) -> None:
    assert set(trained.metrics) == {"precision", "recall", "f1"}
    assert trained.metrics["f1"] > 0.5


def test_predicts_one_row_per_weather_hour_in_weather_order(trained) -> None:
    data = _prediction_data(_training_data().load)

    predictions = trained.model.predict(data)

    assert predictions["datetime"].tolist() == data.weather["datetime"].tolist()
    assert predictions["probability"].between(0.0, 1.0).all()
    assert predictions["is_high_load"].tolist() == (predictions["probability"] >= 0.5).tolist()
    assert predictions["is_high_load"].map(type).eq(bool).all()


def test_prediction_beyond_the_trained_lead_range_fails(trained) -> None:
    data = _prediction_data(_training_data().load)
    far = data.weather.assign(
        datetime=data.weather["datetime"] + pd.Timedelta(hours=MAX_LEAD_HOURS)
    )

    with pytest.raises(ValueError, match="lead"):
        trained.model.predict(PredictionData(data.anchor, data.load_history, far, HORIZON_HOURS))


def test_missing_weather_field_fails_instead_of_using_a_constant(trained) -> None:
    data = _prediction_data(_training_data().load)
    without_humidity = data.weather.drop(columns=["relative_humidity"])

    with pytest.raises(KeyError, match="relative_humidity"):
        trained.model.predict(
            PredictionData(data.anchor, data.load_history, without_humidity, HORIZON_HOURS)
        )


def test_saved_model_reloads_with_identical_predictions(trained, tmp_path: Path) -> None:
    data = _prediction_data(_training_data().load)

    trained.model.save(tmp_path / "model")
    reloaded = task_type.load(tmp_path / "model", PARAMS, WEATHER_FIELDS)

    pd.testing.assert_frame_equal(reloaded.predict(data), trained.model.predict(data))
    assert sorted(path.name for path in (tmp_path / "model").iterdir()) == [
        "metadata.json",
        "model.txt",
    ]


def test_loading_another_task_types_model_fails(tmp_path: Path) -> None:
    recursive = get_task_type("recursive_regression")
    load, weather = hourly_load_with_weather(24 * 10, LAST_HOUR)
    params = recursive.params_model.model_validate(
        {"lags": [1], "rolling_windows": [6], "model": PARAMS.model.model_dump()}
    )
    split = pd.Timestamp(LAST_HOUR) + pd.Timedelta(hours=1)
    recursive.train(params, TrainingData(load, weather, split)).model.save(tmp_path / "m")

    with pytest.raises(ValueError, match="recursive_regression"):
        task_type.load(tmp_path / "m", PARAMS, WEATHER_FIELDS)


def test_validation_split_after_all_rows_reports_no_metrics_so_health_warns() -> None:
    """No validation rows means no measured metrics; reporting zero would hide an unvalidated model."""
    after_last_row = pd.Timestamp(LAST_HOUR) + pd.Timedelta(hours=1)
    thresholds = task_type.health_model.model_validate(HEALTH)

    result = task_type.train(PARAMS, _training_data(validation_start=after_last_row))

    assert result.metrics == {}
    assert task_type.assess_health(thresholds, result.metrics).status is HealthStatus.WARNING


def test_validation_split_before_all_rows_refuses_to_train() -> None:
    before_first_row = pd.Timestamp(LAST_HOUR) - pd.Timedelta(days=30)

    with pytest.raises(ValueError, match="No training rows"):
        task_type.train(PARAMS, _training_data(validation_start=before_first_row))


def test_labels_of_a_single_class_refuse_to_train() -> None:
    flat, _ = hourly_load_with_weather(TRAINING_HOURS, LAST_HOUR)

    with pytest.raises(ValueError, match="single class"):
        task_type.train(PARAMS, _training_data(load=flat.assign(load_mw=30000.0)))


@pytest.mark.parametrize(
    ("metrics", "expected", "named"),
    [
        ({"precision": 0.6, "recall": 0.5, "f1": 0.55}, HealthStatus.HEALTHY, "min_f1"),
        ({"precision": 0.59, "recall": 0.9, "f1": 0.7}, HealthStatus.WARNING, "min_precision"),
        ({"precision": 0.9, "recall": 0.49, "f1": 0.6}, HealthStatus.WARNING, "min_recall"),
        ({"precision": 0.9, "recall": 0.9, "f1": 0.5}, HealthStatus.WARNING, "min_f1"),
    ],
)
def test_health_requires_each_metric_to_reach_its_configured_floor(
    metrics: dict[str, float], expected: HealthStatus, named: str
) -> None:
    thresholds = task_type.health_model.model_validate(HEALTH)

    assessment = task_type.assess_health(thresholds, metrics)

    assert assessment.status is expected
    assert named in assessment.reason


@pytest.mark.parametrize("missing", ["precision", "recall", "f1"])
def test_health_without_a_metric_warns_instead_of_passing(missing: str) -> None:
    thresholds = task_type.health_model.model_validate(HEALTH)
    metrics = {name: 0.9 for name in ("precision", "recall", "f1") if name != missing}

    assessment = task_type.assess_health(thresholds, metrics)

    assert assessment.status is HealthStatus.WARNING
    assert missing in assessment.reason


def test_predictions_do_not_depend_on_rows_order_of_load_history(trained) -> None:
    data = _prediction_data(_training_data().load)
    shuffled = data.load_history.sample(frac=1.0, random_state=0)

    result = trained.model.predict(
        PredictionData(data.anchor, shuffled, data.weather, HORIZON_HOURS)
    )

    np.testing.assert_allclose(result["probability"], trained.model.predict(data)["probability"])


def test_day_off_recipe_describes_each_target_hour_by_its_own_date() -> None:
    """From a workday anchor, targets on the 10-09 substitute holiday are days off, 10-08 is not."""
    params = DirectClassificationParams.model_validate({**PARAMS.model_dump(), "day_off": True})
    load, weather = hourly_load_with_weather(TRAINING_HOURS, datetime(2026, 10, 10, 23, 0))

    rows = training_rows(params, TrainingData(load, weather, load["datetime"].iloc[-1]))

    from_anchor = rows[rows["anchor"] == pd.Timestamp("2026-10-07 23:00")]
    by_target = dict(
        zip(from_anchor["datetime"].dt.strftime("%m-%d %H"), from_anchor["is_day_off"])
    )
    assert by_target["10-08 12"] == 0
    assert by_target["10-09 00"] == 1
    assert by_target["10-09 23"] == 1
    assert "is_day_off" not in training_rows(PARAMS, _training_data()).columns


@pytest.mark.parametrize(
    ("changed", "named"),
    [
        ({"lags": [1]}, "lags"),
        ({"rolling_windows": [6, 24, 48]}, "rolling_windows"),
        ({"day_off": True}, "day_off"),
        ({"threshold": {"window_days": 5, "quantile": 0.9}}, "threshold"),
        ({"threshold": {"window_days": WINDOW_DAYS, "quantile": 0.95}}, "threshold"),
    ],
)
def test_a_model_trained_with_another_recipe_is_refused_on_load(
    trained, tmp_path: Path, changed: dict, named: str
) -> None:
    """A shorter threshold window in the definition used to reach the model as a 500."""
    trained.model.save(tmp_path)
    declared = DirectClassificationParams.model_validate({**PARAMS.model_dump(), **changed})

    with pytest.raises(ModelRecipeMismatchError, match=f"{named}.*retrain"):
        task_type.load(tmp_path, declared, WEATHER_FIELDS)


def test_hyperparameters_and_field_order_do_not_stop_a_model_serving(
    trained, tmp_path: Path
) -> None:
    trained.model.save(tmp_path)
    declared = PARAMS.model_copy(
        update={"model": PARAMS.model.model_copy(update={"num_leaves": 63})}
    )

    reloaded = task_type.load(tmp_path, declared, tuple(reversed(WEATHER_FIELDS)))

    assert reloaded.params == PARAMS


def test_a_model_trained_on_other_weather_fields_is_refused_on_load(
    trained, tmp_path: Path
) -> None:
    trained.model.save(tmp_path)

    with pytest.raises(ModelRecipeMismatchError, match="weather_fields"):
        task_type.load(tmp_path, PARAMS, ("relative_humidity",))
