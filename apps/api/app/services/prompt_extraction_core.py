"""Prompt extraction — shared core: discovery/extraction agent helpers + constants.

Split out of `prompt_extraction_service` to keep each module focused; the pipeline
(`prompt_extraction_service`) and single-prompt maintenance
(`prompt_extraction_maintenance`) both build on the primitives here.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent
from pydantic_ai._agent_graph import CallToolsNode, ModelRequestNode
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.usage import UsageLimits

from app.schemas.prompts import ExtractedPrompt, PromptLocation, PromptLocationList
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_prompts import (
    PROMPT_EXTRACT_ONE_SYSTEM_PROMPT,
)
from app.services.code_agent_tools import RepoContext, grep_files, read_file

logger = logging.getLogger(__name__)

_DISCOVERY_REQUEST_LIMIT = 25
_EXTRACT_ONE_REQUEST_LIMIT = 6
_MAX_PROMPTS = 100  # safety cap on how many locations we extract in one run
# Wall-clock safety net: request limits cap turns but not time. A slow or hung
# model turn would otherwise leave the run "stuck" forever — fail cleanly.
_EXTRACTION_TIMEOUT_SECONDS = 900

_DISCOVERY_PROMPT = (
    "Locate every LLM prompt defined in this repository and return the list of "
    "locations (name, file, line) — do not include the template text yet."
)


def _tokens(usage) -> tuple[int, int]:
    if not usage:
        return 0, 0
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def _describe_activity(node: CallToolsNode) -> tuple[str, str]:
    """Turn a model response into a friendly (progress_message, log_entry).

    The live signal users can see is *what the agent is doing* — which files it
    reads and searches. Phrase those as plain English.
    """
    for part in node.model_response.parts:
        if isinstance(part, ToolCallPart):
            args = part.args_as_dict() if hasattr(part, "args_as_dict") else {}
            if not isinstance(args, dict):
                args = {}
            if part.tool_name == "read_file":
                path = args.get("path") or "a file"
                return f"Reading {path}", f"Read {path}"
            if part.tool_name == "grep_files":
                pattern = (args.get("pattern") or "").strip()
                return (
                    "Searching the code for prompts…",
                    f"Searched for: {pattern}"[:120] if pattern else "Searched the code",
                )
            if part.tool_name == "glob_files":
                pattern = (args.get("pattern") or "").strip()
                return (
                    "Looking for prompt files…",
                    f"Looked for files: {pattern}"[:120] if pattern else "Looked for files",
                )
            return f"Running {part.tool_name}…", part.tool_name
        if isinstance(part, TextPart) and part.content:
            snippet = part.content[:140].replace("\n", " ").strip()
            if snippet:
                return "Analyzing the codebase…", snippet
    return "Analyzing the codebase…", "Analyzing"


def _make_extract_agent(llm_model) -> Agent:
    """Agent that reads one location and returns a single prompt verbatim."""
    return Agent(
        llm_model,
        output_type=ExtractedPrompt,
        system_prompt=PROMPT_EXTRACT_ONE_SYSTEM_PROMPT,
        deps_type=RepoContext,
        tools=(read_file, grep_files),
    )


async def _discover_locations(
    agent: Agent,
    deps: RepoContext,
    usage_limits: UsageLimits,
    *,
    db,
    extraction,
) -> tuple[PromptLocationList | None, object]:
    """Phase 1: locate prompts, streaming tool activity into the progress feed."""
    turn = 0
    async with agent.iter(_DISCOVERY_PROMPT, deps=deps, usage_limits=usage_limits) as ctx:
        async for node in ctx:
            if isinstance(node, ModelRequestNode):
                turn += 1
                await _update_progress(
                    db, extraction,
                    progress_message="Scanning the codebase…" if turn == 1
                    else "Looking for prompts…",
                )
            elif isinstance(node, CallToolsNode):
                progress_msg, log_msg = _describe_activity(node)
                await _update_progress(
                    db, extraction, progress_message=progress_msg, log_entry=log_msg
                )
        output = ctx.result.output if ctx.result else None
        usage = ctx.result.usage if ctx.result else None
    return output, usage


async def _extract_one(
    agent: Agent,
    deps: RepoContext,
    loc: PromptLocation,
    usage_limits: UsageLimits,
) -> tuple[ExtractedPrompt | None, object]:
    """Phase 2: read one location and return the single prompt verbatim."""
    user = (
        f"Extract the prompt named {loc.name!r} defined in {loc.file_path}"
        + (f" around line {loc.line_start}." if loc.line_start else ".")
        + " Return its full template verbatim and its variables."
    )
    result = await agent.run(user, deps=deps, usage_limits=usage_limits)
    return result.output, result.usage


def _loc_ext_id(file_path: str, name: str) -> str:
    return f"{file_path}::{name}"[:512]
