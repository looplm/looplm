"""LangSmith connector implementation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from connectors.base import BaseConnector, ProgressCallback, SyncProgress

logger = logging.getLogger(__name__)

LANGSMITH_API_URL = "https://api.smith.langchain.com"


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
        runs = []
        async with httpx.AsyncClient() as client:
            query_body: dict[str, Any] = {
                "is_root": True,
                "start_time": since.isoformat(),
                "limit": limit,
            }
            if self.project:
                project_id = await self._resolve_project_id(client, self.project)
                if project_id:
                    query_body["session"] = [project_id]
            resp = await client.post(
                f"{self.api_url}/runs/query",
                headers=self._headers,
                json=query_body,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            runs = data.get("runs", data) if isinstance(data, dict) else data
        if on_progress is not None:
            await on_progress(SyncProgress(
                phase="fetching_traces",
                message=f"Found {len(runs)} traces",
                current=len(runs),
            ))
        return runs[:limit]

    async def _resolve_project_id(self, client: httpx.AsyncClient, project_name: str) -> str | None:
        """Look up a LangSmith project (session) ID by name."""
        resp = await client.get(
            f"{self.api_url}/sessions",
            headers=self._headers,
            params={"name": project_name},
            timeout=10,
        )
        resp.raise_for_status()
        sessions = resp.json()
        if sessions:
            return str(sessions[0]["id"])
        return None

    async def fetch_trace_detail(self, trace_id: str) -> dict[str, Any]:
        """Fetch a run and its child runs."""
        async with httpx.AsyncClient() as client:
            # Get the root run
            resp = await client.get(
                f"{self.api_url}/runs/{trace_id}",
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            run = resp.json()

            # Get child runs with cursor-based pagination (API max is 100 per page)
            all_children: list[dict[str, Any]] = []
            body: dict[str, Any] = {"trace": trace_id, "is_root": False, "limit": 100}
            while True:
                children_resp = await client.post(
                    f"{self.api_url}/runs/query",
                    headers=self._headers,
                    json=body,
                    timeout=30,
                )
                children_resp.raise_for_status()
                children_data = children_resp.json()
                runs = children_data.get("runs", children_data) if isinstance(children_data, dict) else children_data
                if not runs:
                    break
                all_children.extend(runs)
                cursors = children_data.get("cursors", {}) if isinstance(children_data, dict) else {}
                if not cursors.get("next"):
                    break
                body["cursor"] = cursors["next"]

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
        # LangChain serialized format: {"lc": 1, "type": "constructor", "id": [...], "kwargs": {...}}
        if "lc" in manifest and "kwargs" in manifest:
            return cls._extract_from_lc(manifest)

        # Direct template string (completion-style prompts)
        template = manifest.get("template", "")
        if template:
            return template if isinstance(template, str) else str(template)

        # Chat-style prompts: list of message objects
        messages = manifest.get("messages")
        if messages and isinstance(messages, list):
            return cls._format_messages(messages)

        return ""

    @classmethod
    def _extract_from_lc(cls, obj: dict) -> str:
        """Recursively extract template text from a LangChain serialized object."""
        kwargs = obj.get("kwargs", {})

        # If this object has a direct template string, return it
        if isinstance(kwargs.get("template"), str) and kwargs["template"]:
            return kwargs["template"]

        # If this object has messages (ChatPromptTemplate), extract from each
        messages = kwargs.get("messages")
        if messages and isinstance(messages, list):
            parts = []
            for msg in messages:
                if isinstance(msg, dict) and "lc" in msg:
                    # Nested LangChain object (e.g. SystemMessagePromptTemplate)
                    msg_kwargs = msg.get("kwargs", {})
                    # The role is derived from the class name
                    msg_id = msg.get("id", [])
                    role = cls._lc_id_to_role(msg_id)

                    # Extract content from the nested prompt
                    prompt = msg_kwargs.get("prompt", {})
                    if isinstance(prompt, dict) and "kwargs" in prompt:
                        content = prompt["kwargs"].get("template", "")
                    else:
                        content = msg_kwargs.get("template", msg_kwargs.get("content", ""))

                    if role and content:
                        parts.append(f"[{role}]\n{content}")
                    elif content:
                        parts.append(str(content))
                elif isinstance(msg, dict):
                    role = msg.get("role", msg.get("type", ""))
                    content = msg.get("content", msg.get("text", ""))
                    if role and content:
                        parts.append(f"[{role}]\n{content}")
                    elif content:
                        parts.append(str(content))
            return "\n\n".join(parts)

        # If this has a nested prompt object
        prompt = kwargs.get("prompt", {})
        if isinstance(prompt, dict) and "kwargs" in prompt:
            return cls._extract_from_lc(prompt)

        return ""

    @staticmethod
    def _lc_id_to_role(lc_id: list) -> str:
        """Map a LangChain class ID to a chat role name."""
        if not lc_id:
            return ""
        class_name = lc_id[-1] if lc_id else ""
        mapping = {
            "SystemMessagePromptTemplate": "system",
            "HumanMessagePromptTemplate": "human",
            "AIMessagePromptTemplate": "ai",
            "SystemMessage": "system",
            "HumanMessage": "human",
            "AIMessage": "ai",
        }
        return mapping.get(class_name, class_name)

    @staticmethod
    def _format_messages(messages: list) -> str:
        """Format a list of plain message dicts into template text."""
        parts = []
        for m in messages:
            role = m.get("role", m.get("type", ""))
            content = m.get("content", m.get("text", ""))
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", str(c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
            if role:
                parts.append(f"[{role}]\n{content}")
            else:
                parts.append(str(content))
        return "\n\n".join(parts)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """Parse an ISO timestamp string into a datetime object."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_thread_id(metadata: dict[str, Any]) -> str | None:
        """Extract thread ID from run metadata, checking common key names."""
        if not metadata:
            return None
        return metadata.get("thread_id") or metadata.get("session_id") or metadata.get("conversation_id")

    @staticmethod
    def _map_run_type(run_type: str) -> str:
        mapping = {
            "llm": "llm",
            "tool": "tool",
            "retriever": "retriever",
            "chain": "chain",
            "agent": "chain",
            "prompt": "llm",
        }
        return mapping.get(run_type, "chain")
