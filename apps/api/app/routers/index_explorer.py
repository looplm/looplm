"""Read-only index-explorer endpoints — the OBSERVE "Data Sources" page.

Surfaces what is *in* a connected retrieval index as a lazy, hierarchical tree:
total document count, the dimensions it can be grouped by, and one drill-down
level at a time (group distribution → sampled documents). Purely read; provider
CRUD lives on the RAG-coverage surface (``rag_coverage.py``). Both reuse the same
``BaseIndexProvider`` introspection and the ``IndexProvider`` model.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section
from app.db import get_db
from app.index_providers.registry import build_index_provider
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.user import User
from app.index_providers.chunk_quality_common import pick_field
from app.schemas.index_explorer import (
    IndexChunkMetadataResponse,
    IndexFieldDocs,
    IndexFieldDocsRequest,
    IndexFieldDocsResponse,
    IndexFieldSchemaItem,
    IndexFieldSchemaResponse,
    IndexFileChunk,
    IndexFileChunksResponse,
    IndexFileListResponse,
    IndexFileMatch,
    IndexFileTypeValue,
    IndexFileTypesResponse,
    IndexGroupingSuggestion,
    IndexGroupingSuggestionRequest,
    IndexGroupingSuggestionResponse,
    IndexPartitionKey,
    IndexProviderOptionListResponse,
    IndexSummaryResponse,
    IndexTreeDocument,
    IndexTreeGroupNode,
    IndexTreeResponse,
    IndexTreeSection,
)
from app.services.analysis_llm import AnalysisLlmConfigError, merge_llm_settings
from app.services.index_field_docs import explain_fields
from app.services.index_grouping_advisor import suggest_grouping

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/index-explorer",
    tags=["index-explorer"],
    dependencies=[require_section("observe", "data-sources")],
)

_MAX_SAMPLE = 200

# File-type dimension candidates for the "Files" tab overview, in priority order.
# Detected among the index's *facetable* fields so the distribution can be faceted.
_FILETYPE_FIELDS = [
    "content_type", "doc_type", "file_type", "mimetype", "mime_type",
    "format", "source_type", "type",
]


def _visible_fields(fields: dict) -> dict:
    """Drop embedding vectors — long numeric arrays are noise in a metadata view."""
    out = {}
    for k, v in fields.items():
        if isinstance(v, list) and len(v) > 16 and all(isinstance(x, (int, float)) for x in v[:8]):
            continue
        out[k] = v
    return out


def _provider_error(e: Exception) -> HTTPException:
    return HTTPException(
        status_code=502, detail={"error": {"code": "PROVIDER_ERROR", "message": str(e)}}
    )


async def _get_provider_or_404(
    db: AsyncSession, provider_id: UUID, project: Project
) -> IndexProvider:
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Index provider not found"}},
        )
    return provider


@router.get("/providers", response_model=IndexProviderOptionListResponse)
async def list_providers(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Read-only provider list for the explorer's picker."""
    result = await db.execute(
        select(IndexProvider)
        .where(IndexProvider.project_id == project.id)
        .order_by(IndexProvider.created_at.desc())
    )
    return IndexProviderOptionListResponse(data=result.scalars().all())


