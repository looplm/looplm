"""Pluggable retrieval-index providers.

A retrieval-index provider is a credentialed, read-only connection to a vector
or search backend (Azure AI Search, Pinecone, Qdrant, pgvector, …) that exposes
the *indexed corpus* so looplm can measure eval coverage against it.

This mirrors the trace-connector subsystem (``connectors/``) but for the corpus
side rather than the trace side. The abstraction speaks in generic
"partitions" so every backend maps onto the same interface — see ``base.py``.
"""

from app.index_providers.base import (
    BaseIndexProvider,
    CorpusDoc,
    PartitionKey,
    PartitionValue,
)
from app.index_providers.registry import build_index_provider

__all__ = [
    "BaseIndexProvider",
    "CorpusDoc",
    "PartitionKey",
    "PartitionValue",
    "build_index_provider",
]
