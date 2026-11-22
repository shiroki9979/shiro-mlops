"""Raw payload serialization stores every source payload as valid JSON text."""

import json

from shiro_mlops.data.repository_utils import deserialize_raw_payload, serialize_raw_payload


def test_string_payload_is_stored_as_json_string_literal_and_round_trips() -> None:
    """XML 等字串 payload 以 JSON 字串字面值保存，JSONB 才會接受，讀回得到原字串。"""
    source_xml = "<cwaopendata><Dataset>臺北</Dataset></cwaopendata>"

    stored = serialize_raw_payload(source_xml)

    assert stored == '"<cwaopendata><Dataset>臺北</Dataset></cwaopendata>"'
    assert deserialize_raw_payload(stored) == source_xml


def test_object_payload_round_trips_without_ascii_escaping() -> None:
    """dict 與 list payload 保存為 JSON 文字且保留中文，讀回與原值相同。"""
    payload = {"DateTime": "2026-11-22 10:00", "aaData": [{"機組名稱": "核三#1"}]}

    stored = serialize_raw_payload(payload)

    assert json.loads(stored) == payload
    assert "核三" in stored
    assert deserialize_raw_payload(stored) == payload
