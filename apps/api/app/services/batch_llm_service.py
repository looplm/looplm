"""Azure OpenAI Batch API wrapper for bulk LLM judge evaluation."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class BatchLlmService:
    """Wraps Azure OpenAI / OpenAI Batch API operations."""

    def __init__(self, user_settings: dict | None = None) -> None:
        us = user_settings or {}
        self.provider = us.get("llm_provider") or settings.analysis_llm_provider

        if self.provider == "openai":
            api_key = us.get("openai_api_key") or settings.openai_api_key
            if not api_key:
                raise ValueError("OpenAI API key is required for batch mode.")
            self._model = settings.openai_model
            self._client = AsyncOpenAI(api_key=api_key, timeout=120.0)
        else:
            api_key = us.get("azure_openai_api_key") or settings.azure_openai_api_key
            if not api_key:
                raise ValueError("Azure OpenAI API key is required for batch mode.")
            endpoint = us.get("azure_openai_endpoint") or settings.azure_openai_endpoint
            if not endpoint:
                raise ValueError("Azure OpenAI endpoint is required for batch mode.")
            deployment = us.get("azure_openai_deployment") or settings.azure_openai_deployment
            if not deployment:
                raise ValueError("Azure OpenAI deployment is required for batch mode.")
            api_version = us.get("azure_openai_api_version") or settings.azure_openai_api_version

            self._model = deployment
            self._client = AsyncAzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint,
                timeout=120.0,
            )

    @property
    def model(self) -> str:
        return self._model

    def build_batch_request(
        self,
        custom_id: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Build a single JSONL line dict for the batch input file."""
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            },
        }

    async def submit_batch(self, requests: list[dict[str, Any]]) -> tuple[str, str]:
        """Write JSONL, upload file, create batch.

        Returns (batch_id, input_file_id).
        """
        # Build JSONL content
        lines = [json.dumps(req, ensure_ascii=False) for req in requests]
        content = "\n".join(lines).encode("utf-8")

        # Upload input file
        file_obj = io.BytesIO(content)
        file_obj.name = "batch_input.jsonl"
        uploaded = await self._client.files.create(file=file_obj, purpose="batch")
        input_file_id = uploaded.id
        logger.info("Uploaded batch input file: %s (%d requests)", input_file_id, len(requests))

        # Create batch job
        batch = await self._client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        logger.info("Created batch job: %s (status: %s)", batch.id, batch.status)
        return batch.id, input_file_id

    async def check_status(self, batch_id: str) -> dict[str, Any]:
        """Check batch job status. Returns status dict with counts."""
        batch = await self._client.batches.retrieve(batch_id)
        return {
            "status": batch.status,
            "output_file_id": batch.output_file_id,
            "error_file_id": batch.error_file_id,
            "completed": batch.request_counts.completed if batch.request_counts else 0,
            "failed": batch.request_counts.failed if batch.request_counts else 0,
            "total": batch.request_counts.total if batch.request_counts else 0,
        }

    async def download_results(self, output_file_id: str) -> list[dict[str, Any]]:
        """Download and parse the results JSONL file."""
        response = await self._client.files.content(output_file_id)
        content = response.text
        results = []
        for line in content.strip().split("\n"):
            if line.strip():
                results.append(json.loads(line))
        return results

    async def cancel_batch(self, batch_id: str) -> None:
        """Cancel a running batch job."""
        await self._client.batches.cancel(batch_id)
        logger.info("Cancelled batch job: %s", batch_id)
