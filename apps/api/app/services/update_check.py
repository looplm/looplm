"""Looks up the latest LoopLM GitHub release for the About settings panel.

Uses an in-process TTL cache so a self-hosted instance pulls GitHub at most once
per hour. GitHub's anonymous rate limit is 60/h per IP, which is plenty for this.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app import __version__
from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/looplm/looplm/releases/latest"
SUCCESS_TTL_SECONDS = 3600
ERROR_TTL_SECONDS = 300


class UpdateChecker:
    def __init__(self) -> None:
        self._cached: dict[str, Any] | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_latest(self) -> dict[str, Any]:
        if not settings.update_check_enabled:
            return {
                "enabled": False,
                "running": __version__,
                "latest": None,
                "error": None,
            }

        async with self._lock:
            if self._cached is not None and time.monotonic() < self._expires_at:
                return self._cached

            payload = await self._fetch()
            ttl = ERROR_TTL_SECONDS if payload["error"] else SUCCESS_TTL_SECONDS
            self._cached = payload
            self._expires_at = time.monotonic() + ttl
            return payload

    async def _fetch(self) -> dict[str, Any]:
        headers = {
            "User-Agent": "looplm-update-check",
            "Accept": "application/vnd.github+json",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(GITHUB_RELEASES_URL, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
            return {
                "enabled": True,
                "running": __version__,
                "latest": None,
                "error": "Could not reach GitHub for the latest release",
            }

        return {
            "enabled": True,
            "running": __version__,
            "latest": {
                "tag": data.get("tag_name"),
                "name": data.get("name"),
                "published_at": data.get("published_at"),
                "html_url": data.get("html_url"),
                "body": data.get("body"),
            },
            "error": None,
        }


update_checker = UpdateChecker()
