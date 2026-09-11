"""Weather and audit readers preserve vintage, filter, and missing-identifier contracts."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.weather import (
    ForecastAuditReader,
    ForecastReader,
    ObservationAuditReader,
    ObservationReader,
)
from tests.helpers import TAIWAN, rfc3339


def test_observation_and_audit_readers_keep_station_and_missing_id_filters(
    test_repo: TimeSeriesRepository,
) -> None:
    """觀測與 audit reader 必須支援 station／missing identifier 篩選，且不回傳 raw payload。"""
    observed = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            status="incomplete",
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

    observations = ObservationReader(test_repo.engine).list({**window, "station_id": "466920"})
    assert observations.items[0]["temperature_c"] is None
    assert observations.items[0]["precipitation_mm"] == 0.0
    assert "raw_payload" not in observations.items[0]

    audits = ObservationAuditReader(test_repo.engine).list(
        {**window, "status": "incomplete", "missing_station_id": "467490"}
    )
    assert audits.items[0]["missing_station_ids"] == ["467490"]
    assert "raw_payload" not in audits.items[0]

    with pytest.raises(ExplorerQueryError, match="status"):
        ObservationAuditReader(test_repo.engine).list({**window, "status": "bogus"})


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
            status="complete",
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

    test_repo.upsert_cwa_forecast_release(release(older, 28.0))
    test_repo.upsert_cwa_forecast_release(release(newer, 31.0))
    window = {
        "start": rfc3339(valid - timedelta(hours=1)),
        "end": rfc3339(valid),
    }
    reader = ForecastReader(test_repo.engine)

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

    audits = ForecastAuditReader(test_repo.engine).list(
        {"start": rfc3339(older - timedelta(hours=1)), "end": rfc3339(newer)}
    )
    assert {item["issued_at"] for item in audits.items} == {rfc3339(older), rfc3339(newer)}
    assert "raw_payload" not in audits.items[0]
