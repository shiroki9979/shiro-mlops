"""Shared test builders for canonical CWA persistence seams."""

import pandas as pd

from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAObservationBatch,
    CWAStationObservation,
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
