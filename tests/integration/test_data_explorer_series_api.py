"""Data Explorer series HTTP contract on a real SQLite repository."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from tests.helpers import rfc3339, write_derived_load
from tests.scenarios.data_explorer_audit_series import (
    AUDIT_SERIES_SCENARIOS,
    AUDIT_STATUS_SCENARIOS,
)
from tests.scenarios.data_explorer_series import (
    LOAD_SERIES_PATH,
    SERIES_SCENARIOS,
    series_client,
)
from tests.scenarios.data_explorer_supply_demand_series import SUPPLY_DEMAND_SERIES_SCENARIOS
from tests.scenarios.data_explorer_unit_series import UNIT_SERIES_SCENARIOS


@pytest.mark.parametrize("scenario", SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_series_scenarios_on_sqlite(scenario, test_repo: TimeSeriesRepository) -> None:
    scenario(test_repo)


@pytest.mark.parametrize(
    "scenario", SUPPLY_DEMAND_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__
)
def test_supply_demand_series_scenarios_on_sqlite(
    scenario, test_repo: TimeSeriesRepository
) -> None:
    scenario(test_repo)


@pytest.mark.parametrize("scenario", UNIT_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_unit_series_scenarios_on_sqlite(scenario, test_repo: TimeSeriesRepository) -> None:
    scenario(test_repo)


@pytest.fixture
def series_client_for(test_repo: TimeSeriesRepository):
    with series_client(test_repo) as client:
        yield client, test_repo


def _window(start: datetime, end: datetime) -> dict[str, str]:
    return {"start": rfc3339(start), "end": rfc3339(end)}


def test_empty_window_returns_empty_series(series_client_for) -> None:
    """窗口內沒有資料時回 200 與空的 series。"""
    client, _repo = series_client_for
    response = client.get(
        LOAD_SERIES_PATH, params=_window(datetime(2026, 9, 1), datetime(2026, 9, 2))
    )

    assert response.status_code == 200
    assert response.json()["series"] == []


def test_series_returns_503_when_database_unavailable(series_client_for) -> None:
    """資料庫無法連線時 series 回 503。"""
    client, repo = series_client_for

    class BrokenEngine:
        def connect(self):
            raise SQLAlchemyError("connection refused")

    repo.engine = BrokenEngine()
    assert client.get(LOAD_SERIES_PATH).status_code == 503


def test_undeclared_parameters_are_rejected(series_client_for) -> None:
    """series 不接受未宣告的參數（例如 cursor 或其他資料集的 group_by），回 422。"""
    client, _repo = series_client_for

    assert client.get(LOAD_SERIES_PATH, params={"cursor": "abc"}).status_code == 422
    assert client.get(LOAD_SERIES_PATH, params={"group_by": "subject"}).status_code == 422


def test_undeclared_parameter_sent_empty_is_rejected(series_client_for) -> None:
    """值為空的未宣告參數也回 422，與 list 相同。"""
    client, _repo = series_client_for

    response = client.get(LOAD_SERIES_PATH, params={"regoin": ""})

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported series parameters: regoin"


def test_declared_filter_sent_empty_is_read_as_not_given(series_client_for) -> None:
    """值為空的已宣告篩選視為沒有篩選。"""
    client, _repo = series_client_for

    with_empty = client.get(LOAD_SERIES_PATH, params={"subject": ""})

    assert with_empty.status_code == 200
    assert with_empty.json()["series"] == client.get(LOAD_SERIES_PATH).json()["series"]


def test_repeated_fields_parameter_is_read_as_a_list(series_client_for) -> None:
    """fields 可重複出現，重複的欄位只產生一條 series。"""
    client, repo = series_client_for
    hour = datetime(2026, 11, 18, 10, 0)
    write_derived_load(repo.engine, pd.DataFrame({DATETIME_COL: [hour], LOAD_MW_COL: [30000.0]}))

    response = client.get(
        f"{LOAD_SERIES_PATH}?fields=load_mw&fields=load_mw",
        params=_window(hour, hour),
    )

    assert response.status_code == 200
    assert [series["field"] for series in response.json()["series"]] == ["load_mw"]


def test_hours_not_yet_derived_are_not_gap_filled(
    series_client_for, monkeypatch: pytest.MonkeyPatch
) -> None:
    """尚未結束的小時與現在之後的 bucket 不算缺口，也不補 null，與列表缺口口徑一致。"""
    client, repo = series_client_for
    hour = datetime(2026, 11, 18, 10, 0)
    write_derived_load(repo.engine, pd.DataFrame({DATETIME_COL: [hour], LOAD_MW_COL: [30000.0]}))
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.series.now_taiwan",
        lambda: hour + timedelta(hours=2, minutes=30),
    )

    response = client.get(
        LOAD_SERIES_PATH, params={**_window(hour, hour + timedelta(hours=5)), "bucket": "1h"}
    )

    points = response.json()["series"][0]["points"]
    assert [(point["t"], point["v"]) for point in points] == [
        ("2026-11-18T10:00:00+08:00", 30000.0),
        ("2026-11-18T11:00:00+08:00", None),
    ]


@pytest.mark.parametrize(
    ("minutes_past", "filled"),
    [(9, []), (10, [("2026-11-18T11:00:00+08:00", None)])],
    ids=["derivation-running", "derivation-due"],
)
def test_an_ended_hour_is_gap_filled_only_after_the_scheduled_derivation(
    series_client_for, monkeypatch: pytest.MonkeyPatch, minutes_past: int, filled: list
) -> None:
    """11:00 那一小時由 12:05 的推算寫入；寬限內圖表不補 null，與列表缺口一致（#373）。"""
    client, repo = series_client_for
    hour = datetime(2026, 11, 18, 10, 0)
    write_derived_load(repo.engine, pd.DataFrame({DATETIME_COL: [hour], LOAD_MW_COL: [30000.0]}))
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.series.now_taiwan",
        lambda: hour + timedelta(hours=2, minutes=minutes_past),
    )

    response = client.get(
        LOAD_SERIES_PATH, params={**_window(hour, hour + timedelta(hours=5)), "bucket": "1h"}
    )

    points = response.json()["series"][0]["points"]
    assert [(point["t"], point["v"]) for point in points] == [
        ("2026-11-18T10:00:00+08:00", 30000.0),
        *filled,
    ]


