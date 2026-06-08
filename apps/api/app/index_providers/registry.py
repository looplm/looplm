"""Factory that builds a concrete index provider from a stored connection.

Mirrors ``app.services.sync_service._get_connector`` (the trace-connector
factory): decrypt the credential, then dispatch on the provider type. New
backends (Pinecone, Qdrant, pgvector) are added with another branch here plus
an enum value in ``IndexProviderType``.
"""

from __future__ import annotations

from app.encryption import decrypt_api_key
from app.index_providers.base import BaseIndexProvider
from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider


def build_index_provider(provider: IndexProvider) -> BaseIndexProvider:
    """Instantiate the provider client for a stored :class:`IndexProvider` row."""
    api_key = decrypt_api_key(provider.api_key)
    config = provider.config or {}

    if provider.type == IndexProviderType.azure_search:
        from app.index_providers.azure_search import AzureSearchIndexProvider

        index_name = config.get("index_name")
        if not index_name:
            raise ValueError("Azure Search provider requires config.index_name")
        return AzureSearchIndexProvider(
            endpoint=provider.base_url or config.get("endpoint", ""),
            api_key=api_key,
            index_name=index_name,
        )

    raise ValueError(f"Unsupported index provider type: {provider.type}")
