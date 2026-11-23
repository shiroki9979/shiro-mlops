"""Unit tests for the frozen Feast export computed directly from target load."""

import pandas as pd

from shiro_mlops.features.feast_export import build_feast_feature_frames


def test_feast_export_lag_features_do_not_use_future_load() -> None:
    """Feast export warm-up lags must use a non-leaking sentinel, not later load values."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 300.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 03:00:00", "load_mw": 8888.0, "subject": "nationwide"},
        ]
    )
    weather_df = pd.DataFrame(
        [
            {
                "datetime": f"2026-08-20 0{i}:00:00",
                "temperature": 30.0,
                "relative_humidity": 70.0,
            }
            for i in range(4)
        ]
    )

    exported = build_feast_feature_frames(load_df, weather_df).taipower.sort_values("datetime")

    assert (exported.iloc[:3]["load_mw_lag_1"] != 8888.0).all()
    assert exported.iloc[0]["load_mw_lag_1"] == 0.0
    assert exported.iloc[1]["load_mw_lag_1"] == 100.0
    assert exported.iloc[0]["load_mw_lag_24"] == 0.0
    assert exported.iloc[0]["load_mw_rolling_mean_24"] == 0.0


def test_feast_export_sorts_unordered_load_before_computing_lags() -> None:
    """Lags follow event time even when the source rows arrive out of order."""
    load_df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-08-20 02:00", "2026-08-20 00:00", "2026-08-20 01:00"]
            ),
            "subject": "nationwide",
            "load_mw": [300.0, 100.0, 200.0],
        }
    )
    weather_df = pd.DataFrame(
        {"datetime": load_df["datetime"], "temperature": 30.0, "relative_humidity": 70.0}
    )

    exported = build_feast_feature_frames(load_df, weather_df).taipower

    assert exported["load_mw_lag_1"].tolist() == [0.0, 100.0, 200.0]


def test_feast_export_uses_elapsed_hours_when_load_hour_is_missing() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 10:00", "2026-09-20 12:00", "2026-09-20 13:00"]
            ),
            "subject": "nationwide",
            "load_mw": [100.0, 120.0, 130.0],
        }
    )
    weather = pd.DataFrame(
        {"datetime": load["datetime"], "temperature": 30.0, "relative_humidity": 70.0}
    )

    exported = build_feast_feature_frames(load, weather).taipower

    assert exported.loc[0, "load_mw_lag_1"] == 0.0
    assert pd.isna(exported.loc[1, "load_mw_lag_1"])
    assert exported.loc[1, "load_mw_lag_2"] == 100.0
    assert pd.isna(exported.loc[2, "load_mw_lag_2"])
    assert exported.loc[2, "load_mw_rolling_mean_6"] == 110.0


def test_feast_export_keeps_last_duplicate_before_calculating_history() -> None:
    load = pd.DataFrame(
        {
            "datetime": [
                "2026-09-20 10:00",
                "2026-09-20 12:00",
                "2026-09-20 12:00",
                "2026-09-20 13:00",
            ],
            "subject": "nationwide",
            "load_mw": [100.0, 120.0, 125.0, 130.0],
        }
    )
    weather = pd.DataFrame(
        {"datetime": ["2026-09-20 10:00"], "temperature": [30.0], "relative_humidity": [70.0]}
    )

    exported = build_feast_feature_frames(load, weather).taipower

    assert exported["load_mw"].tolist() == [100.0, 125.0, 130.0]
    assert exported.loc[2, "load_mw_lag_1"] == 125.0
    assert exported.loc[2, "load_mw_rolling_mean_6"] == 112.5


def test_feast_exports_key_both_frozen_views_by_prediction_subject() -> None:
    """The frozen Feast location entity names the prediction subject rather than the weather reference point."""
    times = pd.date_range("2026-08-20 00:00:00", periods=4, freq="h")
    load = pd.DataFrame({"datetime": times, "subject": "nationwide", "load_mw": 100.0})
    weather = pd.DataFrame(
        {"datetime": times, "location": "Taipei", "temperature": 30.0, "relative_humidity": 70.0}
    )

    frames = build_feast_feature_frames(load, weather)

    assert list(frames.taipower.columns[:2]) == ["datetime", "location"]
    assert "subject" not in frames.taipower.columns
    assert set(frames.taipower["location"]) == {"nationwide"}
    assert list(frames.weather.columns) == [
        "datetime",
        "location",
        "temperature",
        "relative_humidity",
    ]
    assert set(frames.weather["location"]) == {"nationwide"}


def test_feast_load_export_marks_days_off_beside_the_weekend_flag() -> None:
    """2026-10-09 (Fri) is the National Day substitute holiday; 10-08 is a workday."""
    times = pd.to_datetime(["2026-10-08 12:00", "2026-10-09 12:00", "2026-10-10 12:00"])
    load = pd.DataFrame({"datetime": times, "subject": "nationwide", "load_mw": 100.0})

    exported = build_feast_feature_frames(load, pd.DataFrame({"datetime": times})).taipower

    assert exported["is_day_off"].tolist() == [0, 1, 1]
    assert exported["is_weekend"].tolist() == [0, 0, 1]
    assert exported["is_day_off"].dtype == "int64"


def test_feast_weather_export_leaves_missing_readings_missing() -> None:
    """A fabricated 25 °C / 70 % is indistinguishable from a real reading once exported."""
    times = pd.date_range("2026-09-01 00:00", periods=3, freq="h")
    load = pd.DataFrame({"datetime": times, "load_mw": [30000.0, 30100.0, 30200.0]})
    weather = pd.DataFrame(
        {
            "datetime": times,
            "temperature": [28.0, None, 29.0],
            "relative_humidity": [None, 71.0, "not-a-number"],
        }
    )

    exported = build_feast_feature_frames(load, weather).weather

    assert exported["temperature"].isna().tolist() == [False, True, False]
    assert exported["relative_humidity"].isna().tolist() == [True, False, True]
    assert exported["temperature"].dtype == "float32"
    assert exported.loc[1, "relative_humidity"] == 71.0


def test_feast_weather_export_keeps_an_absent_field_as_a_missing_column() -> None:
    times = pd.date_range("2026-09-01 00:00", periods=2, freq="h")
    load = pd.DataFrame({"datetime": times, "load_mw": [30000.0, 30100.0]})
    weather = pd.DataFrame({"datetime": times, "temperature": [28.0, 28.5]})

    exported = build_feast_feature_frames(load, weather).weather

    assert list(exported.columns) == ["datetime", "location", "temperature", "relative_humidity"]
    assert exported["relative_humidity"].isna().all()
    assert exported["relative_humidity"].dtype == "float32"
