"""Unit tests for feature transformation functions."""

import pandas as pd

from shiro_mlops.core.constants import LOAD_MW_COL
from shiro_mlops.features.transformers import (
    build_feature_pipeline,
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
    merge_weather_features,
)


def test_create_calendar_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test cyclical and calendar feature creation."""
    res = create_calendar_features(taipower_raw_df)
    assert "hour" in res.columns
    assert "dayofweek" in res.columns
    assert "is_weekend" in res.columns
    assert "hour_sin" in res.columns
    assert "hour_cos" in res.columns

    # Verify cyclical bounds
    assert res["hour_sin"].between(-1.0, 1.0).all()
    assert res["hour_cos"].between(-1.0, 1.0).all()


def test_create_lag_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test lag feature generation."""
    lags = [1, 2, 24]
    res = create_lag_features(taipower_raw_df, value_col=LOAD_MW_COL, lags=lags)

    for lag in lags:
        col_name = f"{LOAD_MW_COL}_lag_{lag}"
        assert col_name in res.columns
        # First `lag` entries should be NaN
        assert pd.isna(res[col_name].iloc[0])
        # Entry at index `lag` should equal original value at index 0
        assert res[col_name].iloc[lag] == taipower_raw_df[LOAD_MW_COL].iloc[0]


def test_lag_features_use_elapsed_hours_when_a_load_hour_is_missing() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 10:00", "2026-09-20 12:00", "2026-09-20 13:00"]
            ),
            "load_mw": [100.0, 120.0, 130.0],
        }
    )

    features = create_lag_features(load, lags=[1, 2])

    assert pd.isna(features.loc[1, "load_mw_lag_1"])
    assert features.loc[1, "load_mw_lag_2"] == 100.0
    assert features.loc[2, "load_mw_lag_1"] == 120.0
    assert pd.isna(features.loc[2, "load_mw_lag_2"])


