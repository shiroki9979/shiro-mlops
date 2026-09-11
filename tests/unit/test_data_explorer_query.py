"""Typed ExplorerQuery carries the list seam instead of a parameter clump."""

from datetime import datetime, timedelta

import pytest

from shiro_mlops.service.data_explorer.cursor import CursorError, decode_cursor, encode_cursor
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.pagination import paginate_list
from shiro_mlops.service.data_explorer.query import ExplorerQuery


def test_explorer_query_carries_window_filters_limit_and_cursor() -> None:
    """查詢值物件必須一次帶齊時間窗、資料集篩選、limit 與 opaque cursor。"""
    params = {
        "start": "2026-08-01T00:00:00+08:00",
        "end": "2026-08-02T00:00:00+08:00",
        "location": "Taipei",
        "limit": "25",
        "cursor": "opaque-token",
    }

    query = ExplorerQuery.from_params("hourly_load", params)

    assert query.dataset == "hourly_load"
    assert query.window.start == datetime(2026, 8, 1, 0, 0)
    assert query.window.end == datetime(2026, 8, 2, 0, 0)
    assert query.filters["location"] == "Taipei"
    assert query.limit == 25
    assert query.cursor == "opaque-token"


def test_explorer_query_rejects_window_beyond_dataset_maximum() -> None:
    """超過資料集時間上限必須在組出 query 時失敗，不得把參數 clump 往後傳。"""
    with pytest.raises(ExplorerQueryError, match="31 days"):
        ExplorerQuery.from_params(
            "hourly_load",
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
        "location": "Taipei",
    }
    query = ExplorerQuery.from_params("hourly_load", params)
    token = encode_cursor(
        dataset="hourly_load",
        filters=query.filters,
        key={"time": "2026-08-01T12:00:00+08:00", "location": "Taipei"},
    )
    with_cursor = ExplorerQuery.from_params("hourly_load", {**params, "cursor": token})

    key = with_cursor.cursor_key()

    assert key is not None
    assert key["location"] == "Taipei"
    assert "time" in key

    mismatched = ExplorerQuery.from_params(
        "hourly_load",
        {**params, "location": "Taichung", "cursor": token},
    )
    with pytest.raises(CursorError, match="filter"):
        mismatched.cursor_key()


def test_paginate_list_encodes_next_cursor_from_last_visible_item() -> None:
    """共用 keyset 分頁必須用最後一筆可見列編碼 next_cursor，並回傳多一筆偵測到的 has_more。"""
    params = {
        "start": "2026-08-01T00:00:00+08:00",
        "end": "2026-08-02T00:00:00+08:00",
        "location": "Taipei",
        "limit": "1",
    }
    query = ExplorerQuery.from_params("hourly_load", params)
    rows = [
        {
            "datetime": "2026-08-02T00:00:00+08:00",
            "location": "Taipei",
            "load_mw": 31000.0,
        },
        {
            "datetime": "2026-08-01T23:00:00+08:00",
            "location": "Taipei",
            "load_mw": 30000.0,
        },
    ]

    envelope = paginate_list(query, lambda _query, _cursor, _limit: (rows, ["gap"]))

    assert envelope.has_more is True
    assert envelope.missing_slots == ["gap"]
    assert envelope.items == [rows[0]]
    assert envelope.next_cursor is not None
    assert decode_cursor(envelope.next_cursor, dataset="hourly_load", filters=query.filters) == {
        "time": "2026-08-02T00:00:00+08:00",
        "location": "Taipei",
    }


def test_explorer_query_defaults_to_trailing_day_when_window_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未給時間窗時必須使用資料集預設的最近 24 小時。"""
    frozen = datetime(2026, 8, 20, 14, 0)
    monkeypatch.setattr("shiro_mlops.service.data_explorer.query.now_taiwan", lambda: frozen)

    query = ExplorerQuery.from_params("hourly_load", {})

    assert query.window.end == frozen
    assert query.window.start == frozen - timedelta(hours=24)
    assert query.limit == 50
    assert query.cursor is None