@pytest.mark.parametrize("scenario", AUDIT_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_audit_series_scenarios_on_sqlite(scenario, test_repo: TimeSeriesRepository) -> None:
    scenario(test_repo)


@pytest.mark.parametrize("scenario", AUDIT_STATUS_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_audit_status_scenarios_on_sqlite(scenario, test_repo: TimeSeriesRepository) -> None:
    scenario(test_repo)


SERIES_PATHS_WITH_FIELDS = [
    "/data/power/load/series",
    "/data/power/supply-demand/series",
    "/data/power/regional/series",
    "/data/power/units/series",
    "/data/weather/observations/series",
    "/data/weather/forecasts/series",
]
COUNT_SERIES_PATHS = ["/data/audits/cwa-observations/series", "/data/audits/cwa-forecasts/series"]


@pytest.mark.parametrize("path", SERIES_PATHS_WITH_FIELDS)
def test_declared_series_options_sent_empty_read_as_not_given(series_client_for, path) -> None:
    """A form that clears a select sends `bucket=`; the contract reads it as the default."""
    client, _repo = series_client_for
    window = _window(datetime(2026, 9, 1), datetime(2026, 9, 2))

    with_empty = client.get(path, params={**window, "bucket": "", "agg": "", "fields": ""})
    without = client.get(path, params=window)

    assert with_empty.status_code == 200, with_empty.json()
    assert with_empty.json() == without.json()


@pytest.mark.parametrize("path", COUNT_SERIES_PATHS)
def test_an_empty_bucket_reads_as_not_given_on_count_series(series_client_for, path) -> None:
    client, _repo = series_client_for
    window = _window(datetime(2026, 9, 1), datetime(2026, 9, 2))

    response = client.get(path, params={**window, "bucket": ""})

    assert response.status_code == 200, response.json()
    assert response.json()["bucket"] == client.get(path, params=window).json()["bucket"]


def test_an_empty_group_by_reads_as_not_given(series_client_for) -> None:
    client, _repo = series_client_for
    window = _window(datetime(2026, 9, 1), datetime(2026, 9, 2))

    response = client.get("/data/power/units/series", params={**window, "group_by": ""})

    assert response.status_code == 200, response.json()


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("bucket", "weekly"), ("agg", "sum"), ("fields", "not_a_field"), ("group_by", "plant")],
)
def test_a_declared_series_option_with_an_unknown_value_is_still_rejected(
    series_client_for, parameter: str, value: str
) -> None:
    client, _repo = series_client_for

    response = client.get("/data/power/units/series", params={parameter: value})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
