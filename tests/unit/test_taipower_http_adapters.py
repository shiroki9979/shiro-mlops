"""Taipower HTTP adapters: what each returns from, and raises on, the open-data endpoint."""

import json

import httpx
import pytest

from shiro_mlops.data.taipower_regional_supply_demand import TaipowerRegionalSupplyDemandClient
from shiro_mlops.data.taipower_supply_demand import (
    SupplyDemandParseError,
    TaipowerSupplyDemandClient,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationClient,
    UnitGenerationParseError,
)

ENDPOINT = "https://service.taipower.com.tw/data/opendata/apply/file/test/001"


def _serving(content: bytes, status_code: int = 200) -> tuple[httpx.MockTransport, list[str]]:
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(status_code, content=content, request=request)

    return httpx.MockTransport(respond), requested


def test_supply_demand_adapter_returns_the_decoded_json_object() -> None:
    transport, requested = _serving(b'{"records": [{"curr_load": "3242.1"}]}')

    payload = TaipowerSupplyDemandClient(ENDPOINT, transport=transport).fetch_payload()

    assert payload == {"records": [{"curr_load": "3242.1"}]}
    assert requested == [ENDPOINT]


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b'["not", "an", "object"]'])
def test_supply_demand_adapter_rejects_a_body_that_is_not_a_json_object(body: bytes) -> None:
    transport, _ = _serving(body)

    with pytest.raises(SupplyDemandParseError):
        TaipowerSupplyDemandClient(ENDPOINT, transport=transport).fetch_payload()


def test_regional_adapter_returns_the_csv_body() -> None:
    csv_text = "時間,區域,發電(萬瓩),用電(萬瓩)\n20260905T173000,北部,1155.4,1091.7\n"
    transport, requested = _serving(csv_text.encode("utf-8"))

    body = TaipowerRegionalSupplyDemandClient(ENDPOINT, transport=transport).fetch_payload()

    assert body == csv_text
    assert requested == [ENDPOINT]


def test_unit_adapter_decodes_json_published_with_a_byte_order_mark() -> None:
    payload = {"DateTime": "2026-09-05T17:30:00", "aaData": [{"機組名稱": "大潭CC#1"}]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8-sig")
    transport, requested = _serving(body)

    assert TaipowerUnitGenerationClient(ENDPOINT, transport=transport).fetch_payload() == payload
    assert requested == [ENDPOINT]


def test_unit_adapter_rejects_a_body_that_is_not_json() -> None:
    transport, _ = _serving(b"<html>maintenance</html>")

    with pytest.raises(UnitGenerationParseError):
        TaipowerUnitGenerationClient(ENDPOINT, transport=transport).fetch_payload()


@pytest.mark.parametrize(
    "adapter_type",
    [TaipowerSupplyDemandClient, TaipowerRegionalSupplyDemandClient, TaipowerUnitGenerationClient],
)
def test_adapters_raise_on_an_upstream_error_status(adapter_type: type) -> None:
    transport, _ = _serving(b"", status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        adapter_type(ENDPOINT, transport=transport).fetch_payload()
