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
    # Backend relevance score for the matching query, when the doc came from a search
    # (``@search.score`` for Azure — the RRF fusion score in hybrid mode). ``None`` for
    # facet/sample paths, which don't rank.
    score: float | None = None


# Retrieval strategies a provider can pool candidates from. ``keyword`` is BM25/full-text,
# ``vector`` is dense ANN over the embedding field, ``hybrid`` fuses both (RRF on Azure).
SEARCH_MODES = ("keyword", "vector", "hybrid")


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

    async def lookup_ids(self, key: str, values: list[str]) -> dict[str, int]:
        """Count indexed documents per ``key`` value, for an explicit value list.

        Used by wanted-status gap analysis to check expected document IDs in
        bulk (e.g. Azure ``page_id`` hashes). Returns ``{value: doc_count}``
        containing only values that exist in the index. Optional capability —
        backends without an efficient implementation keep the default.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support lookup_ids")

    async def search_documents(
        self,
        query: str,
        n: int,
        filters: dict[str, str] | None = None,
        *,
        mode: str = "keyword",
        query_vector: list[float] | None = None,
    ) -> list[CorpusDoc]:
        """Search returning up to ``n`` best-matching documents, scored, in rank order.

        ``mode`` selects the retrieval strategy (see :data:`SEARCH_MODES`): ``keyword``
        (BM25/full-text), ``vector`` (dense ANN), or ``hybrid`` (both, fused). ``query_vector``
        is an optional precomputed embedding of ``query``; when given, vector/hybrid modes search
        with the raw vector (so an index without a server-side vectorizer still works). Used both
        as a fallback matching strategy when an expected source has no checkable ID, and to build
        the multi-head candidate pool for chunk labeling. Optional capability — backends
        without text search keep the default; a backend that has keyword but not vector
        should raise ``NotImplementedError`` for the modes it can't serve so the pool builder
        can record which heads ran.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support search_documents")

    async def fetch_documents_by_key(self, ids: list[str]) -> dict[str, dict]:
        """Full index documents (all fields) for the given key values, keyed by id.

        Used to show a retrieved chunk's complete index metadata during labeling.
        Optional capability — backends without it keep the empty default.
        """
        return {}

    async def sample_corpus(self, n: int, *, stratify_by: str | None = None) -> list[dict]:
        """Up to ``n`` full-field chunk documents, sampled across the whole corpus.

        Powers chunk/metadata quality analysis: the bodies and metadata of a
        representative sample are read once and analysed offline. Each item is a
        plain ``{field: value}`` dict with all retrievable fields (internal
        ``@``-prefixed keys stripped).

        ``stratify_by`` is an optional facetable field to draw the sample evenly
        across (so the sample isn't biased toward index/insertion order); when
        ``None`` the provider picks a sensible default or falls back to a flat
        even-spaced sample. Optional capability — backends without an efficient
        scan keep the default.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support sample_corpus")

    async def aclose(self) -> None:
        """Release any underlying clients. Override if needed; safe no-op default."""
        return None