def test_create_rolling_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test rolling window mean and standard deviation features."""
    windows = [6, 24]
    res = create_rolling_features(taipower_raw_df, value_col=LOAD_MW_COL, windows=windows)

    for w in windows:
        assert f"{LOAD_MW_COL}_rolling_mean_{w}" in res.columns
        assert f"{LOAD_MW_COL}_rolling_std_{w}" in res.columns


def test_rolling_features_use_elapsed_hours_when_a_load_hour_is_missing() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 10:00", "2026-09-20 12:00", "2026-09-20 13:00"]
            ),
            "load_mw": [100.0, 120.0, 130.0],
        }
    )

    features = create_rolling_features(load, windows=[2])

    assert features.loc[1, "load_mw_rolling_mean_2"] == 100.0
    assert features.loc[2, "load_mw_rolling_mean_2"] == 120.0
    assert features.loc[2, "load_mw_rolling_std_2"] == 0.0


def test_merge_weather_features(taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame) -> None:
    """觀測只涵蓋 8/20：該日與其後兩小時帶入天氣，其餘小時保留缺值。"""
    res = merge_weather_features(taipower_raw_df, cwa_obs_df)
    assert "relative_humidity" in res.columns
    assert len(res) == len(taipower_raw_df)
    covered = res["datetime"] <= pd.Timestamp("2026-08-21 01:00")
    assert res.loc[covered, "temperature"].notna().all()
    assert res.loc[~covered, "temperature"].isna().all()


def test_build_feature_pipeline(taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame) -> None:
    """Test complete end-to-end feature pipeline execution."""
    lags = [1, 2]
    windows = [6]
    features_df = build_feature_pipeline(
        load_df=taipower_raw_df,
        weather_df=cwa_obs_df,
        lags=lags,
        windows=windows,
        drop_na=True,
    )

    assert not features_df.empty
    assert LOAD_MW_COL in features_df.columns
    assert f"{LOAD_MW_COL}_lag_1" in features_df.columns
    assert f"{LOAD_MW_COL}_rolling_mean_6" in features_df.columns
    assert "temperature" in features_df.columns
    assert not features_df.isna().any().any()


def test_feature_pipeline_skips_training_hours_with_missing_lagged_load() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 10:00", "2026-09-20 12:00", "2026-09-20 13:00", "2026-09-20 14:00"]
            ),
            "load_mw": [100.0, 120.0, 130.0, 140.0],
        }
    )

    features = build_feature_pipeline(load, lags=[1], windows=[2])

    assert features["datetime"].tolist() == [
        pd.Timestamp("2026-09-20 13:00"),
        pd.Timestamp("2026-09-20 14:00"),
    ]
    assert features["load_mw_lag_1"].tolist() == [120.0, 130.0]
    assert features["load_mw_rolling_mean_2"].tolist() == [120.0, 125.0]


def test_feature_pipeline_preserves_internal_gaps_in_short_windows() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 10:00", "2026-09-20 12:00", "2026-09-20 13:00", "2026-09-20 14:00"]
            ),
            "load_mw": [100.0, 120.0, 130.0, 140.0],
        }
    )

    features = build_feature_pipeline(load, lags=[1, 2, 24], windows=[2], drop_na=False)

    assert features.loc[0, "load_mw_lag_1"] == 0.0
    assert features.loc[0, "load_mw_rolling_mean_2"] == 0.0
    assert pd.isna(features.loc[1, "load_mw_lag_1"])
    assert pd.isna(features.loc[2, "load_mw_lag_2"])
    assert features.loc[2, "load_mw_rolling_mean_2"] == 120.0

    training = build_feature_pipeline(load, lags=[1, 2, 24], windows=[2])

    assert training["datetime"].tolist() == [
        pd.Timestamp("2026-09-20 10:00"),
        pd.Timestamp("2026-09-20 14:00"),
    ]


def test_rolling_features_leave_elapsed_window_without_observations_missing() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-09-20 10:00", "2026-09-20 14:00"]),
            "load_mw": [100.0, 140.0],
        }
    )

    features = create_rolling_features(load, windows=[2])

    assert pd.isna(features.loc[1, "load_mw_rolling_mean_2"])
    assert pd.isna(features.loc[1, "load_mw_rolling_std_2"])


def test_multi_location_lag_and_rolling_isolation() -> None:
    """Verify lag and rolling calculations are isolated per location with zero cross-station pollution."""
    multi_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "location": "Taipei"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 300.0, "location": "Taipei"},
            {"datetime": "2026-08-20 00:00:00", "load_mw": 1000.0, "location": "Kaohsiung"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 2000.0, "location": "Kaohsiung"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 3000.0, "location": "Kaohsiung"},
        ]
    )

    lag_res = create_lag_features(multi_df, lags=[1])
    # Taipei checks
    taipei_lags = lag_res[lag_res["location"] == "Taipei"].sort_values("datetime")
    assert pd.isna(taipei_lags.iloc[0]["load_mw_lag_1"])
    assert taipei_lags.iloc[1]["load_mw_lag_1"] == 100.0
    assert taipei_lags.iloc[2]["load_mw_lag_1"] == 200.0

    # Kaohsiung checks - MUST NOT be contaminated by Taipei's 300.0 at t=0
    kh_lags = lag_res[lag_res["location"] == "Kaohsiung"].sort_values("datetime")
    assert pd.isna(kh_lags.iloc[0]["load_mw_lag_1"])
    assert kh_lags.iloc[1]["load_mw_lag_1"] == 1000.0
    assert kh_lags.iloc[2]["load_mw_lag_1"] == 2000.0

    # Rolling checks
    roll_res = create_rolling_features(multi_df, windows=[2])
    kh_roll = roll_res[roll_res["location"] == "Kaohsiung"].sort_values("datetime")
    # Kaohsiung t=1 shifted(1) window=2 should be mean([1000.0]) = 1000.0, not contaminated by Taipei
    assert kh_roll.iloc[1]["load_mw_rolling_mean_2"] == 1000.0


def test_multi_location_weather_merge_isolation() -> None:
    """Verify weather data is merged per (datetime, location) without Cartesian product or cross-station bleed."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "location": "Taipei"},
            {"datetime": "2026-08-20 00:00:00", "load_mw": 1000.0, "location": "Kaohsiung"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 2000.0, "location": "Kaohsiung"},
        ]
    )
    weather_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 32.0,
                "relative_humidity": 60.0,
                "location": "Taipei",
            },
            {
                "datetime": "2026-08-20 01:00:00",
                "temperature": 33.0,
                "relative_humidity": 58.0,
                "location": "Taipei",
            },
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 28.0,
                "relative_humidity": 80.0,
                "location": "Kaohsiung",
            },
            {
                "datetime": "2026-08-20 01:00:00",
                "temperature": 29.0,
                "relative_humidity": 78.0,
                "location": "Kaohsiung",
            },
        ]
    )

    merged = merge_weather_features(load_df, weather_df)
    # Exactly 4 rows, preserving location alignment
    assert len(merged) == 4
    taipei_00 = merged[
        (merged["location"] == "Taipei")
        & (merged["datetime"] == pd.Timestamp("2026-08-20 00:00:00"))
    ].iloc[0]
    kh_00 = merged[
        (merged["location"] == "Kaohsiung")
        & (merged["datetime"] == pd.Timestamp("2026-08-20 00:00:00"))
    ].iloc[0]

    assert taipei_00["temperature"] == 32.0
    assert kh_00["temperature"] == 28.0


