"""Integration tests for FastAPI endpoints."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from shiro_mlops.core.config import settings
from shiro_mlops.data.weather_resolution import WeatherResolution
from shiro_mlops.service.api import app, model_store
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_tasks
from shiro_mlops.tasks.model_store import model_directory, save_model
from shiro_mlops.tasks.runner import (
    MissingLoadHistoryError,
    StaleLoadAnchorError,
    TaskRuntime,
    WeatherUnavailableError,
    train_task,
)
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel, TrainingData
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    override_task_policies,
)

HIGH_LOAD_ALERT = "high_load_alert"
ANOMALY_TASK = "load_pattern_anomaly"


def test_api_health_endpoint() -> None:
    """Test /health status endpoint."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data


def test_app_startup_skips_timescale_initialization_in_test_environment(monkeypatch) -> None:
    """測試環境啟動 API 時不得連線預設 TimescaleDB。"""
    initialization_calls: list[None] = []
    monkeypatch.setattr(
        "shiro_mlops.core.database.init_db", lambda: initialization_calls.append(None)
    )

    with TestClient(app):
        pass

    assert initialization_calls == []


def test_api_ready_reports_cold_start_without_constructing_a_cwa_client(monkeypatch) -> None:
    """An empty database is live but not ready until ingestion and training complete."""
    monkeypatch.setattr(model_store, "models", {})

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_api_ready_reports_normal_or_degraded_weather_mode(monkeypatch) -> None:
    """Readiness exposes a usable full-horizon weather mode from persisted sources."""
    repository = MagicMock()
    latest_load = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-08-20 12:00"),
                "load_mw": 30000.0,
                "subject": "nationwide",
            }
        ]
    )
    repository.fetch_latest_load.return_value = latest_load
    repository.fetch_load_range.return_value = latest_load
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock", lambda: pd.Timestamp("2026-08-20 13:00")
    )
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, MagicMock())
    weather = WeatherResolution(
        dataframe=pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2026-08-20 13:00")],
                "temperature": [30.0],
                "relative_humidity": [70.0],
            }
        ),
        sources=(
            {
                "temperature": {"source": "previous_day_observation"},
                "relative_humidity": {"source": "climatology"},
            },
        ),
        mode="degraded",
    )
    monkeypatch.setattr("shiro_mlops.tasks.runner.resolve_weather", lambda *args, **kwargs: weather)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["mode"] == "degraded"


def _serve_fitted_forecaster(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> MagicMock:
    """Attach a fitted model and a repository holding fresh load and forecast rows."""
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, fitted_task_model)
    return _serve_fresh_inputs(taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch)


def _serve_fresh_inputs(
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> MagicMock:
    """Attach a repository holding fresh load and forecast rows, and a matching request clock."""
    repository = MagicMock()
    repository.fetch_latest_load.return_value = taipower_raw_df.tail(1)
    repository.fetch_load_range.return_value = taipower_raw_df
    repository.fetch_cwa_station_observations.return_value = cwa_obs_df.rename(
        columns={
            "datetime": "observed_at",
            "temperature": "temperature_c",
            "relative_humidity": "relative_humidity_pct",
        }
    )
    repository.fetch_cwa_forecast_rows.return_value = cwa_forecast_df.assign(
        dataset_id="F-D0047-089",
        issued_at=pd.Timestamp("2026-08-21 22:00"),
        source_updated_at=pd.Timestamp("2026-08-21 22:10"),
        valid_from=lambda frame: frame["datetime"],
        valid_to=lambda frame: frame["datetime"],
        geocode="63000050",
    ).rename(columns={"temperature": "temperature_c", "relative_humidity": "relative_humidity_pct"})
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock", lambda: pd.Timestamp("2026-08-22 00:00")
    )

    return repository


