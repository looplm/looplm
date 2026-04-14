from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.models.user import User
from app.services.langsmith import LangSmithConfigError, LangSmithService

router = APIRouter(tags=["langsmith"])


def _extract_sessions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("sessions", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _extract_runs(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        runs = payload.get("runs")
        if isinstance(runs, list):
            return [item for item in runs if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


@router.get("/langsmith/ping")
async def langsmith_ping(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        service = LangSmithService()
    except LangSmithConfigError:
        raise HTTPException(status_code=400, detail="LangSmith not configured")

    try:
        payload = await service.fetch_sessions(limit=25)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="LangSmith API error") from exc
    except Exception:
        raise HTTPException(status_code=502, detail="LangSmith request failed")

    sessions = _extract_sessions(payload)
    project_found = None
    if service.project:
        project_found = any(
            session.get("name") == service.project for session in sessions if isinstance(session, dict)
        )
    return {
        "status": "ok",
        "endpoint": service.endpoint,
        "project": service.project,
        "sessions_found": len(sessions),
        "project_found": project_found,
    }


@router.get("/langsmith/runs")
async def langsmith_runs(
    limit: int = Query(default=25, ge=1, le=200),
    session_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        service = LangSmithService()
    except LangSmithConfigError:
        raise HTTPException(status_code=400, detail="LangSmith not configured")

    try:
        resolved_session = session_id or await service.resolve_session_id()
        if not resolved_session:
            raise HTTPException(
                status_code=400,
                detail="No session_id provided and project did not match a session",
            )
        payload = await service.fetch_runs(
            session_id=resolved_session,
            limit=limit,
            cursor=cursor,
        )
    except HTTPException:
        raise
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="LangSmith API error")
    except Exception:
        raise HTTPException(status_code=502, detail="LangSmith request failed")

    runs = _extract_runs(payload)
    cursors = payload.get("cursors") if isinstance(payload, dict) else None
    next_cursor = None
    prev_cursor = None
    if isinstance(cursors, dict):
        next_cursor = cursors.get("next")
        prev_cursor = cursors.get("prev")
    return {
        "status": "ok",
        "endpoint": service.endpoint,
        "project": service.project,
        "session_id": resolved_session,
        "runs_found": len(runs),
        "cursors": cursors,
        "next_cursor": next_cursor,
        "prev_cursor": prev_cursor,
        "runs": runs,
    }