def test_timezone_aware_and_naive_weather_merge_alignment() -> None:
    """Verify tz-aware (+08:00) CWA weather perfectly merges with tz-naive Taipower load."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 14:00:00", "load_mw": 38000.0, "location": "Taipei"},
            {"datetime": "2026-08-20 15:00:00", "load_mw": 37500.0, "location": "Taipei"},
        ]
    )
    weather_df_aware = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20T14:00:00+08:00",
                "temperature": 35.5,
                "relative_humidity": 55.0,
                "location": "Taipei",
            },
            {
                "datetime": "2026-08-20T15:00:00+08:00",
                "temperature": 34.8,
                "relative_humidity": 58.0,
                "location": "Taipei",
            },
        ]
    )

    merged = merge_weather_features(load_df, weather_df_aware)
    assert len(merged) == 2
    row_14 = merged[merged["datetime"] == pd.Timestamp("2026-08-20 14:00:00")].iloc[0]
    assert row_14["temperature"] == 35.5
    assert row_14["load_mw"] == 38000.0


def test_utc_z_weather_merge_alignment() -> None:
    """Verify UTC (Z) timestamp is converted to Asia/Taipei and aligns without 8-hour shift."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 14:00:00", "load_mw": 38000.0, "location": "Taipei"},
        ]
    )
    # 06:00:00Z in UTC corresponds exactly to 14:00:00 in Asia/Taipei
    weather_df_utc = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20T06:00:00Z",
                "temperature": 35.5,
                "relative_humidity": 55.0,
                "location": "Taipei",
            },
        ]
    )

    merged = merge_weather_features(load_df, weather_df_utc)
    assert len(merged) == 1
    assert merged.iloc[0]["temperature"] == 35.5
    assert merged.iloc[0]["datetime"] == pd.Timestamp("2026-08-20 14:00:00")


def test_calendar_features_hour_aligned_with_taiwan_time() -> None:
    """Verify calendar feature extraction treats UTC input as Taiwan local time."""
    df_utc = pd.DataFrame([{"datetime": "2026-08-20T06:00:00Z", "load_mw": 30000.0}])
    feat = create_calendar_features(df_utc)
    # 06:00 UTC is 14:00 in Taiwan
    assert feat.iloc[0]["hour"] == 14


def test_lag_and_rolling_features_do_not_fill_with_future_load() -> None:
    """Lag/rolling missing history must not be imputed from later load observations."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "location": "Taipei"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 300.0, "location": "Taipei"},
            {"datetime": "2026-08-20 03:00:00", "load_mw": 9999.0, "location": "Taipei"},
        ]
    )

    features = build_feature_pipeline(
        load_df=load_df,
        weather_df=None,
        lags=[1, 2],
        windows=[2],
        drop_na=False,
    )

    # Unique future marker must never appear in earlier lag/rolling cells.
    future_marker = 9999.0
    early = features.iloc[:3]
    assert (early["load_mw_lag_1"] != future_marker).all()
    assert (early["load_mw_lag_2"] != future_marker).all()
    assert (early["load_mw_rolling_mean_2"] != future_marker).all()

    # Point-in-time lag values when history exists.
    assert features.iloc[1]["load_mw_lag_1"] == 100.0
    assert features.iloc[2]["load_mw_lag_1"] == 200.0
    assert features.iloc[2]["load_mw_lag_2"] == 100.0

    # Warm-up rows keep a non-leaking sentinel instead of borrowing future load.
    assert features.iloc[0]["load_mw_lag_1"] == 0.0
    assert features.iloc[0]["load_mw_lag_2"] == 0.0
    assert features.iloc[1]["load_mw_lag_2"] == 0.0


def test_multi_location_features_have_no_cross_location_future_leakage() -> None:
    """Features for one location must not absorb another location's later load values."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 110.0, "location": "Taipei"},
            {"datetime": "2026-08-20 00:00:00", "load_mw": 5000.0, "location": "Kaohsiung"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 5100.0, "location": "Kaohsiung"},
        ]
    )

    features = build_feature_pipeline(
        load_df=load_df,
        weather_df=None,
        lags=[1],
        windows=[2],
        drop_na=False,
    )

    taipei = features[features["location"] == "Taipei"].sort_values("datetime")
    assert set(taipei["load_mw_lag_1"]).isdisjoint({5000.0, 5100.0})
    assert taipei.iloc[0]["load_mw_lag_1"] == 0.0
    assert taipei.iloc[1]["load_mw_lag_1"] == 100.0


