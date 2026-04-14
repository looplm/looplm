"""User settings endpoints — GET/PATCH for LLM API keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys that contain secrets and should be masked in responses.
_SECRET_KEYS = {"openai_api_key", "azure_openai_api_key"}


def _mask(value: str | None) -> str:
    """Mask a secret value for display: show first 4 + last 3 chars."""
    if not value:
        return ""
    if len(value) <= 7:
        return value[0] + "..." + value[-1] if len(value) >= 2 else "***"
    return value[:4] + "..." + value[-3:]


def _settings_to_response(settings: dict) -> UserSettingsResponse:
    return UserSettingsResponse(
        llm_provider=settings.get("llm_provider", ""),
        openai_api_key=_mask(settings.get("openai_api_key")),
        azure_openai_api_key=_mask(settings.get("azure_openai_api_key")),
        azure_openai_endpoint=settings.get("azure_openai_endpoint", ""),
        azure_openai_deployment=settings.get("azure_openai_deployment", ""),
        azure_openai_api_version=settings.get("azure_openai_api_version", ""),
    )


@router.get("", response_model=UserSettingsResponse)
async def get_settings(user: User = Depends(get_current_user)):
    return _settings_to_response(user.settings or {})


@router.patch("", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current = dict(user.settings or {})
    incoming = body.model_dump(exclude_none=True)
    current.update(incoming)

    await db.execute(
        update(User).where(User.id == user.id).values(settings=current)
    )
    await db.commit()

    # Refresh in-memory object
    user.settings = current
    return _settings_to_response(current)
