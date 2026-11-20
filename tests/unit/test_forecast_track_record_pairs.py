"""Pairing issued forecast steps with valid hourly observations for the forecast track record (ADR-0013 §2.2)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.repository import TimeSeriesRepository

WINDOW_START = datetime(2026, 11, 18, 0, 0)
WINDOW_END = datetime(2026, 11, 21, 0, 0)


def _issue(
    repo: TimeSeriesRepository,
    issued_at: datetime,
    target_hours: list[datetime],
    *,
    status: str = "normal",
) -> None:
    """Issue a forecast whose step for each target hour predicts 30000 MW plus its index."""
    repo.insert_issued_forecast(
        IssuedForecast(
            issued_at=issued_at,
            load_anchor=issued_at.replace(minute=0) - timedelta(hours=1),
            status=status,
            model_sha256="a" * 64,
            mlflow_model_version=None,
            steps=tuple(
                IssuedForecastStep(target_hour=hour, predicted_load_mw=30000.0 + index)
                for index, hour in enumerate(target_hours)
            ),
        )
    )


def _observe(
    repo: TimeSeriesRepository,
    hours: list[datetime],
    *,
    subject: str = "nationwide",
    source: str = REGIONAL_SNAPSHOT_SUM_SOURCE,
) -> None:
    """Persist hourly load of 25000 MW for each hour."""
    repo.upsert_taipower_load(
        pd.DataFrame({"datetime": hours, "load_mw": [25000.0] * len(hours)}),
        default_subject=subject,
        source=source,
    )


def _pairs(repo: TimeSeriesRepository) -> list[tuple[datetime, datetime, int]]:
    return [
        (pair.issued_at, pair.target_hour, pair.lead_time_hours)
        for pair in repo.fetch_track_record_pairs(WINDOW_START, WINDOW_END)
    ]


def test_lead_time_rounds_up_from_the_issue_time_and_skips_hours_not_after_it(
    test_repo: TimeSeriesRepository,
) -> None:
    """Issued at 10:15: 10:00 is not a forecast, 11:00 is lead 1, the next day's 10:00 is lead 24."""
    issued_at = datetime(2026, 11, 19, 10, 15)
    targets = [
        datetime(2026, 11, 19, 9, 0),
        datetime(2026, 11, 19, 10, 0),
        datetime(2026, 11, 19, 11, 0),
        datetime(2026, 11, 20, 10, 0),
    ]
    _issue(test_repo, issued_at, targets)
    _observe(test_repo, targets)

    assert _pairs(test_repo) == [
        (issued_at, datetime(2026, 11, 19, 11, 0), 1),
        (issued_at, datetime(2026, 11, 20, 10, 0), 24),
    ]


@pytest.mark.parametrize(
    "observe_other",
    [
        pytest.param(lambda _repo, _hour: None, id="no-load-row"),
        pytest.param(
            lambda repo, hour: _observe(repo, [hour], source="legacy_api"),
            id="not-regional-snapshot-sum",
        ),
        pytest.param(
            lambda repo, hour: _observe(repo, [hour], subject="north"),
            id="not-nationwide",
        ),
    ],
)
def test_target_hour_without_a_valid_hourly_observation_is_not_paired(
    test_repo: TimeSeriesRepository, observe_other
) -> None:
    issued_at = datetime(2026, 11, 19, 10, 15)
    observed = datetime(2026, 11, 19, 11, 0)
    unobserved = datetime(2026, 11, 19, 12, 0)
    _issue(test_repo, issued_at, [observed, unobserved])
    _observe(test_repo, [observed])
    observe_other(test_repo, unobserved)

    assert [
        pair.target_hour for pair in test_repo.fetch_track_record_pairs(WINDOW_START, WINDOW_END)
    ] == [observed]


def test_degraded_forecast_pairs_like_a_normal_one(test_repo: TimeSeriesRepository) -> None:
    target = datetime(2026, 11, 19, 12, 0)
    _issue(test_repo, datetime(2026, 11, 19, 10, 15), [target], status="degraded")
    _issue(test_repo, datetime(2026, 11, 19, 11, 15), [target], status="normal")
    _observe(test_repo, [target])

    pairs = test_repo.fetch_track_record_pairs(WINDOW_START, WINDOW_END)

    assert [
        (pair.lead_time_hours, pair.predicted_load_mw, pair.actual_load_mw) for pair in pairs
    ] == [
        (2, 30000.0, 25000.0),
        (1, 30000.0, 25000.0),
    ]


def test_window_counts_its_first_target_hour_and_excludes_its_end_whatever_the_issue_time(
    test_repo: TimeSeriesRepository,
) -> None:
    """A step issued a week before the window still counts when its target hour is inside."""
    before_window = WINDOW_START - timedelta(hours=1)
    last_in_window = WINDOW_END - timedelta(hours=1)
    early_issue = WINDOW_START - timedelta(hours=166, minutes=45)
    _issue(test_repo, early_issue, [before_window, WINDOW_START])
    _issue(test_repo, last_in_window - timedelta(minutes=45), [last_in_window, WINDOW_END])
    _observe(test_repo, [before_window, WINDOW_START, last_in_window, WINDOW_END])

    assert _pairs(test_repo) == [
        (early_issue, WINDOW_START, 167),
        (last_in_window - timedelta(minutes=45), last_in_window, 1),
    ]
