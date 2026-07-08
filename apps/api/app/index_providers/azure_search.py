"""Azure AI Search implementation of :class:`BaseIndexProvider`.

Reads the index schema to discover facetable fields (the partition keys),
uses server-side facets for cheap per-value document counts, and runs filtered
searches to sample documents for a given partition value.

The corpus is populated by an external RAG indexing pipeline. It is accessed
read-only with an admin or query key.
"""

from __future__ import annotations

import json
import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient

from app.index_providers.base import (
    BaseIndexProvider,
    CorpusDoc,
    FieldSchema,
    FileMatch,
    PartitionKey,
    PartitionValue,
)

logger = logging.getLogger(__name__)

# Fields we prefer to surface when sampling documents, in priority order. Only
# those that actually exist in the target index are selected. Tuned for a
# typical Confluence-style document schema but harmless for any index.
_PREFERRED_SAMPLE_FIELDS = [
    "page_id",
    "page_title",
    "page_url",
    "attachment_filename",
    "attachment_url",
    "chunk_text",
]
_MAX_FACET_VALUES = 1000  # Azure caps facet buckets; 1000 is the practical max.
_MAX_EXAMPLE_VALUES = 3  # distinct sampled example values shown per field
_EXAMPLE_MAX_LEN = 160  # truncate long example values (e.g. chunk_text bodies)


def _odata_escape(value: str) -> str:
    """Escape a string literal for an OData filter (single quotes are doubled)."""
    return value.replace("'", "''")


def _is_empty(v: object) -> bool:
    """True for values that mean 'the field carries nothing' in a sampled doc."""
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _stringify_example(v: object) -> str:
    """A short, human-readable rendering of one example value."""
    if isinstance(v, str):
        s = v.strip()
    elif isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
    else:
        s = str(v)
    if len(s) > _EXAMPLE_MAX_LEN:
        s = s[:_EXAMPLE_MAX_LEN] + "…"
    return s


class _FieldInfo:
    __slots__ = (
        "name",
        "type",
        "facetable",
        "is_collection",
        "is_key",
        "searchable",
        "filterable",
        "sortable",
        "retrievable",
    )

    def __init__(
        self,
        name: str,
        type_: str,
        facetable: bool,
        is_key: bool,
        *,
        searchable: bool = False,
        filterable: bool = False,
        sortable: bool = False,
        retrievable: bool = True,
    ):
        self.name = name
        self.type = type_
        self.facetable = bool(facetable)
        self.is_collection = type_.startswith("Collection(")
        self.is_key = bool(is_key)
        self.searchable = bool(searchable)
        self.filterable = bool(filterable)
        self.sortable = bool(sortable)
        self.retrievable = bool(retrievable)

    @property
    def is_vector(self) -> bool:
        # Azure represents embedding fields as Collection(Edm.Single).
        return self.type == "Collection(Edm.Single)"


