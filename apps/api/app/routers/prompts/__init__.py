"""Prompt import & analysis endpoints.

Assembled from two sub-routers into a single `router` that keeps the original
`/api/prompts` prefix and `improve/prompts` section dependency, so callers can
still do `from app.routers import prompts; prompts.router` exactly as before.

Include order matters for FastAPI path matching: `import_sync` carries the
collection-level routes (including the literal `/exclusions`) and must be
included before `extraction_workflow`, whose `/{prompt_id}` catch-alls would
otherwise shadow them. Within `extraction_workflow`, the literal
`/extract/github/*` paths are declared before the `/{prompt_id}` routes.
"""

from fastapi import APIRouter

from app.auth import require_section
from app.schemas.prompts import PromptListResponse

from . import extraction_workflow, import_sync

router = APIRouter(
    prefix="/api/prompts",
    tags=["prompts"],
    dependencies=[require_section("improve", "prompts")],
)

# `GET /api/prompts` lives on the parent router: an included sub-router cannot
# carry a route whose prefix and path are both empty.
router.add_api_route(
    "",
    import_sync.list_all_prompts,
    methods=["GET"],
    response_model=PromptListResponse,
)
router.include_router(import_sync.router)
router.include_router(extraction_workflow.router)

__all__ = ["router"]
