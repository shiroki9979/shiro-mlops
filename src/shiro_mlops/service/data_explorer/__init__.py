"""Read-only Data Explorer HTTP surface for persisted operational datasets."""

from shiro_mlops.service.data_explorer.access import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.router import router

__all__ = ["is_data_explorer_enabled", "router"]
