"""LangSmith connector implementation."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from connectors.base import BaseConnector, ProgressCallback, SyncProgress
from connectors.langsmith import normalization

logger = logging.getLogger(__name__)

LANGSMITH_API_URL = "https://api.smith.langchain.com"

# LangSmith's /runs/query caps `limit` at 100 per request; larger pulls must paginate.
_PAGE_SIZE = 100
# Throttle between pages so a large sync drips rather than bursts at the rate limiter.
_INTER_PAGE_DELAY = 0.25
# Retry behaviour for rate limits (429) and transient upstream errors.
_RETRY_STATUS = {429, 502, 503, 504}
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 30.0


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_dt is None:
        return None
    return max(0.0, (retry_dt - datetime.now(retry_dt.tzinfo)).total_seconds())


class LangSmithConnector(BaseConnector):
    """Pull and normalize traces from LangSmith."""

    def __init__(self, api_key: str, api_url: str = LANGSMITH_API_URL, project: str | None = None):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.project = project
        self._headers = {"x-api-key": api_key}

    async def test_connection(self) -> bool:
        """Verify API connectivity."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.api_url}/info",
                    headers=self._headers,
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("LangSmith health check failed: %s", e)
            return False

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue a request, retrying on rate limits and transient upstream errors.

        On a 429 the server's Retry-After header is honored exactly; otherwise we
        back off exponentially with jitter. After exhausting retries the last
        response's status is raised.
        """
        for attempt in range(_MAX_RETRIES + 1):
            resp = await client.request(method, url, headers=self._headers, **kwargs)
            if resp.status_code not in _RETRY_STATUS or attempt == _MAX_RETRIES:
                resp.raise_for_status()
                return resp
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            if retry_after is None:
                retry_after = min(_MAX_BACKOFF, _INITIAL_BACKOFF * (2**attempt))
            backoff = retry_after + random.uniform(0, retry_after * 0.25)
            logger.warning(
                "LangSmith %s %s -> %d; retrying in %.1fs (attempt %d/%d)",
                method,
                url,
                resp.status_code,
                backoff,
                attempt + 1,
                _MAX_RETRIES,
            )
            await asyncio.sleep(backoff)
        # Unreachable: the loop returns or raises on its final iteration.
        raise RuntimeError("LangSmith request retries exhausted")

    async def fetch_traces(
        self,
        since: datetime,
        limit: int = 100,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw runs (traces) from LangSmith API."""
        if on_progress is not None:
            await on_progress(SyncProgress(
                phase="fetching_traces",
                message=f"Querying LangSmith for traces since {since.date().isoformat()}",
            ))
        runs: list[dict[str, Any]] = []
        async with httpx.AsyncClient() as client:
            # /runs/query requires at least one of session/id/trace/... — a bare
            # start_time + is_root query is rejected. Scope to the configured
            # project, or to every session in the workspace when none is set.
            if self.project:
                project_id = await self._resolve_project_id(client, self.project)
                session_filter = [project_id] if project_id else []
            else:
                session_filter = await self._resolve_all_session_ids(client)

            if not session_filter:
                logger.warning("LangSmith: no sessions found to query; nothing to sync")
                return []

            # The API caps `limit` at 100 per request, so page with cursors until
            # we reach the caller's requested total (or run out of runs).
            cursor: str | None = None
            while len(runs) < limit:
                query_body: dict[str, Any] = {
                    "is_root": True,
                    "start_time": since.isoformat(),
                    "limit": min(_PAGE_SIZE, limit - len(runs)),
                    "session": session_filter,
                }
                if cursor:
                    query_body["cursor"] = cursor

                resp = await self._request(
                    client,
                    "POST",
                    f"{self.api_url}/runs/query",
                    json=query_body,
                    timeout=30,
                )
                data = resp.json()
                page = data.get("runs", data) if isinstance(data, dict) else data
                if not page:
                    break
                runs.extend(page)

                if on_progress is not None:
                    await on_progress(SyncProgress(
                        phase="fetching_traces",
                        message=f"Fetched {len(runs)} traces",
                        current=len(runs),
                    ))

                cursors = data.get("cursors", {}) if isinstance(data, dict) else {}
                cursor = cursors.get("next")
                if not cursor:
                    break
                await asyncio.sleep(_INTER_PAGE_DELAY)
        if on_progress is not None:
            await on_progress(SyncProgress(
                phase="fetching_traces",
                message=f"Found {len(runs)} traces",
                current=len(runs),
            ))
        return runs[:limit]

    async def _resolve_project_id(self, client: httpx.AsyncClient, project_name: str) -> str | None:
        """Look up a LangSmith project (session) ID by name."""
        resp = await self._request(
            client,
            "GET",
            f"{self.api_url}/sessions",
            params={"name": project_name},
            timeout=10,
        )
        sessions = resp.json()
        if sessions:
            return str(sessions[0]["id"])
        return None

    async def _resolve_all_session_ids(self, client: httpx.AsyncClient) -> list[str]:
        """List every project (session) ID in the workspace.

        Used when no specific project is configured, since /runs/query requires
        a session (or other) filter and rejects an unscoped query.
        """
        resp = await self._request(
            client,
            "GET",
            f"{self.api_url}/sessions",
            timeout=10,
        )
        sessions = resp.json()
        if not isinstance(sessions, list):
            return []
        return [str(s["id"]) for s in sessions if isinstance(s, dict) and s.get("id")]

    async def fetch_trace_detail(self, trace_id: str) -> dict[str, Any]:
        """Fetch a run and its child runs."""
        async with httpx.AsyncClient() as client:
            # Get the root run
            resp = await self._request(
                client,
                "GET",
                f"{self.api_url}/runs/{trace_id}",
                timeout=30,
            )
            run = resp.json()

            # Get child runs with cursor-based pagination (API max is 100 per page)
            all_children: list[dict[str, Any]] = []
            body: dict[str, Any] = {"trace": trace_id, "is_root": False, "limit": _PAGE_SIZE}
            while True:
                children_resp = await self._request(
                    client,
                    "POST",
                    f"{self.api_url}/runs/query",
                    json=body,
                    timeout=30,
                )
                children_data = children_resp.json()
                runs = children_data.get("runs", children_data) if isinstance(children_data, dict) else children_data
                if not runs:
                    break
                all_children.extend(runs)
                cursors = children_data.get("cursors", {}) if isinstance(children_data, dict) else {}
                if not cursors.get("next"):
                    break
                body["cursor"] = cursors["next"]
                await asyncio.sleep(_INTER_PAGE_DELAY)

            run["child_runs"] = all_children
            return run

    def normalize_trace(self, raw_trace: dict[str, Any]) -> dict[str, Any]:
        """Convert LangSmith run to unified LoopLM schema."""
        child_runs = raw_trace.get("child_runs", [])

        # Determine status
        status = "success"
        error_message = None
        if raw_trace.get("error"):
            status = "failure"
            error_message = raw_trace["error"]
        elif raw_trace.get("status") == "error":
            status = "failure"

        # Duration
        duration_ms = None
        if raw_trace.get("total_time"):
            duration_ms = int(raw_trace["total_time"] * 1000)
        elif raw_trace.get("start_time") and raw_trace.get("end_time"):
            try:
                start = datetime.fromisoformat(raw_trace["start_time"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(raw_trace["end_time"].replace("Z", "+00:00"))
                duration_ms = int((end - start).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass

        # Normalize child runs to spans (backward compat)
        spans = []
        # Normalize child runs to child traces (new hierarchical model)
        child_traces = []
        root_external_id = str(raw_trace.get("id", ""))

        for child in child_runs:
            span_type = self._map_run_type(child.get("run_type", "chain"))
            child_status = "error" if child.get("error") else "success"

            token_usage = child.get("total_tokens") or {}
            if isinstance(token_usage, int):
                tokens_in = child.get("prompt_tokens")
                tokens_out = child.get("completion_tokens")
            else:
                tokens_in = token_usage.get("prompt_tokens")
                tokens_out = token_usage.get("completion_tokens")

            child_duration = None
            if child.get("total_time"):
                child_duration = int(child["total_time"] * 1000)

            child_metadata = child.get("extra", {}).get("metadata", {}) if isinstance(child.get("extra"), dict) else {}

            span = {
                "external_id": child.get("id"),
                "name": child.get("name"),
                "type": span_type,
                "model": child.get("extra", {}).get("metadata", {}).get("ls_model_name") if isinstance(child.get("extra"), dict) else None,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration_ms": child_duration,
                "status": child_status,
                "error_message": child.get("error"),
            }
            spans.append(span)

            # Build child trace dict
            child_trace_status = "success"
            if child.get("error"):
                child_trace_status = "failure"
            elif child.get("status") == "error":
                child_trace_status = "failure"

            child_trace = {
                "external_id": str(child.get("id", "")),
                "name": child.get("name"),
                "input": child.get("inputs"),
                "output": child.get("outputs"),
                "metadata": child_metadata,
                "start_time": self._parse_datetime(child.get("start_time")),
                "end_time": self._parse_datetime(child.get("end_time")),
                "duration_ms": child_duration,
                "status": child_trace_status,
                "error_message": child.get("error"),
                "run_type": child.get("run_type", "chain"),
                "parent_external_id": str(child.get("parent_run_id", "")) or root_external_id,
                "root_external_id": root_external_id,
            }
            child_traces.append(child_trace)

        metadata = raw_trace.get("extra", {}).get("metadata", {}) if isinstance(raw_trace.get("extra"), dict) else {}

        return {
            "external_id": str(raw_trace.get("id", "")),
            "name": raw_trace.get("name"),
            "input": raw_trace.get("inputs"),
            "output": raw_trace.get("outputs"),
            "metadata": metadata,
            "thread_id": self._extract_thread_id(metadata),
            "start_time": self._parse_datetime(raw_trace.get("start_time")),
            "end_time": self._parse_datetime(raw_trace.get("end_time")),
            "duration_ms": duration_ms,
            "status": status,
            "error_message": error_message,
            "run_type": raw_trace.get("run_type", "chain"),
            "user_id": None,
            "spans": spans,
            "child_traces": child_traces,
        }

    async def sync(
        self,
        since: datetime,
        on_progress: ProgressCallback | None = None,
        limit: int = 5000,
        enrich_limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Full sync: fetch traces and enrich the most recent ones with child runs."""
        raw_traces = await self.fetch_traces(since, limit=limit, on_progress=on_progress)
        if len(raw_traces) >= limit:
            logger.warning(
                "LangSmith sync hit the %d-trace cap; older traces in the window were not synced",
                limit,
            )

        async def _enrich(trace: dict[str, Any]) -> dict[str, Any]:
            try:
                return await self.fetch_trace_detail(str(trace.get("id", "")))
            except Exception as e:
                logger.warning("Failed to fetch detail for run %s: %s", trace.get("id"), e)
                return trace

        # Fetch details concurrently (bounded to avoid overwhelming the API)
        sem = asyncio.Semaphore(5)

        async def _bounded_enrich(trace: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                return await _enrich(trace)

        # Only enrich the most recent N traces to avoid rate limits
        to_enrich = raw_traces[:enrich_limit]
        rest = raw_traces[enrich_limit:]

        if on_progress is not None and to_enrich:
            await on_progress(SyncProgress(
                phase="processing_traces",
                message=f"Enriching {len(to_enrich)} most recent traces with child runs",
                current=0,
                total=len(raw_traces),
            ))

        enriched = await asyncio.gather(*[_bounded_enrich(t) for t in to_enrich])
        return list(enriched) + rest

    async def sync_prompts(self) -> list[dict]:
        """Fetch prompts from LangSmith using the official SDK."""
        import re
        from langsmith import Client

        ls_client = Client(api_key=self.api_key, api_url=self.api_url)

        prompts: list[dict] = []
        for repo in ls_client.list_prompts(is_public=False, limit=100).repos:
            repo_name = repo.repo_handle
            owner = repo.owner or "-"

            # Fetch latest commit with full manifest
            try:
                commit = ls_client.pull_prompt_commit(f"{owner}/{repo_name}")
                manifest = commit.manifest if hasattr(commit, "manifest") else {}
                if isinstance(manifest, dict):
                    template = self._extract_template(manifest)
                else:
                    template = str(manifest)
            except Exception as e:
                logger.warning("Failed to pull prompt %s: %s", repo_name, e)
                template = ""

            variables = list(dict.fromkeys(re.findall(r"\{(\w+)\}", template))) if isinstance(template, str) else []

            prompts.append({
                "external_id": str(repo.id),
                "name": repo_name,
                "template": template if isinstance(template, str) else str(template),
                "version": repo.num_commits or 1,
                "variables": variables,
                "metadata": {
                    "owner": owner,
                    "repo": repo_name,
                    "tags": repo.tags or [],
                },
            })
        return prompts

    @classmethod
    def _extract_template(cls, manifest: dict) -> str:
        """Extract prompt template text from a LangSmith commit manifest."""
        return normalization.extract_template(manifest)

    @classmethod
    def _extract_from_lc(cls, obj: dict) -> str:
        """Recursively extract template text from a LangChain serialized object."""
        return normalization.extract_from_lc(obj)

    @staticmethod
    def _lc_id_to_role(lc_id: list) -> str:
        """Map a LangChain class ID to a chat role name."""
        return normalization.lc_id_to_role(lc_id)

    @staticmethod
    def _format_messages(messages: list) -> str:
        """Format a list of plain message dicts into template text."""
        return normalization.format_messages(messages)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """Parse an ISO timestamp string into a datetime object."""
        return normalization.parse_datetime(value)

    @staticmethod
    def _extract_thread_id(metadata: dict[str, Any]) -> str | None:
        """Extract thread ID from run metadata, checking common key names."""
        return normalization.extract_thread_id(metadata)

    @staticmethod
    def _map_run_type(run_type: str) -> str:
        return normalization.map_run_type(run_type)
