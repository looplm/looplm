"""Base interface for retrieval-index providers.

Different backends partition their data differently — Azure AI Search has
facetable fields, Pinecone has namespaces + metadata keys, Qdrant has payload
keys, pgvector has columns. To stay backend-agnostic the interface speaks in
three generic shapes:

* ``PartitionKey``  — a dimension you can group the corpus by.
* ``PartitionValue`` — one bucket within a key, with its document count.
* ``CorpusDoc``     — a sampled document for a partition value (used both for
  drill-down and to ground the LLM when it drafts eval questions).

The user of looplm picks *which* partition key coverage is measured by; the
provider advertises the available keys via :meth:`list_partition_keys`.

Every concrete provider mirrors ``connectors.base.BaseConnector``: it is
constructed with decrypted credentials and exposes only async, read-only
operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PartitionKey:
    """A dimension the corpus can be grouped/faceted by.

    ``key`` is the backend-native identifier (e.g. an Azure field name, a
    Pinecone metadata key). ``label`` is a human-friendly name. ``multivalued``
    is True when a single document can carry several values for this key (e.g.
    an Azure ``Collection(String)`` field like ``tags``) — it changes how
    filters are built downstream.
    """

    key: str
    label: str
    multivalued: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class PartitionValue:
    """One bucket within a partition key, with its indexed document count."""

    value: str
    doc_count: int


@dataclass
class CorpusDoc:
    """A sampled document/chunk from the index, for drill-down + LLM grounding."""

    id: str
    title: str | None = None
    url: str | None = None
    snippet: str | None = None


class BaseIndexProvider(ABC):
    """Read-only access to an indexed corpus for coverage analysis."""

    @abstractmethod
    async def test_connection(self) -> int:
        """Verify credentials/reachability. Returns the total document count.

        Raises on failure so the caller can surface the underlying error.
        """
        ...

    @abstractmethod
    async def list_partition_keys(self) -> list[PartitionKey]:
        """Discover the dimensions this index can be partitioned by."""
        ...

    @abstractmethod
    async def get_partition_distribution(
        self, key: str, filters: dict[str, str] | None = None
    ) -> list[PartitionValue]:
        """Return every value of ``key`` present in the corpus, with counts.

        ``filters`` is an optional ``{field: value}`` map of ancestor constraints
        AND-ed into the query — e.g. the distribution of ``space`` *within*
        ``source_type == "confluence"``. ``None`` means the whole corpus.
        """
        ...

    @abstractmethod
    async def sample_documents(
        self, key: str, value: str, n: int, filters: dict[str, str] | None = None
    ) -> list[CorpusDoc]:
        """Return up to ``n`` representative documents where ``key == value``.

        ``filters`` is an optional ``{field: value}`` map of additional ancestor
        constraints AND-ed with the ``key == value`` clause (used to scope a
        sample to a full drill-down path). ``None`` means no extra constraints.
        """
        ...

    async def aclose(self) -> None:
        """Release any underlying clients. Override if needed; safe no-op default."""
        return None
