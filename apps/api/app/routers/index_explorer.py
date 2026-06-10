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
from app.schemas.index_explorer import (
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
from app.services.analysis_llm import AnalysisLlmConfigError
from app.services.index_grouping_advisor import suggest_grouping

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
            client, project_id=project.id, db=db, user_settings=user.settings
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
