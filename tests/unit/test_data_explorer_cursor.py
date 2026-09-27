"""Opaque keyset cursor encoding stays filter-bound and versioned."""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode

import pytest

from shiro_mlops.service.data_explorer.cursor import (
    CursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trip_preserves_sort_key() -> None:
    """編碼後的 cursor 必須能還原最後一筆排序鍵。"""
    filters = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    key = {"time": "2026-08-01T12:00:00+08:00", "location": "Taipei"}

    token = encode_cursor(dataset="hourly_load", filters=filters, key=key)

    assert "=" not in token
    assert json.loads(urlsafe_b64decode(token + "=" * (-len(token) % 4)))["v"] == 2
    assert decode_cursor(token, dataset="hourly_load", filters=filters) == key


def test_cursor_rejects_filter_mismatch() -> None:
    """篩選條件改變後不得繼續使用舊 cursor。"""
    token = encode_cursor(
        dataset="hourly_load",
        filters={"location": "Taipei"},
        key={"time": "2026-08-01T12:00:00+08:00"},
    )

    with pytest.raises(CursorError, match="filter"):
        decode_cursor(token, dataset="hourly_load", filters={"location": "Taichung"})


def test_cursor_rejects_invalid_or_incompatible_payload() -> None:
    """格式無效、資料集不符或版本不相容的 cursor 必須拒絕。"""
    with pytest.raises(CursorError):
        decode_cursor("not-a-cursor", dataset="hourly_load", filters={})

    token = encode_cursor(
        dataset="hourly_load", filters={}, key={"time": "2026-08-01T00:00:00+08:00"}
    )
    with pytest.raises(CursorError, match="dataset"):
        decode_cursor(token, dataset="national_supply_demand", filters={})

    legacy = urlsafe_b64encode(b'{"v":1,"ds":"hourly_load","f":{},"k":{}}').decode()
    with pytest.raises(CursorError, match="version"):
        decode_cursor(legacy, dataset="hourly_load", filters={})
