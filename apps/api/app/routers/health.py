"""Health check endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        logger.exception("Health check DB ping failed")
        db_status = "unhealthy"

    overall = "healthy" if db_status == "healthy" else "degraded"
    return {"status": overall, "service": "looplm-api", "database": db_status}


@router.get("/")
async def root() -> dict[str, str]:
    return {"message": "LoopLM API", "version": "0.1.0"}
