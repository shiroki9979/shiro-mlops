"""Weather and audit readers preserve vintage, filter, and missing-identifier contracts."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.datasets import (
    CWA_FORECAST_AUDITS,
    CWA_FORECASTS,
    CWA_OBSERVATION_AUDITS,
    CWA_OBSERVATIONS,
    Dataset,
)
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from tests.helpers import TAIWAN, DatasetLister, explorer_pages, rfc3339


def test_observation_pages_keep_microseconds_station_key_and_window_gaps(
    sqlite_engine: Engine,
) -> None:
    rows = [
        ("2026-09-20 04:00:00.900002+00:00", "467490", 4.0),
        ("2026-09-20 04:00:00.900002+00:00", "466920", 3.0),
        ("2026-09-20 04:00:00.900001+00:00", "466920", 2.0),
        ("2026-09-20 02:00:00.100000+00:00", "466920", 1.0),
    ]
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_cwa_station_observation "
                "(observed_at, station_id, station_name, town_code, temperature_c) "
                "VALUES (:observed_at, :station_id, :station_id, '63000050', :temperature_c)"
            ),
            [
                {"observed_at": observed, "station_id": station, "temperature_c": temperature}
                for observed, station, temperature in rows
            ],
        )
    reader = DatasetLister(sqlite_engine, CWA_OBSERVATIONS)
    params = {
        "start": "2026-09-20T10:00:00+08:00",
        "end": "2026-09-20T12:00:01+08:00",
        "limit": 1,
    }

    pages = explorer_pages(reader, params)

    assert [page.items[0]["temperature_c"] for page in pages] == [4.0, 3.0, 2.0, 1.0]
    assert [page.items[0]["observed_at"] for page in pages[:3]] == ["2026-09-20T12:00:00+08:00"] * 3
    assert [page.has_more for page in pages] == [True, True, True, False]
    assert all(page.missing_slots == pages[0].missing_slots for page in pages)
    station = reader.list({**params, "station_id": "466920", "limit": 2})
    assert [item["temperature_c"] for item in station.items] == [3.0, 2.0]
    assert "2026-09-20T11:00:00+08:00:466920" in station.missing_slots
    with pytest.raises(CursorError, match="filter"):
        reader.list({**params, "station_id": "466920", "cursor": pages[0].next_cursor})
    assert (
        reader.list({**params, "cursor": pages[0].next_cursor, "limit": 2}).items[0][
            "temperature_c"
        ]
        == 3.0
    )


@pytest.mark.parametrize("dataset", [CWA_OBSERVATIONS, CWA_FORECASTS])
def test_weather_readers_answer_an_empty_last_page_without_matching_rows(
    sqlite_engine: Engine, dataset: Dataset
) -> None:
    """No matching data returns an empty last page so absence differs from a query failure."""
    reader = DatasetLister(sqlite_engine, dataset)

    page = reader.list({"start": "2026-09-20T10:00:00+08:00", "end": "2026-09-20T12:00:00+08:00"})

    assert page.items == []
    assert page.has_more is False
    assert page.next_cursor is None


def test_observation_and_audit_readers_keep_station_and_missing_id_filters(
    test_repo: TimeSeriesRepository,
) -> None:
    """觀測與 audit reader 必須支援 station／missing identifier 篩選，且不回傳 raw payload。"""
    observed = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            missing_station_ids=("467490",),
            raw_payload={"secret": "do-not-return"},
            observations=(
                CWAStationObservation(
                    observed_at=pd.Timestamp(observed),
                    station_id="466920",
                    station_name="臺北",
                    town_code="63000050",
                    temperature_c=None,
                    relative_humidity_pct=80.0,
                    air_pressure_hpa=None,
                    precipitation_mm=0.0,
                    wind_speed_m_s=None,
                    wind_direction_deg=None,
                ),
            ),
        )
    )
    window = {
        "start": rfc3339(observed - timedelta(hours=1)),
        "end": rfc3339(observed),
    }

    observations = DatasetLister(test_repo.engine, CWA_OBSERVATIONS).list(
        {**window, "station_id": "466920"}
    )
    assert observations.items[0]["temperature_c"] is None
    assert observations.items[0]["precipitation_mm"] == 0.0
    assert "raw_payload" not in observations.items[0]

    audits = DatasetLister(test_repo.engine, CWA_OBSERVATION_AUDITS).list(
        {**window, "status": "incomplete", "missing_station_id": "467490"}
    )
    assert audits.items[0]["missing_station_ids"] == ["467490"]
    assert "raw_payload" not in audits.items[0]

    with pytest.raises(ExplorerQueryError, match="status"):
        DatasetLister(test_repo.engine, CWA_OBSERVATION_AUDITS).list({**window, "status": "bogus"})


def test_forecast_reader_defaults_to_latest_vintage_and_keeps_explicit_filters(
    test_repo: TimeSeriesRepository,
) -> None:
    """未指定版本時預設最新發布；all_vintages 與 source_updated_at 必須維持既有語意。"""
    older = datetime.now(TAIWAN).replace(
        tzinfo=None, minute=0, second=0, microsecond=0
    ) - timedelta(hours=2)
    newer = older + timedelta(hours=1)
    valid = newer + timedelta(hours=3)

    def release(issued_at: datetime, temperature: float) -> CWAForecastRelease:
        return CWAForecastRelease(
            dataset_id="F-D0047-089",
            issued_at=pd.Timestamp(issued_at),
            source_updated_at=pd.Timestamp(issued_at),
            fetched_at=issued_at,
            missing_geocodes=(),
            raw_payload={"secret": "do-not-return"},
            forecasts=(
                CWATownshipForecast(
                    valid_from=pd.Timestamp(valid),
                    valid_to=pd.Timestamp(valid),
                    geocode="63000050",
                    location_name="臺北",
                    temperature_c=temperature,
                    dew_point_c=None,
                    apparent_temperature_c=None,
                    relative_humidity_pct=70.0,
                    probability_of_precipitation_pct=None,
                    wind_speed_m_s=None,
                    wind_direction=None,
                ),
            ),
        )

    test_repo.cwa_weather_store.upsert_cwa_forecast_releases([release(older, 28.0)])
    test_repo.cwa_weather_store.upsert_cwa_forecast_releases([release(newer, 31.0)])
    window = {
        "start": rfc3339(valid - timedelta(hours=1)),
        "end": rfc3339(valid),
    }
    reader = DatasetLister(test_repo.engine, CWA_FORECASTS)

    latest = reader.list(window)
    assert [item["temperature_c"] for item in latest.items] == [31.0]
    assert latest.items[0]["issued_at"] == rfc3339(newer)
    assert "raw_payload" not in latest.items[0]

    all_vintages = reader.list({**window, "all_vintages": "true"})
    assert {item["temperature_c"] for item in all_vintages.items} == {28.0, 31.0}

    older_vintage = reader.list({**window, "source_updated_at": rfc3339(older)})
    assert [item["temperature_c"] for item in older_vintage.items] == [28.0]

    by_issued = reader.list({**window, "issued_at": rfc3339(older)})
    assert [item["temperature_c"] for item in by_issued.items] == [28.0]

    audits = DatasetLister(test_repo.engine, CWA_FORECAST_AUDITS).list(
        {"start": rfc3339(older - timedelta(hours=1)), "end": rfc3339(newer)}
    )
    assert {item["issued_at"] for item in audits.items} == {rfc3339(older), rfc3339(newer)}
    assert "raw_payload" not in audits.items[0]
