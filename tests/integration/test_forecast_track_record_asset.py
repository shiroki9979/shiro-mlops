"""Compiling the forecast track record end to end: cutoff, 30-day window and accumulated days (ADR-0013 §2.3)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from dagster import AssetKey, build_input_context, materialize

from shiro_mlops.core.io_managers import get_parquet_io_manager
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.forecast_track_record import (
    FORECAST_TRACK_RECORD_ASSET,
    forecast_track_record,
)

TAIPEI = ZoneInfo("Asia/Taipei")
# 排程 tick 為 10:25，統計截至時刻取整點 10:00。
TICK = "2026-11-20T10:25:00"
CUTOFF = datetime(2026, 11, 20, 10, 0)


def _issue(repo: TimeSeriesRepository, issued_at: datetime, target_hours: list[datetime]) -> None:
    repo.insert_issued_forecast(
        IssuedForecast(
            issued_at=issued_at,
            load_anchor=issued_at.replace(minute=0) - timedelta(hours=1),
            status="degraded",
            model_sha256="a" * 64,
            mlflow_model_version="7",
            steps=tuple(
                IssuedForecastStep(target_hour=hour, predicted_load_mw=30000.0)
                for hour in target_hours
            ),
        )
    )


def _issue_45_minutes_ahead(repo: TimeSeriesRepository, target_hours: list[datetime]) -> None:
    """One forecast per target hour, issued at :15 the hour before (lead 1)."""
    for hour in target_hours:
        _issue(repo, hour - timedelta(minutes=45), [hour])


def _observe(repo: TimeSeriesRepository, hours: list[datetime]) -> None:
    repo.upsert_taipower_load(pd.DataFrame({"datetime": hours, "load_mw": [25000.0] * len(hours)}))


def _compile(repo: TimeSeriesRepository, tmp_path, instance, *, tick: str | None = TICK):
    run_config = (
        {"ops": {FORECAST_TRACK_RECORD_ASSET: {"config": {"scheduled_at": tick}}}}
        if tick is not None
        else None
    )
    return materialize(
        [forecast_track_record],
        resources={
            "time_series_repo": repo,
            "io_manager": get_parquet_io_manager("local", "unused", tmp_path),
        },
        run_config=run_config,
        instance=instance,
    )


def _artifact(tmp_path) -> dict:
    """The track record exactly as a downstream asset reads it as input."""
    manager = get_parquet_io_manager("local", "unused", tmp_path)
    return manager.load_input(
        build_input_context(asset_key=AssetKey([FORECAST_TRACK_RECORD_ASSET]))
    )


TRACK_RECORD_METADATA = ("cutoff", "accumulated_days", "window_pairs")


def _metadata(result) -> dict:
    """The asset's own materialization metadata; the IO manager adds the artifact path."""
    [materialization] = result.asset_materializations_for_node(FORECAST_TRACK_RECORD_ASSET)
    return {key: materialization.metadata[key].value for key in TRACK_RECORD_METADATA}


def test_scheduled_run_counts_up_to_the_tick_hour_and_stores_only_cutoff_and_days(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    """No run status, weather source, model version or data gaps leave the asset."""
    hours = [datetime(2026, 11, 20, 8, 0), datetime(2026, 11, 20, 9, 0), CUTOFF]
    _issue_45_minutes_ahead(test_repo, hours)
    _observe(test_repo, hours)

    result = _compile(test_repo, tmp_path, dagster_instance)

    assert result.success
    assert _artifact(tmp_path) == {"cutoff": "2026-11-20T10:00:00", "accumulated_days": 1}
    assert _metadata(result) == {
        "cutoff": "2026-11-20T10:00:00",
        "accumulated_days": 1,
        "window_pairs": 2,
    }


def test_manual_run_cuts_off_at_the_current_hour(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    def current_hour() -> datetime:
        return datetime.now(TAIPEI).replace(tzinfo=None, minute=0, second=0, microsecond=0)

    before = current_hour()
    result = _compile(test_repo, tmp_path, dagster_instance, tick=None)
    after = current_hour()

    assert result.success
    assert datetime.fromisoformat(_artifact(tmp_path)["cutoff"]) in {before, after}


def test_window_spans_the_720_target_hours_before_the_cutoff(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    """E - 720h counts and E does not; the two counted hours fall on different Taiwan dates."""
    hours = [
        CUTOFF - timedelta(hours=721),
        CUTOFF - timedelta(hours=720),
        CUTOFF - timedelta(hours=1),
        CUTOFF,
    ]
    _issue_45_minutes_ahead(test_repo, hours)
    _observe(test_repo, hours)

    result = _compile(test_repo, tmp_path, dagster_instance)

    assert _metadata(result) == {
        "cutoff": "2026-11-20T10:00:00",
        "accumulated_days": 2,
        "window_pairs": 2,
    }


def test_accumulated_days_count_taiwan_dates(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    """23:00 and 00:00 Taiwan time are two dates, though both fall on 2026-11-18 in UTC."""
    hours = [datetime(2026, 11, 18, 23, 0), datetime(2026, 11, 19, 0, 0)]
    _issue_45_minutes_ahead(test_repo, hours)
    _observe(test_repo, hours)

    _compile(test_repo, tmp_path, dagster_instance)

    assert _artifact(tmp_path)["accumulated_days"] == 2


def test_a_full_window_accumulates_31_days(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    """720 hours from 2026-10-21 10:00 to 2026-11-20 09:00 touch 31 Taiwan dates."""
    hours = [CUTOFF - timedelta(hours=offset) for offset in range(1, 721)]
    _issue_45_minutes_ahead(test_repo, hours)
    _observe(test_repo, hours)

    result = _compile(test_repo, tmp_path, dagster_instance)

    assert _metadata(result)["window_pairs"] == 720
    assert _metadata(result)["accumulated_days"] == 31


def test_without_issued_forecasts_the_record_has_zero_days(
    test_repo: TimeSeriesRepository, tmp_path, dagster_instance
) -> None:
    _observe(test_repo, [CUTOFF - timedelta(hours=offset) for offset in range(1, 49)])

    result = _compile(test_repo, tmp_path, dagster_instance)

    assert result.success
    assert _artifact(tmp_path) == {"cutoff": "2026-11-20T10:00:00", "accumulated_days": 0}
    assert _metadata(result)["window_pairs"] == 0
