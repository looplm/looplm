"""Langfuse connector implementation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

# Concurrent trace-detail fetches during enrichment. Sequential enrichment of a
# large window (hundreds of traces × 2 requests each) easily exceeds the sync
# timeout; bounded concurrency keeps it fast without hammering the API.
ENRICH_CONCURRENCY = 8

from dateutil.parser import isoparse

import httpx

from connectors.base import BaseConnector, ProgressCallback, SyncProgress

logger = logging.getLogger(__name__)


class LangfuseConnector(BaseConnector):
    """Pull and normalize traces from Langfuse."""

    def __init__(self, public_key: str, secret_key: str, host: str = "https://cloud.langfuse.com"):
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self._auth = (public_key, secret_key)

    async def test_connection(self) -> bool:
        """Verify API connectivity."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.host}/api/public/health",
                    auth=self._auth,
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Langfuse health check failed: %s", e)
            return False

    async def fetch_traces(
        self,
        since: datetime,
        limit: int = 100,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw traces from Langfuse API."""
        traces = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.host}/api/public/traces",
                    auth=self._auth,
                    params={
                        "page": page,
                        "limit": min(limit, 100),
                        "fromTimestamp": since.isoformat(),
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("data", [])
                if not batch:
                    break
                traces.extend(batch)
                if on_progress is not None:
                    await on_progress(SyncProgress(
                        phase="fetching_traces",
                        message=f"Fetched page {page} ({len(traces)} traces so far)",
                        current=len(traces),
                    ))
                if len(traces) >= limit:
                    break
                page += 1
        return traces[:limit]

    async def fetch_trace_detail(self, trace_id: str) -> dict[str, Any]:
        """Fetch full trace detail with observations."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.host}/api/public/traces/{trace_id}",
                auth=self._auth,
                timeout=30,
            )
            resp.raise_for_status()
            trace = resp.json()

            # Fetch observations for this trace
            obs_resp = await client.get(
                f"{self.host}/api/public/observations",
                auth=self._auth,
                params={"traceId": trace_id, "limit": 100},
                timeout=30,
            )
            obs_resp.raise_for_status()
            trace["observations"] = obs_resp.json().get("data", [])
            return trace

    def normalize_trace(self, raw_trace: dict[str, Any]) -> dict[str, Any]:
        """Convert Langfuse trace to unified LoopLM schema."""
        observations = raw_trace.get("observations", [])
        # Filter out string IDs (from list endpoint fallback)
        observations = [o for o in observations if isinstance(o, dict)]

        # Determine status from observations
        status = "success"
        error_message = None
        for obs in observations:
            if obs.get("level") == "ERROR" or obs.get("statusMessage"):
                status = "failure"
                obs_output = obs.get("output")
                error_message = obs.get("statusMessage") or (obs_output.get("error") if isinstance(obs_output, dict) else None)
                break

        # Calculate duration
        start_time = self._parse_ts(raw_trace.get("timestamp"))
        end_time = self._parse_ts(raw_trace.get("endTime"))
        duration_ms = None
        if raw_trace.get("latency"):
            duration_ms = int(raw_trace["latency"] * 1000)

        # Normalize spans
        spans = []
        for obs in observations:
            span_type = self._map_observation_type(obs.get("type", "SPAN"))
            obs_status = "error" if obs.get("level") == "ERROR" else "success"

            usage = obs.get("usage") or {}
            span = {
                "external_id": obs.get("id"),
                "name": obs.get("name"),
                "type": span_type,
                "input": obs.get("input"),
                "output": obs.get("output"),
                "model": obs.get("model"),
                "tokens_in": usage.get("input") or usage.get("promptTokens"),
                "tokens_out": usage.get("output") or usage.get("completionTokens"),
                "duration_ms": int(obs["latency"] * 1000) if obs.get("latency") else None,
                "status": obs_status,
                "error_message": obs.get("statusMessage"),
                "parent_external_id": obs.get("parentObservationId"),
            }
            spans.append(span)

        metadata = raw_trace.get("metadata") or {}
        # Preserve top-level Langfuse environment inside metadata
        environment = raw_trace.get("environment")
        if environment and "environment" not in metadata:
            metadata["environment"] = environment
        thread_id = raw_trace.get("sessionId") or metadata.get("thread_id") or metadata.get("session_id") or metadata.get("conversation_id")

        return {
            "external_id": raw_trace.get("id", ""),
            "name": raw_trace.get("name"),
            "input": raw_trace.get("input"),
            "output": raw_trace.get("output"),
            "metadata": metadata,
            "thread_id": thread_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": duration_ms,
            "status": status,
            "error_message": error_message,
            "user_id": raw_trace.get("userId"),
            "spans": spans,
        }

    async def fetch_scores(
        self,
        since: datetime,
        limit: int = 500,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch scores from Langfuse API (feedback + grader scores)."""
        scores: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.host}/api/public/scores",
                    auth=self._auth,
                    params={
                        "page": page,
                        "limit": min(limit, 100),
                        "fromTimestamp": since.isoformat(),
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("data", [])
                if not batch:
                    break
                scores.extend(batch)
                if on_progress is not None:
                    await on_progress(SyncProgress(
                        phase="fetching_scores",
                        message=f"Fetched page {page} ({len(scores)} scores so far)",
                        current=len(scores),
                    ))
                if len(scores) >= limit:
                    break
                page += 1
        return scores[:limit]

    def normalize_score(self, raw_score: dict[str, Any]) -> dict[str, Any]:
        """Convert Langfuse score to unified LoopLM schema."""
        return {
            "external_id": raw_score.get("id", ""),
            "trace_id": raw_score.get("traceId", ""),
            "name": raw_score.get("name", ""),
            "value": float(raw_score.get("value", 0)),
            "data_type": raw_score.get("dataType", "BOOLEAN"),
            "comment": raw_score.get("comment"),
            "scored_at": self._parse_ts(raw_score.get("createdAt")),
        }

    async def sync(
        self,
        since: datetime,
        on_progress: ProgressCallback | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Full sync: fetch traces and enrich with observations."""
        raw_traces = await self.fetch_traces(since, limit=limit, on_progress=on_progress)
        total = len(raw_traces)
        if total >= limit:
            logger.warning(
                "Langfuse sync hit the %d-trace cap; older traces in the window were not synced",
                limit,
            )
        if on_progress is not None:
            await on_progress(SyncProgress(
                phase="processing_traces",
                message=f"Enriching {total} traces with observations",
                current=0,
                total=total,
            ))

        # Enrich concurrently (bounded). on_progress writes to a shared DB session
        # and is NOT concurrency-safe, so we don't emit per-trace progress here —
        # the storing loop reports granular progress afterwards.
        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def _enrich(trace: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                try:
                    return await self.fetch_trace_detail(trace["id"])
                except Exception as e:
                    logger.warning("Failed to fetch detail for trace %s: %s", trace.get("id"), e)
                    return trace

        # gather preserves input order, so results line up with raw_traces.
        return list(await asyncio.gather(*[_enrich(t) for t in raw_traces]))

    async def sync_prompts(self) -> list[dict]:
        """Fetch prompts from Langfuse Prompt Management API."""
        prompts: list[dict] = []
        async with httpx.AsyncClient() as client:
            page = 1
            while True:
                resp = await client.get(
                    f"{self.host}/api/public/v2/prompts",
                    auth=self._auth,
                    params={"page": page, "limit": 50},
                    timeout=30,
                )
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("data", [])
                if not batch:
                    break
                for p in batch:
                    name = p.get("name", "unnamed")
                    versions = p.get("versions", [1])
                    for ver in versions if isinstance(versions, list) else [versions]:
                        # Langfuse V2 list returns version numbers, fetch full prompt
                        if isinstance(ver, int):
                            try:
                                vresp = await client.get(
                                    f"{self.host}/api/public/v2/prompts/{name}",
                                    auth=self._auth,
                                    params={"version": ver},
                                    timeout=30,
                                )
                                vresp.raise_for_status()
                                v = vresp.json()
                            except Exception:
                                continue
                        else:
                            v = ver
                        template = v.get("prompt", "")
                        if isinstance(template, list):
                            template = "\n".join(
                                m.get("content", str(m)) for m in template
                            )
                        variables = v.get("config", {}).get("variables", [])
                        if not variables and isinstance(template, str):
                            import re
                            variables = re.findall(r"\{\{(\w+)\}\}", template)
                        prompts.append({
                            "external_id": str(v.get("id", name)),
                            "name": name,
                            "template": template if isinstance(template, str) else str(template),
                            "version": v.get("version", ver if isinstance(ver, int) else 1),
                            "variables": variables,
                            "metadata": {
                                "type": p.get("type", "text"),
                                "labels": v.get("labels", []),
                            },
                        })
                page += 1
        return prompts

    @staticmethod
    def _parse_ts(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return isoparse(value)
        except Exception:
            return None

    @staticmethod
    def _map_observation_type(obs_type: str) -> str:
        mapping = {
            "GENERATION": "llm",
            "SPAN": "chain",
            "EVENT": "tool",
        }
        return mapping.get(obs_type, "chain")
