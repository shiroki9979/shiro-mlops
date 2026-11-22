"""Issued forecasts persist once per issue time and are never rewritten (ADR-0013)."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.repository import IssuedForecastRepository, TimeSeriesRepository

ISSUED_AT = datetime(2026, 11, 20, 10, 15)
LOAD_ANCHOR = datetime(2026, 11, 20, 9, 0)
MODEL_SHA256 = "a" * 64


def _issued_forecast(
    issued_at: datetime = ISSUED_AT, *, first_load_mw: float = 30000.0
) -> IssuedForecast:
    return IssuedForecast(
        issued_at=issued_at,
        load_anchor=LOAD_ANCHOR,
        status="degraded",
        model_sha256=MODEL_SHA256,
        mlflow_model_version=None,
        steps=tuple(
            IssuedForecastStep(
                target_hour=LOAD_ANCHOR + timedelta(hours=hour),
                predicted_load_mw=first_load_mw + hour,
            )
            for hour in range(1, 169)
        ),
    )


def test_issued_forecast_reads_back_exactly_as_issued(test_repo: TimeSeriesRepository) -> None:
    forecast = _issued_forecast()

    assert test_repo.insert_issued_forecast(forecast) is True

    assert test_repo.fetch_issued_forecast(ISSUED_AT) == forecast


def test_issued_forecast_keeps_steps_at_or_before_the_issue_time(
    test_repo: TimeSeriesRepository,
) -> None:
    """The anchor precedes the issue time, so the first step (10:00) is not after 10:15."""
    test_repo.insert_issued_forecast(_issued_forecast())

    fetched = test_repo.fetch_issued_forecast(ISSUED_AT)

    assert fetched is not None
    assert fetched.steps[0].target_hour == datetime(2026, 11, 20, 10, 0)
    assert len(fetched.steps) == 168


def test_issued_forecast_stores_its_instants_as_utc_with_an_offset(
    sqlite_engine: Engine,
) -> None:
    """Issued at 10:15 Taiwan time, stored as 02:15 UTC in the same form as hourly load rows."""
    IssuedForecastRepository(engine=sqlite_engine).insert(_issued_forecast())

    with sqlite_engine.connect() as conn:
        header = conn.execute(text("SELECT issued_at, load_anchor FROM issued_forecast")).one()
        first_step = conn.execute(
            text(
                "SELECT issued_at, target_hour FROM issued_forecast_step "
                "ORDER BY target_hour LIMIT 1"
            )
        ).one()

    assert tuple(header) == ("2026-11-20 02:15:00+00:00", "2026-11-20 01:00:00+00:00")
    assert tuple(first_step) == ("2026-11-20 02:15:00+00:00", "2026-11-20 02:00:00+00:00")


def test_issuing_the_same_issue_time_again_leaves_the_record_unchanged(
    test_repo: TimeSeriesRepository,
) -> None:
    original = _issued_forecast()
    test_repo.insert_issued_forecast(original)
    reissue = replace(
        _issued_forecast(first_load_mw=99999.0),
        status="normal",
        model_sha256="b" * 64,
        mlflow_model_version="7",
    )

    assert test_repo.insert_issued_forecast(reissue) is False

    assert test_repo.fetch_issued_forecast(ISSUED_AT) == original


def test_fetching_an_issue_time_that_was_never_issued_returns_none(
    test_repo: TimeSeriesRepository,
) -> None:
    test_repo.insert_issued_forecast(_issued_forecast())

    assert test_repo.fetch_issued_forecast(ISSUED_AT + timedelta(hours=1)) is None


def test_issued_forecast_repository_works_standalone(sqlite_engine: Engine) -> None:
    repository = IssuedForecastRepository(engine=sqlite_engine)
    forecast = _issued_forecast()

    assert repository.insert(forecast) is True
    assert repository.fetch(ISSUED_AT) == forecast


def test_issued_forecast_rejects_a_status_other_than_normal_or_degraded() -> None:
    with pytest.raises(ValueError, match="status"):
        replace(_issued_forecast(), status="unavailable")


def test_issued_forecast_rejects_a_model_identity_that_is_not_a_full_sha256() -> None:
    with pytest.raises(ValueError, match="model_sha256"):
        replace(_issued_forecast(), model_sha256="abc")


def test_latest_issued_forecast_is_the_one_with_the_latest_issue_time(
    test_repo: TimeSeriesRepository,
) -> None:
    """Insertion order does not matter: an earlier issue written later is not the latest."""
    latest = _issued_forecast(ISSUED_AT + timedelta(hours=1))
    test_repo.insert_issued_forecast(latest)
    test_repo.insert_issued_forecast(_issued_forecast())

    assert test_repo.fetch_latest_issued_forecast() == latest


def test_latest_issued_forecast_is_none_before_the_first_issue(
    test_repo: TimeSeriesRepository,
) -> None:
    assert test_repo.fetch_latest_issued_forecast() is None
