"""The deployed Definitions bind each ingestion source port to its settings-configured HTTP adapter."""

import pytest
from dagster import Definitions, build_resources

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.taipower_regional_supply_demand import TaipowerRegionalSupplyDemandClient
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandClient
from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationClient
from shiro_mlops.pipelines.assets import (
    CWA_SOURCE,
    TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_UNIT_GENERATION_SOURCE,
)
from shiro_mlops.pipelines.definitions import defs


def test_every_asset_resource_requirement_is_bound() -> None:
    Definitions.validate_loadable(defs)


@pytest.mark.parametrize(
    ("key", "adapter_type", "base_url"),
    [
        (
            TAIPOWER_SUPPLY_DEMAND_SOURCE,
            TaipowerSupplyDemandClient,
            settings.TAIPOWER_SUPPLY_DEMAND_API_URL,
        ),
        (
            TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
            TaipowerRegionalSupplyDemandClient,
            settings.TAIPOWER_REGIONAL_SUPPLY_DEMAND_API_URL,
        ),
        (
            TAIPOWER_UNIT_GENERATION_SOURCE,
            TaipowerUnitGenerationClient,
            settings.TAIPOWER_UNIT_GENERATION_API_URL,
        ),
    ],
)
def test_taipower_sources_fetch_from_the_configured_endpoint(
    key: str, adapter_type: type, base_url: str
) -> None:
    with build_resources({key: defs.resources[key]}) as resources:
        adapter = getattr(resources, key)

    assert isinstance(adapter, adapter_type)
    assert adapter.base_url == base_url


def test_cwa_source_authorizes_with_the_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CWA_API_KEY", "configured-key")

    with build_resources({CWA_SOURCE: defs.resources[CWA_SOURCE]}) as resources:
        adapter = getattr(resources, CWA_SOURCE)

    assert isinstance(adapter, CWAClient)
    assert adapter.api_key == "configured-key"