def test_api_predict_dynamic_horizon(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Test dynamic horizon prediction endpoint."""
    _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    client = TestClient(app)
    response = client.post("/predict", json={"horizon_hours": 12})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["horizon_hours"] == 12
    assert len(data["predictions"]) == 12
    assert data["predictions"][0]["predicted_load_mw"] > 0
    assert data["subject"] == "nationwide"
    assert "location" not in data


def test_api_predict_ignores_legacy_location_and_reads_nationwide_subject(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """A legacy location request cannot change the nationwide load subject."""
    repository = _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    client = TestClient(app)
    response = client.post("/predict", json={"horizon_hours": 6, "location": "Kaohsiung"})

    assert response.status_code == 200
    assert response.json()["subject"] == "nationwide"
    assert repository.fetch_load_range.call_args.kwargs["subject"] == "nationwide"


def test_api_predict_reads_weather_from_the_weather_reference_point(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Weather comes from the catalog's reference point, independently of the prediction subject."""
    repository = _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    TestClient(app).post("/predict", json={"horizon_hours": 1})

    taipei = settings.cwa_locations["Taipei"]
    assert repository.fetch_cwa_forecast_rows.call_args.kwargs["geocode"] == taipei.geocode
    assert (
        repository.fetch_cwa_station_observations.call_args.kwargs["station_id"]
        == taipei.station_id
    )


def test_api_predict_on_demand_does_not_issue_a_forecast(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Only scheduled issues count (ADR-0013): an on-demand /predict only reads the store."""
    repository = _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    response = TestClient(app).post("/predict", json={"horizon_hours": 12})

    assert response.status_code == 200, response.text
    repository.insert_issued_forecast.assert_not_called()
    assert {name for name, _args, _kwargs in repository.method_calls} <= {
        "fetch_latest_load",
        "fetch_load_range",
        "fetch_cwa_station_observations",
        "fetch_cwa_forecast_rows",
    }


def test_openapi_marks_predict_location_as_optional_and_deprecated() -> None:
    schemas = app.openapi()["components"]["schemas"]
    request_schema = schemas["PredictionRequest"]

    assert "location" not in request_schema.get("required", [])
    assert request_schema["properties"]["location"]["deprecated"] is True
    assert "subject" in schemas["PredictionResponse"]["properties"]
    assert "location" not in schemas["PredictionResponse"]["properties"]


def test_task_predict_matches_the_predict_alias(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Under ADR-0009, /predict and the dynamic-horizon task endpoint return the same forecast."""
    _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )
    client = TestClient(app)

    alias = client.post("/predict", json={"horizon_hours": 12}).json()
    task = client.post(
        f"/tasks/{DYNAMIC_HORIZON_FORECAST}/predict", json={"horizon_hours": 12}
    ).json()

    assert task["status"] == "success"
    assert task["task_id"] == DYNAMIC_HORIZON_FORECAST
    assert task["task_type"] == "recursive_regression"
    assert task["subject"] == alias["subject"] == "nationwide"
    assert task["mode"] == alias["mode"]
    assert len(task["predictions"]) == 12
    assert task["predictions"] == alias["predictions"]


def test_task_endpoints_answer_404_for_an_unknown_task() -> None:
    client = TestClient(app)

    predict = client.post("/tasks/no_such_task/predict", json={"horizon_hours": 1})
    ready = client.get("/tasks/no_such_task/ready")

    assert predict.status_code == 404
    assert "no_such_task" in predict.json()["detail"]
    assert ready.status_code == 404


def test_task_predict_answers_503_when_the_task_model_is_not_loaded(monkeypatch) -> None:
    monkeypatch.setattr(model_store, "models", {})

    response = TestClient(app).post(
        f"/tasks/{DYNAMIC_HORIZON_FORECAST}/predict", json={"horizon_hours": 1}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Model is not loaded or trained yet."


@pytest.mark.parametrize(
    "error",
    [
        MissingLoadHistoryError("No persisted nationwide load history is available."),
        StaleLoadAnchorError("Stale load anchor: latest actual load lags request time."),
        WeatherUnavailableError("Weather coverage is unavailable."),
    ],
)
def test_task_predict_answers_503_when_serving_inputs_are_unavailable(
    error: Exception, monkeypatch
) -> None:
    """The task endpoint and alias both return 503 when load history, anchor freshness, or weather is unavailable."""
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, MagicMock())
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", MagicMock())

    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr("shiro_mlops.service.api.predict_task", unavailable)
    client = TestClient(app)

    task = client.post(f"/tasks/{DYNAMIC_HORIZON_FORECAST}/predict", json={"horizon_hours": 1})
    alias = client.post("/predict", json={"horizon_hours": 1})

    assert task.status_code == alias.status_code == 503
    assert task.json()["detail"] == alias.json()["detail"] == str(error)


def test_unexpected_task_errors_are_logged_with_their_traceback(monkeypatch, caplog) -> None:
    """Unexpected errors retain their traceback in logs when returned as not_ready or HTTP 500."""
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, MagicMock())
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", MagicMock())

    def broken(*args, **kwargs):
        raise RuntimeError("feature column mismatch")

    monkeypatch.setattr("shiro_mlops.service.api.check_task_ready", broken)
    monkeypatch.setattr("shiro_mlops.service.api.predict_task", broken)
    client = TestClient(app)

    with caplog.at_level("ERROR", logger="shiro_mlops.service.api"):
        ready = client.get(f"/tasks/{DYNAMIC_HORIZON_FORECAST}/ready")
        predict = client.post(
            f"/tasks/{DYNAMIC_HORIZON_FORECAST}/predict", json={"horizon_hours": 1}
        )

    assert ready.status_code == 503
    assert predict.status_code == 500
    logged = [record for record in caplog.records if record.exc_info]
    assert len(logged) == 2
    assert all(DYNAMIC_HORIZON_FORECAST in record.getMessage() for record in logged)


