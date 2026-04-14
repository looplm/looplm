from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class LangSmithConfigError(ValueError):
    pass


class LangSmithService:
    def __init__(self) -> None:
        if not settings.langsmith_api_key:
            raise LangSmithConfigError("LANGSMITH_API_KEY is required for LangSmith requests")
        self.endpoint = settings.langchain_endpoint.rstrip("/")
        self.project = settings.langchain_project.strip() or None

    async def fetch_sessions(self, limit: int = 10) -> Any:
        headers = {"X-Api-Key": settings.langsmith_api_key}
        params = {"limit": str(limit)}

        async with httpx.AsyncClient(base_url=self.endpoint, headers=headers, timeout=20.0) as client:
            response = await client.get("/sessions", params=params)
            if response.status_code in {404, 405}:
                response = await client.get("/api/v1/sessions", params=params)
            response.raise_for_status()
            return response.json()

    async def resolve_session_id(self) -> str | None:
        if not self.project:
            return None

        payload = await self.fetch_sessions(limit=100)
        if isinstance(payload, list):
            for session in payload:
                if isinstance(session, dict) and session.get("name") == self.project:
                    return session.get("id")
        return None

    async def fetch_runs(
        self, session_id: str, limit: int = 25, cursor: str | None = None
    ) -> Any:
        headers = {"X-Api-Key": settings.langsmith_api_key}
        body: dict[str, Any] = {"session": [session_id], "limit": limit}
        if cursor:
            body["cursor"] = cursor

        async with httpx.AsyncClient(base_url=self.endpoint, headers=headers, timeout=30.0) as client:
            response = await client.post("/runs/query", json=body)
            if response.status_code in {404, 405}:
                response = await client.post("/api/v1/runs/query", json=body)
            response.raise_for_status()
            return response.json()
