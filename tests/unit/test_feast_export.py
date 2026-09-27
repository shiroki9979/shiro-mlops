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


def test_feast_exports_key_both_frozen_views_by_prediction_subject() -> None:
    """Feast 凍結 schema 保留 location entity，值為預測對象而非氣象代表點。"""
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
