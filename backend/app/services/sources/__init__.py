"""Configurable multi-source collection for the bid intelligence platform."""

from app.services.sources.base import (
    CollectResult,
    ConnectionTestResult,
    SourceConfigError,
    sanitize_config,
)
from app.services.sources.adapters import (
    HtmlListingAdapter,
    JsonApiAdapter,
    PlaywrightListingAdapter,
    RssFeedAdapter,
    adapter_catalog,
    all_adapters,
    get_adapter,
    get_adapter_for_source_type,
)

__all__ = [
    "CollectResult",
    "ConnectionTestResult",
    "SourceConfigError",
    "sanitize_config",
    "RssFeedAdapter",
    "JsonApiAdapter",
    "HtmlListingAdapter",
    "PlaywrightListingAdapter",
    "adapter_catalog",
    "all_adapters",
    "get_adapter",
    "get_adapter_for_source_type",
]