def test_task_ready_matches_the_ready_alias(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )
    client = TestClient(app)

    alias = client.get("/ready")
    task = client.get(f"/tasks/{DYNAMIC_HORIZON_FORECAST}/ready")

    assert task.status_code == alias.status_code
    assert task.json() == alias.json()


def test_startup_loads_each_task_model_independently(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A missing or corrupt model for one task cannot prevent other tasks from serving predictions."""
    tasks = deployed_tasks()
    other = replace(tasks[DYNAMIC_HORIZON_FORECAST], task_id="other_forecast")
    monkeypatch.setitem(tasks, other.task_id, other)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(model_store, "models", {})
    save_model(settings.models_dir, other.task_id, fitted_task_model)
    corrupt = model_directory(settings.models_dir, DYNAMIC_HORIZON_FORECAST)
    corrupt.mkdir(parents=True)
    (corrupt / "metadata.json").write_text("not json", encoding="utf-8")
    _serve_fresh_inputs(taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch)

    with TestClient(app) as client:
        health = client.get("/health").json()
        other_predict = client.post(f"/tasks/{other.task_id}/predict", json={"horizon_hours": 3})
        alias_predict = client.post("/predict", json={"horizon_hours": 3})

    assert health["model_loaded"] is False
    assert health["tasks"] == {
        DYNAMIC_HORIZON_FORECAST: {"task_type": "recursive_regression", "model_loaded": False},
        other.task_id: {"task_type": "recursive_regression", "model_loaded": True},
        HIGH_LOAD_ALERT: {"task_type": "direct_classification", "model_loaded": False},
        ANOMALY_TASK: {"task_type": "unsupervised_reconstruction", "model_loaded": False},
    }
    assert other_predict.status_code == 200
    assert len(other_predict.json()["predictions"]) == 3
    assert alias_predict.status_code == 503


def test_openapi_keeps_the_predict_item_contract_for_the_dynamic_horizon_task() -> None:
    """Issue #68 keeps the /predict item contract aligned with the dynamic-horizon task item."""
    expected_fields = {
        "datetime",
        "predicted_load_mw",
        "temperature",
        "relative_humidity",
        "weather_sources",
    }
    schemas = app.openapi()["components"]["schemas"]

    task_response = schemas["DynamicHorizonForecastTaskPredictionResponse"]
    item_ref = task_response["properties"]["predictions"]["items"]["$ref"]
    task_item = schemas[item_ref.rsplit("/", 1)[-1]]

    assert set(schemas["PredictionItem"]["properties"]) == expected_fields
    assert set(schemas["PredictionItem"]["required"]) == expected_fields
    assert set(task_item["required"]) == expected_fields
    assert task_item["properties"] == schemas["PredictionItem"]["properties"]


def _fitted_high_load_alert(
    last_hour: pd.Timestamp, task: TaskDefinition | None = None
) -> tuple[TaskModel, pd.DataFrame]:
    """Train a high-load alert on 35 days, leaving 7 days of full threshold windows."""
    task = task or deployed_tasks()[HIGH_LOAD_ALERT]
    load, weather = hourly_load_with_weather(24 * 35, last_hour.to_pydatetime())
    data = TrainingData(
        load=load,
        weather=weather[["datetime", *task.weather.fields]],
        validation_start=last_hour + pd.Timedelta(hours=1),
    )
    return get_task_type(task.task_type).train(task.params, data).model, load


def test_high_load_alert_predicts_each_hour_with_verdict_probability_and_threshold(
    cwa_obs_df: pd.DataFrame, cwa_forecast_df: pd.DataFrame, monkeypatch
) -> None:
    model, load = _fitted_high_load_alert(pd.Timestamp("2026-08-21 23:00"))
    monkeypatch.setitem(model_store.models, HIGH_LOAD_ALERT, model)
    _serve_fresh_inputs(load, cwa_obs_df, cwa_forecast_df, monkeypatch)

    response = TestClient(app).post(f"/tasks/{HIGH_LOAD_ALERT}/predict", json={"horizon_hours": 6})

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == HIGH_LOAD_ALERT
    assert body["task_type"] == "direct_classification"
    assert body["subject"] == "nationwide"
    predictions = body["predictions"]
    assert [item["datetime"] for item in predictions] == [
        f"2026-08-22 {hour:02d}:00:00" for hour in range(6)
    ]
    for item in predictions:
        assert isinstance(item["is_high_load"], bool)
        assert 0.0 <= item["probability"] <= 1.0
        assert item["is_high_load"] == (item["probability"] >= 0.5)
        assert "predicted_load_mw" not in item
        assert set(item["weather_sources"]) == {"temperature", "relative_humidity"}
    thresholds = {item["threshold_mw"] for item in predictions}
    assert len(thresholds) == 1
    assert load["load_mw"].min() < thresholds.pop() < load["load_mw"].max()


def test_prediction_items_repeat_only_the_weather_fields_the_task_declares(
    cwa_obs_df: pd.DataFrame, cwa_forecast_df: pd.DataFrame, monkeypatch
) -> None:
    """Prediction items follow task weather.fields instead of fixed task-type fields."""
    tasks = deployed_tasks()
    shipped = tasks[HIGH_LOAD_ALERT]
    temperature_only = replace(
        shipped,
        task_id="temperature_only_alert",
        weather=replace(shipped.weather, fields=("temperature",)),
    )
    monkeypatch.setitem(tasks, temperature_only.task_id, temperature_only)
    model, load = _fitted_high_load_alert(pd.Timestamp("2026-08-21 23:00"), temperature_only)
    monkeypatch.setitem(model_store.models, temperature_only.task_id, model)
    _serve_fresh_inputs(load, cwa_obs_df, cwa_forecast_df, monkeypatch)

    response = TestClient(app).post(
        f"/tasks/{temperature_only.task_id}/predict", json={"horizon_hours": 2}
    )

    assert response.status_code == 200
    for item in response.json()["predictions"]:
        assert set(item) == {
            "datetime",
            "is_high_load",
            "probability",
            "threshold_mw",
            "temperature",
            "weather_sources",
        }
        assert set(item["weather_sources"]) == {"temperature"}


def test_high_load_alert_refuses_a_stale_load_anchor(
    cwa_obs_df: pd.DataFrame, cwa_forecast_df: pd.DataFrame, monkeypatch
) -> None:
    """A stale load anchor makes both high-load alert and dynamic-horizon prediction return 503."""
    model, load = _fitted_high_load_alert(pd.Timestamp("2026-08-21 12:00"))
    monkeypatch.setitem(model_store.models, HIGH_LOAD_ALERT, model)
    _serve_fresh_inputs(load, cwa_obs_df, cwa_forecast_df, monkeypatch)

    response = TestClient(app).post(f"/tasks/{HIGH_LOAD_ALERT}/predict", json={"horizon_hours": 6})

    assert response.status_code == 503
    assert "Stale load anchor" in response.json()["detail"]


def test_high_load_alert_without_threshold_window_history_answers_503(
    cwa_obs_df: pd.DataFrame, cwa_forecast_df: pd.DataFrame, monkeypatch
) -> None:
    """An incomplete threshold window makes predict and ready return 503 rather than 500 or ready."""
    model, load = _fitted_high_load_alert(pd.Timestamp("2026-08-21 23:00"))
    monkeypatch.setitem(model_store.models, HIGH_LOAD_ALERT, model)
    _serve_fresh_inputs(load.tail(24 * 20), cwa_obs_df, cwa_forecast_df, monkeypatch)
    client = TestClient(app)

    predicted = client.post(f"/tasks/{HIGH_LOAD_ALERT}/predict", json={"horizon_hours": 6})
    ready = client.get(f"/tasks/{HIGH_LOAD_ALERT}/ready")

    assert predicted.status_code == 503
    assert "672-hour window" in predicted.json()["detail"]
    assert ready.status_code == 503
    assert "672-hour window" in ready.json()["reason"]


# --- Observed-weather task: load_pattern_anomaly -------------------------------------------

ANOMALY_ANCHOR = pd.Timestamp("2026-09-20 23:00")


@pytest.fixture
def serve_anomaly_task(test_repo, monkeypatch) -> None:
    """A trained anomaly model over a SQLite store holding 21 days of load and observations."""
    hours = 24 * 21
    load, weather = hourly_load_with_weather(hours, ANOMALY_ANCHOR.to_pydatetime())
    test_repo.upsert_taipower_load(load)
    test_repo.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    task = override_task_policies(monkeypatch, ANOMALY_TASK, min_training_hours=hours)
    as_of = ANOMALY_ANCHOR + pd.Timedelta(minutes=30)
    model = train_task(task, TaskRuntime(repository=test_repo), as_of=as_of).model
    monkeypatch.setitem(model_store.models, ANOMALY_TASK, model)
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", test_repo)
    monkeypatch.setattr("shiro_mlops.service.api.request_clock", lambda: as_of)


def test_anomaly_task_scores_the_latest_window_end_hours(serve_anomaly_task) -> None:
    """For observed-weather tasks, horizon_hours selects recent window-end hours back from the load anchor."""
    response = TestClient(app).post(f"/tasks/{ANOMALY_TASK}/predict", json={"horizon_hours": 3})

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("status", "task_id", "task_type", "subject", "mode")} == {
        "status": "success",
        "task_id": ANOMALY_TASK,
        "task_type": "unsupervised_reconstruction",
        "subject": "nationwide",
        "mode": "normal",
    }
    items = body["predictions"]
    assert [item["datetime"] for item in items] == [
        "2026-09-20 21:00:00",
        "2026-09-20 22:00:00",
        "2026-09-20 23:00:00",
    ]
    assert all(
        set(item) == {"datetime", "anomaly_score", "is_anomaly", "threshold"} for item in items
    )
    assert all(item["is_anomaly"] == (item["anomaly_score"] > item["threshold"]) for item in items)


