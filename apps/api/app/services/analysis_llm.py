from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI, BadRequestError

from app.config import settings
from app.services.llm_pricing import calculate_cost

logger = logging.getLogger(__name__)


@dataclass
class LlmUsageInfo:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None
    cached_tokens: int
    reasoning_tokens: int
    duration_ms: int


class AnalysisLlmConfigError(ValueError):
    pass


def merge_llm_settings(
    project_settings: dict | None, user_settings: dict | None
) -> dict:
    """Effective analysis-LLM settings.

    Project settings are shared by all members and take priority; a user's
    personal settings fill any gaps so an already-configured personal key keeps
    working until the project-level key is set. Empty project values never clobber
    a usable personal fallback.
    """
    merged = dict(user_settings or {})
    for key, value in (project_settings or {}).items():
        if value:
            merged[key] = value
    return merged


class AnalysisLlmService:
    def __init__(
        self,
        user_settings: dict | None = None,
        project_settings: dict | None = None,
    ) -> None:
        us = merge_llm_settings(project_settings, user_settings)

        self.provider = us.get("llm_provider") or settings.analysis_llm_provider

        if self.provider == "openai":
            api_key = us.get("openai_api_key") or settings.openai_api_key
            if not api_key:
                raise AnalysisLlmConfigError(
                    "OpenAI API key is required. Configure it in Settings → General or set OPENAI_API_KEY."
                )
            self._model = settings.openai_model
            self._client = AsyncOpenAI(api_key=api_key, timeout=120.0)
            return

        # azure_openai
        api_key = us.get("azure_openai_api_key") or settings.azure_openai_api_key
        if not api_key:
            raise AnalysisLlmConfigError(
                "Azure OpenAI API key is required. Configure it in Settings → General or set AZURE_OPENAI_API_KEY."
            )
        endpoint = us.get("azure_openai_endpoint") or settings.azure_openai_endpoint
        if not endpoint:
            raise AnalysisLlmConfigError(
                "Azure OpenAI endpoint is required. Configure it in Settings → General or set AZURE_OPENAI_ENDPOINT."
            )
        deployment = us.get("azure_openai_deployment") or settings.azure_openai_deployment
        if not deployment:
            raise AnalysisLlmConfigError(
                "Azure OpenAI deployment is required. Configure it in Settings → General or set AZURE_OPENAI_DEPLOYMENT."
            )
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

    @staticmethod
    async def load_project_settings(db: Any, project_id: Any) -> dict:
        """Load a project's settings dict for project-scoped LLM config.

        Returns ``{}`` when no project_id is given or the project is missing,
        which falls back to per-user settings / env in the constructor.
        """
        if project_id is None:
            return {}
        from app.models.project import Project

        project = await db.get(Project, project_id)
        return dict(project.settings or {}) if project else {}

    async def tracked_chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        response_format: Any = None,
    ) -> tuple[str, LlmUsageInfo]:
        """Chat completion that captures and returns usage metadata."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "messages": messages,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        t0 = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except BadRequestError:
            # Some Azure/OpenAI deployments reject the JSON response_format ("The requested
            # operation is unsupported."). Every caller here parses JSON tolerantly (extracting
            # the first object, ignoring fences/prose), so drop the hint and retry once rather
            # than failing the whole call. A genuine 400 (context length, content filter) will
            # simply 400 again and propagate.
            if "response_format" not in kwargs:
                raise
            logger.warning(
                "response_format unsupported by %s deployment; retrying without JSON mode",
                self.provider,
            )
            kwargs.pop("response_format", None)
            response = await self._client.chat.completions.create(**kwargs)
        duration_ms = round((time.monotonic() - t0) * 1000)

        content = response.choices[0].message.content or ""
        usage = response.usage

        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        cached_tokens = 0
        reasoning_tokens = 0
        if usage:
            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0

        # Use the model name from the API response for cost calculation;
        # for Azure, self._model is the deployment name which may not match
        # the pricing table, but response.model contains the actual model.
        cost_model = response.model or self._model
        cost = calculate_cost(cost_model, input_tokens, output_tokens)

        usage_info = LlmUsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
        )
        return content, usage_info

    async def analyze_trace(
        self, trace: dict[str, Any], instructions: str = ""
    ) -> tuple[str, LlmUsageInfo]:
        """Analyze a trace and return (content, usage_info)."""
        trace_json = json.dumps(trace, default=str, indent=2)
        return await self.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior LLM reliability engineer. "
                        "Find likely failure causes and propose concrete fixes."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze this normalized trace and produce:\n"
                        "1) failure type\n2) root cause\n3) suggested fixes\n\n"
                        f"Trace JSON:\n{trace_json}\n\n"
                        f"Extra instructions:\n{instructions or 'None'}"
                    ),
                },
            ],
            temperature=0.2,
        )
