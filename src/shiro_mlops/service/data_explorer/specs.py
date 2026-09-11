"""Dataset catalog shared by typed queries, readers, and status."""

from typing import Any

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

DATASET_SPECS: dict[str, dict[str, Any]] = {
    "hourly_load": {
        "label": "逐時用電負載",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/power/load",
        "sort": ("time", "location"),
    },
    "national_supply_demand": {
        "label": "全台供需",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/supply-demand",
        "sort": ("observed_at",),
    },
    "regional_supply_demand": {
        "label": "區域供需",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/regional",
        "sort": ("observed_at", "region"),
    },
    "unit_generation": {
        "label": "機組發電",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/units",
        "sort": ("observed_at", "unit_type", "unit_name"),
    },
    "cwa_observations": {
        "label": "CWA 測站觀測",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/weather/observations",
        "sort": ("observed_at", "station_id"),
    },
    "cwa_forecasts": {
        "label": "CWA 鄉鎮預報",
        "cadence": 3600,
        "max_days": 14,
        "href": "/data/weather/forecasts",
        "sort": (
            "valid_from",
            "issued_at",
            "source_updated_at",
            "dataset_id",
            "geocode",
            "valid_to",
        ),
    },
    "cwa_observation_audits": {
        "label": "CWA 觀測批次審計",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/audits?type=observations",
        "sort": ("fetched_at",),
    },
    "cwa_forecast_audits": {
        "label": "CWA 預報版本審計",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/audits?type=forecasts",
        "sort": ("issued_at", "source_updated_at", "dataset_id"),
    },
}
