"""Data Explorer row-mapping helpers reject corrupt identifier payloads."""

import pytest

from shiro_mlops.service.data_explorer.values import json_list


def test_json_list_accepts_arrays_and_treats_absent_as_empty() -> None:
    """約定缺值與 JSON null 表示沒有 missing identifiers；合法陣列原樣回傳。"""
    assert json_list(None) == []
    assert json_list("") == []
    assert json_list("null") == []
    assert json_list(["467490"]) == ["467490"]


def test_json_list_rejects_non_array_payloads() -> None:
    """非陣列 payload 不得被轉成識別鍵清單而掩蓋資料損壞。"""
    with pytest.raises(ValueError, match="JSON array"):
        json_list({"station": "467490"})
    with pytest.raises(ValueError, match="JSON"):
        json_list("not-json")
