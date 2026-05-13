"""Platform-admin endpoints for instance maintenance (migrations, etc.)."""

from __future__ import annotations

import asyncio
import io
import logging
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_platform_admin
from app.config import settings
from app.db import engine, get_db
from app.models.admin_audit import AdminAudit
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# apps/api/alembic.ini relative to apps/api/app/routers/admin.py
_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # Override with the runtime DB URL — alembic.ini hardcodes localhost.
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _read_current_rev(sync_conn: Any) -> str | None:
    ctx = MigrationContext.configure(sync_conn)
    return ctx.get_current_revision()


async def _get_current_revision() -> str | None:
    async with engine.connect() as conn:
        return await conn.run_sync(_read_current_rev)


@router.get("/migrations")
async def list_migrations(
    _admin: User = Depends(require_platform_admin),
) -> dict[str, Any]:
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    head = heads[0] if heads else None
    current = await _get_current_revision()

    pending: list[dict[str, str | None]] = []
    if head and current != head:
        for rev in script.walk_revisions(head, current or "base"):
            if rev.revision == current:
                break
            pending.append({"revision": rev.revision, "message": rev.doc})
        pending.reverse()

    return {
        "current_rev": current,
        "head_rev": head,
        "pending": pending,
    }


def _run_upgrade_sync(cfg: Config) -> tuple[bool, str]:
    """Run alembic upgrade head, capturing stdout/stderr and alembic logging."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    alembic_logger = logging.getLogger("alembic")
    alembic_logger.addHandler(handler)
    prior_level = alembic_logger.level
    alembic_logger.setLevel(logging.INFO)
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            command.upgrade(cfg, "head")
        return True, buf.getvalue()
    except Exception as exc:
        logger.exception("Migration upgrade failed")
        return False, buf.getvalue() + f"\nERROR: {exc}"
    finally:
        alembic_logger.removeHandler(handler)
        alembic_logger.setLevel(prior_level)


@router.post("/migrations/upgrade")
async def run_migrations(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_platform_admin),
) -> dict[str, Any]:
    before_rev = await _get_current_revision()
    cfg = _alembic_config()
    success, output = await asyncio.to_thread(_run_upgrade_sync, cfg)
    after_rev = await _get_current_revision()

    db.add(
        AdminAudit(
            user_id=admin.id,
            action="migrations.upgrade",
            details={
                "before": before_rev,
                "after": after_rev,
                "success": success,
            },
        )
    )
    await db.flush()

    return {
        "success": success,
        "before_rev": before_rev,
        "after_rev": after_rev,
        "output": output,
    }
