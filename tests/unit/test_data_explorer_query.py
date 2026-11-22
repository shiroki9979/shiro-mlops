"""Typed ExplorerQuery carries the list seam instead of a parameter clump."""

from datetime import datetime, timedelta

import pytest

from shiro_mlops.service.data_explorer.cursor import CursorError, encode_cursor
from shiro_mlops.service.data_explorer.datasets import HOURLY_LOAD
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery


def test_explorer_query_carries_window_filters_limit_and_cursor() -> None:
    """查詢值物件必須一次帶齊時間窗、資料集篩選、limit 與 opaque cursor。"""
    params = {
        "start": "2026-08-01T00:00:00+08:00",
        "end": "2026-08-02T00:00:00+08:00",
        "subject": "nationwide",
        "limit": "25",
        "cursor": "opaque-token",
    }

    query = ExplorerQuery.from_params(HOURLY_LOAD, params)

    assert query.dataset is HOURLY_LOAD
    assert query.window.start == datetime(2026, 8, 1, 0, 0)
    assert query.window.end == datetime(2026, 8, 2, 0, 0)
    assert query.filters["subject"] == "nationwide"
    assert query.limit == 25
    assert query.cursor == "opaque-token"


def test_explorer_query_rejects_window_beyond_dataset_maximum() -> None:
    """超過資料集時間上限必須在組出 query 時失敗，不得把參數 clump 往後傳。"""
    with pytest.raises(ExplorerQueryError, match="31 days"):
        ExplorerQuery.from_params(
            HOURLY_LOAD,
            {
                "start": "2026-08-01T00:00:00+08:00",
                "end": "2026-09-02T00:00:00+08:00",
            },
        )


def test_explorer_query_decodes_filter_bound_cursor_key() -> None:
    """cursor 解碼與驗證必須走 query 值物件，且綁定當前篩選。"""
    params = {
        "start": "2026-08-01T00:00:00+08:00",
        "end": "2026-08-02T00:00:00+08:00",
        "subject": "nationwide",
    }
    query = ExplorerQuery.from_params(HOURLY_LOAD, params)
    token = encode_cursor(
        dataset="hourly_load",
        filters=query.filters,
        key={"time": "2026-08-01T12:00:00+08:00", "subject": "nationwide"},
    )
    with_cursor = ExplorerQuery.from_params(HOURLY_LOAD, {**params, "cursor": token})

    key = with_cursor.cursor_key()

    assert key is not None
    assert key["subject"] == "nationwide"
    assert "time" in key

    mismatched = ExplorerQuery.from_params(
        HOURLY_LOAD,
        {**params, "subject": "north", "cursor": token},
    )
    with pytest.raises(CursorError, match="filter"):
        mismatched.cursor_key()


def test_cursor_preserves_fractional_second_window_when_defaults_are_restored() -> None:
    first = ExplorerQuery.from_params(
        HOURLY_LOAD,
        {
            "start": "2026-08-01T00:00:00.500000+08:00",
            "end": "2026-08-02T00:00:00.500000+08:00",
        },
    )
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=first.filters,
        key={"time": "2026-08-01T12:00:00+08:00", "subject": "nationwide"},
    )

    next_page = ExplorerQuery.from_params(HOURLY_LOAD, {"cursor": cursor})

    assert next_page.window == first.window
    assert next_page.cursor_key() is not None


def test_explorer_query_defaults_to_trailing_day_when_window_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未給時間窗時必須使用資料集預設的最近 24 小時。"""
    frozen = datetime(2026, 8, 20, 14, 0)
    monkeypatch.setattr("shiro_mlops.service.data_explorer.query.now_taiwan", lambda: frozen)

    query = ExplorerQuery.from_params(HOURLY_LOAD, {})

    assert query.window.end == frozen
    assert query.window.start == frozen - timedelta(hours=24)
    assert query.limit == 50
    assert query.cursor is None
