"""Taiwan-local timestamp standardisation, including the inputs that skip per-row parsing."""

import numpy as np
import pandas as pd
import pytest

from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime


def test_naive_timestamps_already_are_taiwan_local() -> None:
    series = pd.Series(pd.date_range("2026-08-20 00:00", periods=3, freq="h"), index=[7, 3, 9])

    result = standardize_taiwan_datetime(series)

    assert result.tolist() == series.tolist()
    assert result.index.tolist() == [7, 3, 9]
    assert result.dtype == "datetime64[ns]"


def test_naive_timestamps_are_returned_as_a_copy_the_caller_may_change() -> None:
    series = pd.Series(pd.date_range("2026-08-20 00:00", periods=2, freq="h"))

    result = standardize_taiwan_datetime(series)
    result.iloc[0] = pd.Timestamp("2000-01-01")

    assert series.iloc[0] == pd.Timestamp("2026-08-20 00:00")


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_naive_timestamps_of_any_resolution_come_back_in_nanoseconds(unit: str) -> None:
    series = pd.Series(np.array(["2026-08-20T12:00:00"], dtype=f"datetime64[{unit}]"))

    result = standardize_taiwan_datetime(series)

    assert result.dtype == "datetime64[ns]"
    assert result.iloc[0] == pd.Timestamp("2026-08-20 12:00")


def test_missing_naive_timestamps_stay_missing() -> None:
    series = pd.Series([pd.Timestamp("2026-08-20 12:00"), pd.NaT])

    result = standardize_taiwan_datetime(series)

    assert result.isna().tolist() == [False, True]


def test_timezone_aware_timestamps_convert_to_taiwan_local() -> None:
    series = pd.Series(pd.to_datetime(["2026-08-20T04:00:00Z"]))

    assert standardize_taiwan_datetime(series).iloc[0] == pd.Timestamp("2026-08-20 12:00")


def test_mixed_strings_and_offsets_convert_row_by_row() -> None:
    series = pd.Series(
        ["2026-08-20T04:00:00Z", "2026-08-20 12:00:00", "2026-08-20T13:00:00+09:00", None]
    )

    result = standardize_taiwan_datetime(series)

    assert result.iloc[:3].tolist() == [pd.Timestamp("2026-08-20 12:00")] * 3
    assert pd.isna(result.iloc[3])


def test_empty_series_stays_empty() -> None:
    assert standardize_taiwan_datetime(pd.Series([], dtype=object)).empty


def test_a_year_of_naive_hours_is_not_parsed_row_by_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every feature step calls this; mapping a Python function over each row dominated them."""
    series = pd.Series(pd.date_range("2025-08-20", periods=8760, freq="h"))
    monkeypatch.setattr(
        pd.Series, "map", lambda *_, **__: pytest.fail("mapped a naive datetime column")
    )

    assert standardize_taiwan_datetime(series).equals(series)
