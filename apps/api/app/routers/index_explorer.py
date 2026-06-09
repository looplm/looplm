"""Read-only index-explorer endpoints — the OBSERVE "Data Sources" page.

Surfaces what is *in* a connected retrieval index as a lazy, hierarchical tree:
total document count, the dimensions it can be grouped by, and one drill-down
level at a time (group distribution → sampled documents). Purely read; provider
CRUD lives on the RAG-coverage surface (``rag_coverage.py``). Both reuse the same
``BaseIndexProvider`` introspection and the ``IndexProvider`` model.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.index_providers.registry import build_index_provider
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.schemas.index_explorer import (
    IndexPartitionKey,
    IndexProviderOptionListResponse,
    IndexSummaryResponse,
    IndexTreeDocument,
    IndexTreeGroupNode,
    IndexTreeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/index-explorer",
    tags=["index-explorer"],
    dependencies=[require_section("observe", "data-sources")],
)

_MAX_SAMPLE = 200


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
    group_by: list[str] = Query(..., min_length=1),
    path: list[str] = Query(default_factory=list),
    limit: int = Query(50, ge=1, le=_MAX_SAMPLE),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """One lazily-expanded level of the index tree.

    ``path`` holds the already-selected values for ``group_by[:len(path)]``. When
    grouping keys remain, return the next field's distribution (filtered by the
    path); once the path is complete, return sampled documents for the leaf.
    """
    if len(path) > len(group_by):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "BAD_REQUEST", "message": "path longer than group_by"}},
        )

    provider = await _get_provider_or_404(db, provider_id, project)
    filters = {group_by[i]: path[i] for i in range(len(path))}
    client = build_index_provider(provider)
    try:
        if len(path) < len(group_by):
            next_key = group_by[len(path)]
            has_children = len(path) + 1 < len(group_by)
            values = await client.get_partition_distribution(next_key, filters or None)
            return IndexTreeResponse(
                level="group",
                key=next_key,
                groups=[
                    IndexTreeGroupNode(
                        value=v.value, doc_count=v.doc_count, has_children=has_children
                    )
                    for v in values
                ],
            )

        # Path complete → sample documents for the leaf value.
        leaf_key = group_by[-1]
        leaf_value = path[-1]
        ancestors = {group_by[i]: path[i] for i in range(len(path) - 1)}
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
