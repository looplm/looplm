"""Chunk relevance labeling endpoints — the human-in-the-loop retrieval judging flow.

A human opens an eval run, sees the chunks each case retrieved, and marks them relevant or
not. Those labels (pooled across runs per test case) become the ground truth the
chunk-level retrieval metrics are computed against.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth import require_section

from . import diagnosis, llm_ops, operations, views

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_section("evaluate", "labeling")],
)

# Include order preserves the original module's registration: read endpoints (the GET views)
# first, then the human-label mutations/agreement, then the LLM-backed ops (AI judge, planner).
# All paths are specific and static, so ordering does not affect matching.
router.include_router(views.router)
router.include_router(operations.router)
router.include_router(llm_ops.router)
router.include_router(diagnosis.router)

__all__ = ["router"]