class AzureSearchIndexProvider(BaseIndexProvider):
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        index_name: str,
        semantic_config: str | None = None,
    ) -> None:
        if not endpoint or not api_key or not index_name:
            raise ValueError("Azure Search provider requires endpoint, api_key and index_name")
        self._endpoint = endpoint
        self._index_name = index_name
        # Name of the index's semantic configuration, enabling the ``semantic`` (rerank) head.
        self._semantic_config = semantic_config or None
        self._credential = AzureKeyCredential(api_key)
        self._search_client = SearchClient(
            endpoint=endpoint, index_name=index_name, credential=self._credential
        )
        self._index_client = SearchIndexClient(endpoint=endpoint, credential=self._credential)
        self._fields: dict[str, _FieldInfo] | None = None

    async def _get_fields(self) -> dict[str, _FieldInfo]:
        if self._fields is None:
            index = await self._index_client.get_index(self._index_name)
            self._fields = {f.name: self._field_info(f) for f in index.fields}
        return self._fields

    @staticmethod
    def _field_info(f) -> _FieldInfo:
        # Azure marks a field non-retrievable via ``hidden`` (newer SDK) or a
        # ``retrievable=False`` (older); default to retrievable when neither is set.
        hidden = getattr(f, "hidden", None)
        retrievable = getattr(f, "retrievable", None)
        if hidden is not None:
            is_retrievable = not hidden
        elif retrievable is not None:
            is_retrievable = bool(retrievable)
        else:
            is_retrievable = True
        return _FieldInfo(
            f.name,
            f.type,
            getattr(f, "facetable", False),
            getattr(f, "key", False),
            searchable=getattr(f, "searchable", False),
            filterable=getattr(f, "filterable", False),
            sortable=getattr(f, "sortable", False),
            retrievable=is_retrievable,
        )

    async def _field(self, key: str) -> _FieldInfo:
        fields = await self._get_fields()
        info = fields.get(key)
        if info is None:
            raise ValueError(f"Field '{key}' does not exist in index '{self._index_name}'")
        return info

    async def test_connection(self) -> int:
        return await self._search_client.get_document_count()

    async def list_partition_keys(self) -> list[PartitionKey]:
        fields = await self._get_fields()
        keys = [
            PartitionKey(
                key=f.name,
                label=f.name,
                multivalued=f.is_collection,
                metadata={"type": f.type},
            )
            for f in fields.values()
            if f.facetable
        ]
        keys.sort(key=lambda k: k.key)
        return keys

    async def _build_filter(self, constraints: dict[str, str] | None) -> str | None:
        """AND-join ``{field: value}`` constraints into a single OData filter.

        Collection fields use the ``field/any(t: t eq 'v')`` form; scalars use
        ``field eq 'v'``. Returns ``None`` when there are no constraints.
        """
        if not constraints:
            return None
        clauses: list[str] = []
        for field_name, value in constraints.items():
            info = await self._field(field_name)
            esc = _odata_escape(value)
            if info.is_collection:
                clauses.append(f"{field_name}/any(t: t eq '{esc}')")
            else:
                clauses.append(f"{field_name} eq '{esc}'")
        return " and ".join(clauses)

    async def get_partition_distribution(
        self, key: str, filters: dict[str, str] | None = None
    ) -> list[PartitionValue]:
        info = await self._field(key)
        if not info.facetable:
            raise ValueError(f"Field '{key}' is not facetable and cannot be used as a partition key")

        filter_expr = await self._build_filter(filters)
        results = await self._search_client.search(
            search_text="*",
            filter=filter_expr,
            facets=[f"{key},count:{_MAX_FACET_VALUES}"],
            top=0,
            include_total_count=False,
        )
        facets = await results.get_facets() or {}
        buckets = facets.get(key, []) or []
        out = [
            PartitionValue(value=str(b["value"]), doc_count=int(b.get("count") or 0))
            for b in buckets
            if b.get("value") is not None
        ]
        out.sort(key=lambda v: v.doc_count, reverse=True)
        return out

    async def sample_documents(
        self, key: str, value: str, n: int, filters: dict[str, str] | None = None
    ) -> list[CorpusDoc]:
        info = await self._field(key)
        fields = await self._get_fields()
        esc = _odata_escape(value)
        if info.is_collection:
            filter_expr = f"{key}/any(t: t eq '{esc}')"
        else:
            filter_expr = f"{key} eq '{esc}'"

        ancestor_expr = await self._build_filter(filters)
        if ancestor_expr:
            filter_expr = f"({filter_expr}) and ({ancestor_expr})"

        select = [f for f in _PREFERRED_SAMPLE_FIELDS if f in fields]
        key_field = next((f.name for f in fields.values() if f.is_key), None)
        if key_field and key_field not in select:
            select.append(key_field)

        results = await self._search_client.search(
            search_text="*",
            filter=filter_expr,
            select=select or None,
            top=max(1, n),
        )
        docs: list[CorpusDoc] = []
        async for doc in results:
            snippet = doc.get("chunk_text")
            if isinstance(snippet, str) and len(snippet) > 600:
                snippet = snippet[:600] + "…"
            docs.append(
                CorpusDoc(
                    id=str(doc.get(key_field) or doc.get("page_id") or doc.get("id") or ""),
                    title=doc.get("attachment_filename") or doc.get("page_title"),
                    url=doc.get("page_url") or doc.get("attachment_url"),
                    snippet=snippet,
                )
            )
        return docs

    _LOOKUP_BATCH = 200  # keep the search.in literal well under filter size limits

    async def lookup_ids(self, key: str, values: list[str]) -> dict[str, int]:
        info = await self._field(key)
        if not info.facetable:
            raise ValueError(f"Field '{key}' is not facetable; cannot bulk-count by it")
        found: dict[str, int] = {}
        # search.in is the cheap membership test; a facet on the same field
        # gives the per-value counts in one round trip per batch.
        for i in range(0, len(values), self._LOOKUP_BATCH):
            batch = [v for v in values[i : i + self._LOOKUP_BATCH] if v]
            if not batch:
                continue
            literal = _odata_escape("|".join(batch))
            results = await self._search_client.search(
                search_text="*",
                filter=f"search.in({key}, '{literal}', '|')",
                facets=[f"{key},count:{_MAX_FACET_VALUES}"],
                top=0,
            )
            facets = await results.get_facets() or {}
            for b in facets.get(key, []) or []:
                if b.get("value") is not None:
                    found[str(b["value"])] = int(b.get("count") or 0)
        return found

    async def _vector_field(self) -> str | None:
        """The embedding field used for dense/hybrid search, or None if the index has none.

        Azure represents vector fields as ``Collection(Edm.Single)``; the first such field is
        used. Cached via ``_get_fields``. Vector and hybrid search additionally require the
        index to declare a *vectorizer* (so Azure can embed the query text server-side) — that
        isn't visible in the field type, so the actual call may still fail; the caller treats
        a failure as "this head is unavailable".
        """
        fields = await self._get_fields()
        for f in fields.values():
            if f.type == "Collection(Edm.Single)":
                return f.name
        return None

    async def search_documents(
        self,
        query: str,
        n: int,
        filters: dict[str, str] | None = None,
        *,
        mode: str = "keyword",
        query_vector: list[float] | None = None,
    ) -> list[CorpusDoc]:
        fields = await self._get_fields()
        select = [f for f in _PREFERRED_SAMPLE_FIELDS if f in fields]
        key_field = next((f.name for f in fields.values() if f.is_key), None)
        if key_field and key_field not in select:
            select.append(key_field)

        top = max(1, n)
        kwargs: dict = {
            "filter": await self._build_filter(filters),
            "select": select or None,
            "top": top,
        }
        if mode not in ("keyword", "vector", "hybrid", "semantic"):
            raise ValueError(f"unknown search mode: {mode!r}")

        # Dense sub-query: required for vector/hybrid; optional for semantic (rerank over hybrid
        # when a vector is available, else rerank the keyword results).
        needs_vector = mode in ("vector", "hybrid")
        if needs_vector or (mode == "semantic" and query_vector is not None):
            vector_field = await self._vector_field()
            if not vector_field:
                if needs_vector:
                    raise NotImplementedError(
                        f"index '{self._index_name}' has no vector field for {mode} search"
                    )
            elif query_vector is not None:
                # We embedded the query ourselves — send the raw vector. Works whether or not the
                # index declares a server-side vectorizer on this field's profile.
                from azure.search.documents.models import VectorizedQuery

                kwargs["vector_queries"] = [
                    VectorizedQuery(vector=query_vector, k_nearest_neighbors=top, fields=vector_field)
                ]
            else:
                # No precomputed vector: ask Azure to embed the text, which requires the index to
                # have a vectorizer on this field's profile (else Azure rejects the query).
                from azure.search.documents.models import VectorizableTextQuery

                kwargs["vector_queries"] = [
                    VectorizableTextQuery(text=query, k_nearest_neighbors=top, fields=vector_field)
                ]

        # Keyword text: present for everything except vector-only (which ranks purely on ANN
        # score). hybrid/semantic fuse keyword + vector (RRF on Azure).
        kwargs["search_text"] = None if mode == "vector" else query

        if mode == "semantic":
            # L2 semantic reranking on top of the (hybrid) result — the system's true final
            # ranking. Needs the index's semantic configuration name.
            if not self._semantic_config:
                raise NotImplementedError(
                    f"index '{self._index_name}' has no semantic configuration for rerank"
                )
            kwargs["query_type"] = "semantic"
            kwargs["semantic_configuration_name"] = self._semantic_config

        results = await self._search_client.search(**kwargs)
        docs: list[CorpusDoc] = []
        async for doc in results:
            snippet = doc.get("chunk_text")
            if isinstance(snippet, str) and len(snippet) > 600:
                snippet = snippet[:600] + "…"
            # On the semantic head the reranker score is the meaningful one; fall back otherwise.
            score = doc.get("@search.reranker_score")
            if score is None:
                score = doc.get("@search.score")
            docs.append(
                CorpusDoc(
                    # Key field first: this is the chunk/doc key that dedups against the
                    # trace-captured ``chunk_id`` when building the labeling pool. (Source-gap
                    # title matching reads only title/url, so the id choice is free here.)
                    id=str((key_field and doc.get(key_field)) or doc.get("page_id") or doc.get("id") or ""),
                    # Prefer the descriptive page title for text matching —
                    # attachment filenames are often opaque (e.g. "12080.pdf").
                    title=doc.get("page_title") or doc.get("attachment_filename"),
                    url=doc.get("page_url") or doc.get("attachment_url"),
                    snippet=snippet,
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
        return docs

    async def fetch_documents_by_key(self, ids: list[str]) -> dict[str, dict]:
        """All retrievable fields for each chunk, keyed by id.

        Primary path is Azure's direct document-key lookup (``get_document``), which is
        correct when the chunk id is the index key (the usual case). Any id not found that
        way falls back to a ``search.in`` filter on the discovered key field. Every field is
        returned (no ``select``); internal ``@search.*`` / ``@odata.*`` keys are stripped.
        """
        from azure.core.exceptions import AzureError

        clean_ids = [i for i in ids if i]
        if not clean_ids:
            return {}

        def _strip(doc: dict) -> dict:
            return {k: v for k, v in doc.items() if not k.startswith("@")}

        out: dict[str, dict] = {}
        remaining: list[str] = []
        for cid in clean_ids:
            try:
                doc = await self._search_client.get_document(key=cid)
                out[str(cid)] = _strip(dict(doc))
            except AzureError:
                # Not found by key (or transient) — try the filter fallback below.
                remaining.append(cid)

        if not remaining:
            return out

        fields = await self._get_fields()
        key_field = next((f.name for f in fields.values() if f.is_key), None)
        if not key_field:
            return out
        for i in range(0, len(remaining), self._LOOKUP_BATCH):
            batch = remaining[i : i + self._LOOKUP_BATCH]
            literal = _odata_escape("|".join(batch))
            try:
                results = await self._search_client.search(
                    search_text="*",
                    filter=f"search.in({key_field}, '{literal}', '|')",
                    top=len(batch),
                )
                async for doc in results:
                    key_val = doc.get(key_field)
                    if key_val is not None:
                        out[str(key_val)] = _strip(dict(doc))
            except AzureError:
                continue
        return out

    # Stratifying across more buckets than this would cost one search call each,
    # so beyond it we fall back to a flat paged sample.
    _MAX_STRATA = 40
    _SCAN_PAGE = 1000  # Azure's per-request `top` ceiling.

    @staticmethod
    def _strip_internal(doc: dict) -> dict:
        return {k: v for k, v in doc.items() if not k.startswith("@")}

    async def _default_stratify_field(self) -> str | None:
        """A facetable scalar string field to spread the sample across.

        Prefers common corpus-partitioning names, else the first facetable scalar
        string field. ``None`` when the index exposes no suitable field.
        """
        fields = await self._get_fields()
        facetable = [
            f for f in fields.values()
            if f.facetable and not f.is_collection and f.type == "Edm.String"
        ]
        if not facetable:
            return None
        preferred = ("source_type", "content_type", "doc_type", "type", "sparte")
        by_name = {f.name: f for f in facetable}
        for name in preferred:
            if name in by_name:
                return name
        facetable.sort(key=lambda f: f.name)
        return facetable[0].name

    async def _fetch_full(self, *, filter_expr: str | None, top: int) -> list[dict]:
        """Up to ``top`` documents with every field, internal keys stripped."""
        results = await self._search_client.search(
            search_text="*", filter=filter_expr, top=max(1, top)
        )
        out: list[dict] = []
        async for doc in results:
            out.append(self._strip_internal(dict(doc)))
        return out

    async def get_field_schema(self, *, sample_size: int = 50) -> list[FieldSchema]:
        fields = await self._get_fields()
        # Sample real documents to derive example values + fill rates. Vector
        # fields are counted for fill rate but never surfaced as example values.
        try:
            sample = await self.sample_corpus(sample_size)
        except Exception as e:  # sampling is best-effort; schema still returns
            logger.warning("Field-schema sampling failed for %s: %s", self._index_name, e)
            sample = []
        n = len(sample)

        out: list[FieldSchema] = []
        for info in fields.values():
            filled = 0
            examples: list[str] = []
            seen: set[str] = set()
            for doc in sample:
                val = doc.get(info.name)
                if _is_empty(val):
                    continue
                filled += 1
                if info.is_vector or len(examples) >= _MAX_EXAMPLE_VALUES:
                    continue
                for item in val if isinstance(val, list) else [val]:
                    if _is_empty(item):
                        continue
                    s = _stringify_example(item)
                    if s and s not in seen:
                        seen.add(s)
                        examples.append(s)
                        if len(examples) >= _MAX_EXAMPLE_VALUES:
                            break
            out.append(
                FieldSchema(
                    name=info.name,
                    type=info.type,
                    is_key=info.is_key,
                    is_collection=info.is_collection,
                    is_vector=info.is_vector,
                    searchable=info.searchable,
                    filterable=info.filterable,
                    facetable=info.facetable,
                    sortable=info.sortable,
                    retrievable=info.retrievable,
                    example_values=examples,
                    fill_rate=round(filled / n, 3) if n else 0.0,
                )
            )
        return out

    async def sample_corpus(self, n: int, *, stratify_by: str | None = None) -> list[dict]:
        if n <= 0:
            return []

        field_name = stratify_by or await self._default_stratify_field()
        if field_name is not None:
            info = (await self._get_fields()).get(field_name)
            if info is None or not info.facetable:
                field_name = None

        # Stratified path: allocate the budget across the field's buckets so the
        # sample mirrors the corpus' composition rather than its insertion order.
        if field_name is not None:
            buckets = await self.get_partition_distribution(field_name)
            total = sum(b.doc_count for b in buckets)
            if buckets and total > 0 and len(buckets) <= self._MAX_STRATA:
                out: list[dict] = []
                for b in buckets:
                    alloc = max(1, round(n * b.doc_count / total))
                    alloc = min(alloc, b.doc_count)
                    esc = _odata_escape(b.value)
                    clause = (
                        f"{field_name}/any(t: t eq '{esc}')"
                        if info and info.is_collection
                        else f"{field_name} eq '{esc}'"
                    )
                    out.extend(await self._fetch_full(filter_expr=clause, top=alloc))
                    if len(out) >= n:
                        break
                return out[:n]

        # Flat fallback (no facetable field to stratify on): page the corpus in
        # index order until we have n. Less representative than the stratified
        # path, but the only option when the index exposes no facets.
        return await self._paged_scan(n)

    async def _paged_scan(self, n: int) -> list[dict]:
        """Collect ~n full docs by paging `top`+`$skip` (Azure caps $skip at 100k)."""
        out: list[dict] = []
        skip = 0
        while len(out) < n and skip < 100_000:
            results = await self._search_client.search(
                search_text="*", top=self._SCAN_PAGE, skip=skip
            )
            page = [self._strip_internal(dict(doc)) async for doc in results]
            if not page:
                break
            out.extend(page)
            skip += self._SCAN_PAGE
        return out[:n]

    # ── Filename search → chunks-of-a-file (Data Sources "Files" tab) ────────────
    # The implementation lives in ``azure_search_files`` to keep this file focused;
    # these thin methods delegate, passing the client and field metadata it needs.

    async def _file_field_map(self) -> dict[str, str | None]:
        from app.index_providers.azure_search_files import build_file_field_map

        return build_file_field_map(await self._get_fields())

    async def search_files(self, query: str, limit: int) -> list[FileMatch]:
        from app.index_providers.azure_search_files import search_files

        return await search_files(self, query, limit)

    async def list_file_chunks(
        self, key: str, value: str, kind: str, limit: int, *, include_text: bool = True
    ) -> list[CorpusDoc]:
        from app.index_providers.azure_search_files import list_file_chunks

        return await list_file_chunks(self, key, value, kind, limit, include_text=include_text)

    async def aclose(self) -> None:
        await self._search_client.close()
        await self._index_client.close()
