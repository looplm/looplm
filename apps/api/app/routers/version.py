"""Version metadata endpoint — surfaced in the UI's About panel."""

import os
from importlib.metadata import PackageNotFoundError, version as pkg_version

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["version"])


def _connectors_version() -> str | None:
    try:
        return pkg_version("looplm-connectors")
    except PackageNotFoundError:
        return None


@router.get("/api/version")
async def get_version() -> dict[str, str | None]:
    return {
        "api": __version__,
        "connectors": _connectors_version(),
        "commit": os.getenv("LOOPLM_GIT_SHA") or None,
    }