def test_weather_gap_forward_fills_at_most_two_hours_and_drops_remaining_rows() -> None:
    load_df = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-20 00:00", periods=5, freq="h"),
            "load_mw": [100, 110, 120, 130, 140],
            "location": "Taipei",
        }
    )
    weather_df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-08-20 00:00"), pd.Timestamp("2026-08-20 04:00")],
            "temperature": [30.0, 34.0],
            "relative_humidity": [70.0, 66.0],
            "location": "Taipei",
        }
    )

    features = build_feature_pipeline(load_df, weather_df, lags=[1], windows=[2], drop_na=True)

    assert list(features["datetime"]) == [
        pd.Timestamp("2026-08-20 01:00"),
        pd.Timestamp("2026-08-20 02:00"),
        pd.Timestamp("2026-08-20 04:00"),
    ]
    assert list(features["temperature"]) == [30.0, 30.0, 34.0]


def test_weather_older_than_two_hours_is_dropped_across_missing_load_hours() -> None:
    load = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-09-20 00:00", "2026-09-20 02:00", "2026-09-20 05:00", "2026-09-20 06:00"]
            ),
            "load_mw": [100.0, 110.0, 120.0, 130.0],
        }
    )
    weather = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-09-20 00:00"]),
            "temperature": [28.0],
            "relative_humidity": [70.0],
        }
    )

    features = build_feature_pipeline(load, weather, lags=[2, 24], windows=[2])

    assert features["datetime"].tolist() == [
        pd.Timestamp("2026-09-20 00:00"),
        pd.Timestamp("2026-09-20 02:00"),
    ]
    assert features["temperature"].tolist() == [28.0, 28.0]


def test_weather_fields_match_past_observations_per_location() -> None:
    load = pd.DataFrame(
        {
            "datetime": ["2026-09-20 03:00", "2026-09-20 03:00"],
            "load_mw": [100.0, 200.0],
            "location": ["Taipei", "Taichung"],
        }
    )
    weather = pd.DataFrame(
        {
            "datetime": [
                "2026-09-20 01:00",
                "2026-09-20 03:00",
                "2026-09-20 04:00",
                "2026-09-20 01:00",
            ],
            "location": ["Taipei", "Taipei", "Taipei", "Taichung"],
            "temperature": [30.0, 32.0, 99.0, 20.0],
            "relative_humidity": [70.0, None, 99.0, 80.0],
        }
    )

    features = build_feature_pipeline(load, weather, lags=[1, 2, 24], windows=[2])

    assert features.set_index("location")[["temperature", "relative_humidity"]].to_dict(
        "index"
    ) == {
        "Taipei": {"temperature": 32.0, "relative_humidity": 70.0},
        "Taichung": {"temperature": 20.0, "relative_humidity": 80.0},
    }


def test_merge_weather_leaves_hours_without_recent_observations_missing() -> None:
    """缺少兩小時內觀測的小時保留缺值，不以常數或未來觀測補值（#66）。"""
    load_df = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-20 00:00", periods=4, freq="h"),
            "load_mw": [100.0, 110.0, 120.0, 130.0],
        }
    )
    weather_df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-08-20 03:00")],
            "temperature": [31.0],
            "relative_humidity": [66.0],
        }
    )

    merged = merge_weather_features(load_df, weather_df)

    assert merged["temperature"].iloc[:3].isna().all()
    assert merged["relative_humidity"].iloc[:3].isna().all()
    assert merged["temperature"].iloc[3] == 31.0
