"""Feature gate for the trusted-network Data Explorer surface."""

from shiro_mlops.core.config import settings


def is_data_explorer_enabled() -> bool:
    """Enable Data Explorer in local environments or when explicitly flagged."""
    if settings.DATA_EXPLORER_ENABLED:
        return True
    return settings.ENVIRONMENT == "local"
