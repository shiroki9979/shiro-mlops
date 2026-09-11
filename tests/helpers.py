"""集中共用測試資料，避免測試模組互相依賴私有 builder。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
    parse_regional_supply_demand_csv,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandSnapshot,
    parse_supply_demand_payload,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationSnapshot,
    parse_unit_generation_payload,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TAIWAN = ZoneInfo(TAIWAN_TZ)


def rfc3339(value: datetime) -> str:
    """測試時間統一套用臺灣時區，避免各測試產生不同 offset 語意。"""
    return value.replace(tzinfo=TAIWAN).isoformat(timespec="seconds")


def supply_demand_snapshot(
    observed_at: datetime | None = None,
) -> TaipowerSupplyDemandSnapshot:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    with (FIXTURES_DIR / "taipower_supply_demand_sample.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    return parse_supply_demand_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def regional_supply_demand_snapshots(
    observed_at: datetime | None = None,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    csv_text = (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(
        encoding="utf-8"
    )
    return parse_regional_supply_demand_csv(
        csv_text,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def unit_generation_snapshots(
    observed_at: datetime | None = None,
) -> list[TaipowerUnitGenerationSnapshot]:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    with (FIXTURES_DIR / "taipower_unit_generation_sample.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    return parse_unit_generation_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def township_forecast(
    valid_from: datetime,
    temperature_c: float,
    *,
    valid_to: datetime | None = None,
    relative_humidity_pct: float | None = None,
) -> CWATownshipForecast:
    """集中預報測試預設值，讓個別測試只呈現契約差異。"""
    return CWATownshipForecast(
        valid_from=pd.Timestamp(valid_from),
        valid_to=pd.Timestamp(valid_to or valid_from),
        geocode="63000050",
        location_name="臺北",
        temperature_c=temperature_c,
        dew_point_c=None,
        apparent_temperature_c=None,
        relative_humidity_pct=relative_humidity_pct,
        probability_of_precipitation_pct=None,
        wind_speed_m_s=None,
        wind_direction=None,
    )


def forecast_release(
    issued_at: datetime,
    forecasts: tuple[CWATownshipForecast, ...],
    *,
    raw_payload: dict[str, Any] | None = None,
) -> CWAForecastRelease:
    """集中 release 識別與完整度預設值，讓分頁測試聚焦版本行為。"""
    return CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=pd.Timestamp(issued_at),
        source_updated_at=pd.Timestamp(issued_at),
        fetched_at=issued_at,
        status="complete",
        missing_geocodes=(),
        raw_payload=raw_payload or {},
        forecasts=forecasts,
    )


def canonical_observation_batch(frame: pd.DataFrame) -> CWAObservationBatch:
    """Build canonical observations from fixture rows with an explicit allowed location."""
    locations = {location.alias: location for location in DEFAULT_CWA_LOCATIONS.values()}
    observations = []
    for row in frame.itertuples():
        location = locations[row.location]
        observations.append(
            CWAStationObservation(
                observed_at=pd.Timestamp(row.datetime),
                station_id=location.station_id,
                station_name=location.alias,
                town_code=location.geocode,
                temperature_c=float(row.temperature) if pd.notna(row.temperature) else None,
                relative_humidity_pct=(
                    float(row.relative_humidity) if pd.notna(row.relative_humidity) else None
                ),
                air_pressure_hpa=None,
                precipitation_mm=None,
                wind_speed_m_s=None,
                wind_direction_deg=None,
            )
        )
    return CWAObservationBatch(
        fetched_at=pd.Timestamp(frame.datetime.max()).to_pydatetime(),
        status="complete",
        missing_station_ids=(),
        raw_payload={"fixture": "canonical_observation_batch"},
        observations=tuple(observations),
    )