@router.get("/summary", response_model=IndexSummaryResponse)
async def summary(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Total document count + the dimensions the corpus can be grouped by."""
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        document_count = await client.test_connection()
        keys = await client.list_partition_keys()
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    return IndexSummaryResponse(
        document_count=document_count,
        partition_keys=[
            IndexPartitionKey(
                key=k.key, label=k.label, multivalued=k.multivalued, metadata=k.metadata
            )
            for k in keys
        ],
    )


@router.get("/tree", response_model=IndexTreeResponse)
async def tree(
    provider_id: UUID,
    level: list[str] = Query(..., min_length=1),
    path_key: list[str] = Query(default_factory=list),
    path_value: list[str] = Query(default_factory=list),
    limit: int = Query(50, ge=1, le=_MAX_SAMPLE),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """One lazily-expanded level of the index tree.

    Each ``level`` is a comma-separated set of field keys; a level with more
    than one field is rendered as parallel side-by-side sections. ``path_key`` /
    ``path_value`` are the index-aligned (field, value) pairs already drilled
    into (one per level descended). While levels remain, return the next level's
    distribution(s) filtered by the path; once complete, sample the leaf's docs.
    """
    levels = [[f for f in item.split(",") if f] for item in level]
    levels = [lvl for lvl in levels if lvl]
    if not levels:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "BAD_REQUEST", "message": "no grouping levels given"}},
        )
    if len(path_key) != len(path_value):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "BAD_REQUEST", "message": "path_key/path_value mismatch"}},
        )
    if len(path_key) > len(levels):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "BAD_REQUEST", "message": "path longer than levels"}},
        )

    provider = await _get_provider_or_404(db, provider_id, project)
    depth = len(path_key)
    filters = {path_key[i]: path_value[i] for i in range(depth)}
    client = build_index_provider(provider)
    try:
        if depth < len(levels):
            fields = levels[depth]
            has_children = depth + 1 < len(levels)
            keys = await client.list_partition_keys()
            labels = {k.key: k.label for k in keys}
            sections: list[IndexTreeSection] = []
            for field in fields:
                values = await client.get_partition_distribution(field, filters or None)
                sections.append(
                    IndexTreeSection(
                        key=field,
                        label=labels.get(field, field),
                        groups=[
                            IndexTreeGroupNode(
                                value=v.value, doc_count=v.doc_count, has_children=has_children
                            )
                            for v in values
                        ],
                    )
                )
            return IndexTreeResponse(level="group", sections=sections)

        # Path complete → sample documents for the leaf value.
        leaf_key = path_key[-1]
        leaf_value = path_value[-1]
        ancestors = {path_key[i]: path_value[i] for i in range(depth - 1)}
        docs = await client.sample_documents(
            leaf_key, leaf_value, limit, ancestors or None
        )
        return IndexTreeResponse(
            level="documents",
            documents=[
                IndexTreeDocument(id=d.id, title=d.title, url=d.url, snippet=d.snippet)
                for d in docs
            ],
        )
    except ValueError as e:
        # Bad field/partition key — a client error, not a backend failure.
        raise HTTPException(
            status_code=400, detail={"error": {"code": "BAD_REQUEST", "message": str(e)}}
        )
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()


@router.get("/file-types", response_model=IndexFileTypesResponse)
async def file_types(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """The file/content-type dimension of the index and its chunk-count distribution.

    Detects a facetable type field by name; returns ``field=null`` when the index
    exposes none. Example chunks per type reuse the ``/tree`` endpoint.
    """
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        keys = await client.list_partition_keys()
        field = pick_field({k.key for k in keys}, _FILETYPE_FIELDS)
        if field is None:
            return IndexFileTypesResponse(field=None, values=[])
        values = await client.get_partition_distribution(field)
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    return IndexFileTypesResponse(
        field=field,
        values=[IndexFileTypeValue(value=v.value, count=v.doc_count) for v in values],
    )


@router.get("/files", response_model=IndexFileListResponse)
async def files(
    provider_id: UUID,
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Distinct files (attachments + pages) whose filename/title matches ``q``."""
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        matches = await client.search_files(q, limit)
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    return IndexFileListResponse(
        data=[
            IndexFileMatch(
                key=m.key,
                value=m.value,
                label=m.label,
                kind=m.kind,  # type: ignore[arg-type]
                chunk_count=m.chunk_count,
                url=m.url,
            )
            for m in matches
        ]
    )


@router.get("/file-chunks", response_model=IndexFileChunksResponse)
async def file_chunks(
    provider_id: UUID,
    file_key: str = Query(..., min_length=1),
    file_value: str = Query(..., min_length=1),
    kind: str = Query("attachment"),
    label: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Every chunk of one file, in reading order (by the index's ordinal field)."""
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        docs = await client.list_file_chunks(file_key, file_value, kind, limit)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"error": {"code": "BAD_REQUEST", "message": str(e)}}
        )
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    return IndexFileChunksResponse(
        label=label or file_value,
        ordinal_available=any(d.ordinal is not None for d in docs),
        documents=[
            IndexFileChunk(
                id=d.id,
                index=i,
                ordinal=None if d.ordinal is None else str(d.ordinal),
                title=d.title,
                url=d.url,
                snippet=d.snippet,
            )
            for i, d in enumerate(docs)
        ],
    )


@router.get("/chunk-metadata", response_model=IndexChunkMetadataResponse)
async def chunk_metadata(
    provider_id: UUID,
    chunk_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """All index fields for one chunk (embedding vectors omitted)."""
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        docs = await client.fetch_documents_by_key([chunk_id])
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    fields = docs.get(chunk_id)
    return IndexChunkMetadataResponse(
        id=chunk_id,
        found=fields is not None,
        fields=_visible_fields(fields) if fields else {},
    )


_FIELD_SCHEMA_SAMPLE = 50  # docs sampled to derive example values + fill rates


@router.get("/field-schema", response_model=IndexFieldSchemaResponse)
async def field_schema(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Every index field with its attributes, example values, and fill rate.

    Live-computed (no LLM): powers the "Fields" tab overview. The human-readable
    field purposes + confusable-field groups come from ``/field-docs``.
    """
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        fields = await client.get_field_schema(sample_size=_FIELD_SCHEMA_SAMPLE)
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()
    return IndexFieldSchemaResponse(
        sample_size=_FIELD_SCHEMA_SAMPLE,
        fields=[
            IndexFieldSchemaItem(
                name=f.name,
                type=f.type,
                is_key=f.is_key,
                is_collection=f.is_collection,
                is_vector=f.is_vector,
                searchable=f.searchable,
                filterable=f.filterable,
                facetable=f.facetable,
                sortable=f.sortable,
                retrievable=f.retrievable,
                example_values=f.example_values,
                fill_rate=f.fill_rate,
            )
            for f in fields
        ],
    )


@router.get("/field-docs", response_model=IndexFieldDocsResponse)
async def get_field_docs(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """The cached LLM field documentation for this provider (no LLM call).

    Returns ``docs: null`` when none has been generated yet; the frontend then
    triggers ``POST`` to generate them.
    """
    provider = await _get_provider_or_404(db, provider_id, project)
    docs = IndexFieldDocs.model_validate(provider.field_docs) if provider.field_docs else None
    return IndexFieldDocsResponse(docs=docs, generated_at=provider.field_docs_generated_at)


@router.post("/field-docs", response_model=IndexFieldDocsResponse)
async def compute_field_docs(
    body: IndexFieldDocsRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Generate field documentation with an LLM, persist it, and return it."""
    provider = await _get_provider_or_404(db, body.provider_id, project)
    client = build_index_provider(provider)
    try:
        docs, model = await explain_fields(
            client, project_id=project.id, db=db,
            user_settings=merge_llm_settings(project.settings, user.settings),
        )
    except AnalysisLlmConfigError as e:
        raise HTTPException(
            status_code=400, detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(e)}}
        )
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()

    generated_at = datetime.now(timezone.utc)
    provider.field_docs = docs.model_dump(mode="json")
    provider.field_docs_generated_at = generated_at
    return IndexFieldDocsResponse(docs=docs, generated_at=generated_at, model=model)


@router.get("/grouping-suggestion", response_model=IndexGroupingSuggestionResponse)
async def get_grouping_suggestion(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """The cached LLM-suggested grouping for this provider (no LLM call).

    Returns ``suggestion: null`` when none has been computed yet — the frontend
    then triggers ``POST`` to compute one.
    """
    provider = await _get_provider_or_404(db, provider_id, project)
    suggestion = (
        IndexGroupingSuggestion.model_validate(provider.grouping_suggestion)
        if provider.grouping_suggestion
        else None
    )
    return IndexGroupingSuggestionResponse(
        suggestion=suggestion, suggested_at=provider.grouping_suggested_at
    )


@router.post("/grouping-suggestion", response_model=IndexGroupingSuggestionResponse)
async def compute_grouping_suggestion(
    body: IndexGroupingSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Profile the index with an LLM, persist the suggestion, and return it."""
    provider = await _get_provider_or_404(db, body.provider_id, project)
    client = build_index_provider(provider)
    try:
        suggestion, model = await suggest_grouping(
            client, project_id=project.id, db=db,
            user_settings=merge_llm_settings(project.settings, user.settings),
        )
    except AnalysisLlmConfigError as e:
        raise HTTPException(
            status_code=400, detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(e)}}
        )
    except Exception as e:
        raise _provider_error(e)
    finally:
        await client.aclose()

    suggested_at = datetime.now(timezone.utc)
    provider.grouping_suggestion = suggestion.model_dump(mode="json")
    provider.grouping_suggested_at = suggested_at
    return IndexGroupingSuggestionResponse(
        suggestion=suggestion, suggested_at=suggested_at, model=model
    )