def test_anomaly_task_ready_reports_normal_mode_without_forecasts(serve_anomaly_task) -> None:
    response = TestClient(app).get(f"/tasks/{ANOMALY_TASK}/ready")

    assert response.status_code == 200
    assert response.json()["mode"] == "normal"


def test_anomaly_task_reports_a_database_outage_instead_of_missing_weather(
    serve_anomaly_task, test_repo, monkeypatch
) -> None:
    def unavailable(**_: object) -> pd.DataFrame:
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(test_repo, "fetch_cwa_station_observations", unavailable)

    response = TestClient(app).post(f"/tasks/{ANOMALY_TASK}/predict", json={"horizon_hours": 1})

    assert response.status_code == 503
    assert "Persistence unavailable" in response.json()["detail"]


def test_anomaly_task_answers_503_on_a_stale_load_anchor(serve_anomaly_task, monkeypatch) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock",
        lambda: ANOMALY_ANCHOR + pd.Timedelta(hours=3, minutes=1),
    )

    response = TestClient(app).post(f"/tasks/{ANOMALY_TASK}/predict", json={"horizon_hours": 1})

    assert response.status_code == 503
    assert "Stale load anchor" in response.json()["detail"]


def test_openapi_describes_high_load_alert_items() -> None:
    schemas = app.openapi()["components"]["schemas"]
    task_response = next(
        schema
        for name, schema in schemas.items()
        if name.endswith("TaskPredictionResponse")
        and schema["properties"]["task_type"].get("const") == "direct_classification"
    )
    item_ref = task_response["properties"]["predictions"]["items"]["$ref"]
    item = schemas[item_ref.rsplit("/", 1)[-1]]

    assert {"datetime", "is_high_load", "probability", "threshold_mw"} <= set(item["required"])


def test_openapi_describes_anomaly_predictions_and_horizon_semantics() -> None:
    schemas = app.openapi()["components"]["schemas"]
    response_schema = schemas["LoadPatternAnomalyTaskPredictionResponse"]
    item_ref = response_schema["properties"]["predictions"]["items"]["$ref"]
    item = schemas[item_ref.rsplit("/", 1)[-1]]

    assert set(item["properties"]) == {"datetime", "anomaly_score", "is_anomaly", "threshold"}
    task_horizon = schemas["TaskPredictionRequest"]["properties"]["horizon_hours"]["description"]
    assert "observed-weather tasks" in task_horizon
    assert schemas["PredictionRequest"]["properties"]["horizon_hours"]["description"] == (
        "Forecast horizon in hours (1-168)"
    )


def test_openapi_describes_weather_sources_per_field_and_reference_point() -> None:
    """ADR-0012: each weather field lists the source behind every weather reference point."""
    item = app.openapi()["components"]["schemas"]["PredictionItem"]

    by_field = item["properties"]["weather_sources"]["additionalProperties"]
    by_point = by_field["additionalProperties"]
    assert by_point["additionalProperties"] == {"type": "string"}
