"""Opaque keyset cursor encoding stays filter-bound and versioned."""

import pytest

from shiro_mlops.service.data_explorer.cursor import (
    CursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trip_preserves_sort_key() -> None:
    """編碼後的 cursor 必須能還原最後一筆排序鍵。"""
    filters = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    key = {"time": "2026-08-01T12:00:00+08:00", "subject": "nationwide"}

    token = encode_cursor(dataset="hourly_load", filters=filters, key=key)

    assert "=" not in token
    assert decode_cursor(token, dataset="hourly_load", filters=filters) == key


def test_cursor_rejects_filter_mismatch() -> None:
    """篩選條件改變後不得繼續使用舊 cursor。"""
    token = encode_cursor(
        dataset="hourly_load",
        filters={"subject": "nationwide"},
        key={"time": "2026-08-01T12:00:00+08:00"},
    )

    with pytest.raises(CursorError, match="filter"):
        decode_cursor(token, dataset="hourly_load", filters={"subject": "north"})


def test_cursor_rejects_invalid_or_incompatible_payload() -> None:
    """格式無效、資料集不符或版本不相容的 cursor 必須拒絕。"""
    with pytest.raises(CursorError):
        decode_cursor("not-a-cursor", dataset="hourly_load", filters={})

    token = encode_cursor(
        dataset="hourly_load", filters={}, key={"time": "2026-08-01T00:00:00+08:00"}
    )
    with pytest.raises(CursorError, match="dataset"):
        decode_cursor(token, dataset="national_supply_demand", filters={})
