"""Issued forecasts persist once per issue time and are never rewritten (ADR-0013)."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.issued_forecast_repository import IssuedForecastRepository
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import ForecastMode

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

    assert test_repo.issued_forecast_store.insert(forecast) is True

    assert test_repo.issued_forecast_store.fetch(ISSUED_AT) == forecast


def test_issued_forecast_keeps_steps_at_or_before_the_issue_time(
    test_repo: TimeSeriesRepository,
) -> None:
    """The anchor precedes the issue time, so the first step (10:00) is not after 10:15."""
    test_repo.issued_forecast_store.insert(_issued_forecast())

    fetched = test_repo.issued_forecast_store.fetch(ISSUED_AT)

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
    test_repo.issued_forecast_store.insert(original)
    reissue = replace(
        _issued_forecast(first_load_mw=99999.0),
        status="normal",
        model_sha256="b" * 64,
        mlflow_model_version="7",
    )

    assert test_repo.issued_forecast_store.insert(reissue) is False

    assert test_repo.issued_forecast_store.fetch(ISSUED_AT) == original


def test_fetching_an_issue_time_that_was_never_issued_returns_none(
    test_repo: TimeSeriesRepository,
) -> None:
    test_repo.issued_forecast_store.insert(_issued_forecast())

    assert test_repo.issued_forecast_store.fetch(ISSUED_AT + timedelta(hours=1)) is None


def test_an_issue_time_exists_only_once_issued(test_repo: TimeSeriesRepository) -> None:
    store = test_repo.issued_forecast_store
    assert store.exists(ISSUED_AT) is False

    store.insert(_issued_forecast())

    assert store.exists(ISSUED_AT) is True
    assert store.exists(ISSUED_AT + timedelta(hours=1)) is False
    assert store.exists(ISSUED_AT - timedelta(microseconds=1)) is False


def test_checking_an_issue_time_reads_no_steps(test_repo: TimeSeriesRepository) -> None:
    """Issuing asks this every hour; reading 168 steps only to discard them is wasted work."""
    from sqlalchemy import event

    store = test_repo.issued_forecast_store
    store.insert(_issued_forecast())
    statements: list[str] = []

    def record(conn, cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(test_repo.engine, "before_cursor_execute", record)
    try:
        assert store.exists(ISSUED_AT) is True
    finally:
        event.remove(test_repo.engine, "before_cursor_execute", record)

    assert len(statements) == 1
    assert "issued_forecast_step" not in statements[0]


def test_issued_forecast_repository_works_standalone(sqlite_engine: Engine) -> None:
    repository = IssuedForecastRepository(engine=sqlite_engine)
    forecast = _issued_forecast()

    assert repository.insert(forecast) is True
    assert repository.fetch(ISSUED_AT) == forecast


def test_issued_forecast_rejects_a_status_other_than_normal_or_degraded() -> None:
    with pytest.raises(ValueError, match="status"):
        replace(_issued_forecast(), status="unavailable")


def test_issued_forecast_status_is_a_forecast_mode() -> None:
    assert _issued_forecast().status is ForecastMode.DEGRADED


def test_reading_an_issued_forecast_returns_its_status_as_a_forecast_mode(
    sqlite_engine: Engine,
) -> None:
    repository = IssuedForecastRepository(engine=sqlite_engine)
    repository.insert(_issued_forecast())

    assert repository.fetch(ISSUED_AT).status is ForecastMode.DEGRADED


def test_reading_an_issued_forecast_with_an_unknown_status_is_rejected(
    sqlite_engine: Engine,
) -> None:
    repository = IssuedForecastRepository(engine=sqlite_engine)
    repository.insert(_issued_forecast())
    with sqlite_engine.begin() as conn:
        conn.execute(text("UPDATE issued_forecast SET status = 'unavailable'"))

    with pytest.raises(ValueError, match="unavailable"):
        repository.fetch(ISSUED_AT)


def test_issued_forecast_rejects_a_model_identity_that_is_not_a_full_sha256() -> None:
    with pytest.raises(ValueError, match="model_sha256"):
        replace(_issued_forecast(), model_sha256="abc")


def test_latest_issued_forecast_is_the_one_with_the_latest_issue_time(
    test_repo: TimeSeriesRepository,
) -> None:
    """Insertion order does not matter: an earlier issue written later is not the latest."""
    latest = _issued_forecast(ISSUED_AT + timedelta(hours=1))
    test_repo.issued_forecast_store.insert(latest)
    test_repo.issued_forecast_store.insert(_issued_forecast())

    assert test_repo.issued_forecast_store.fetch_latest() == latest


def test_latest_issued_forecast_is_none_before_the_first_issue(
    test_repo: TimeSeriesRepository,
) -> None:
    assert test_repo.issued_forecast_store.fetch_latest() is None
