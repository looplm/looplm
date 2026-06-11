from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_project, get_current_user
from app.models.project import Project
from app.models.user import User
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

router = APIRouter(tags=["analysis"])


class AnalysisPreviewRequest(BaseModel):
    trace: dict[str, Any] = Field(default_factory=dict)
    instructions: str = ""


class AnalysisPreviewResponse(BaseModel):
    provider: str
    model: str
    analysis: str


@router.post("/analysis/preview", response_model=AnalysisPreviewResponse)
async def analysis_preview(
    payload: AnalysisPreviewRequest,
    _user: User = Depends(get_current_user),
    project: Project = Depends(get_current_project),
) -> AnalysisPreviewResponse:
    try:
        service = AnalysisLlmService(user_settings=_user.settings, project_settings=project.settings)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(status_code=400, detail="Analysis LLM not configured") from exc

    try:
        analysis_text, _usage = await service.analyze_trace(
            trace=payload.trace, instructions=payload.instructions
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("LLM analysis failed")
        raise HTTPException(status_code=502, detail="LLM analysis failed") from exc

    return AnalysisPreviewResponse(
        provider=service.provider,
        model=service.model,
        analysis=analysis_text,
    )
