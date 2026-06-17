"""Eval runner functions — target API calls and evaluator execution.

Extracted from eval_executor.py to keep that module focused on orchestration.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import time

import httpx

from app.models.models import Evaluator, TestCase
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.retrieval_config import extract_retrieved_urls
from app.services.retrieval_metrics import compute_recall_at_k


def _resolve_dot_path(data: Any, path: str) -> Any:
    """Resolve a dot-notation path like 'choices.0.message.content' on a dict/list."""
    for key in path.split("."):
        if data is None:
            return None
        if isinstance(data, list):
            try:
                data = data[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def _render_template(template: Any, variables: dict[str, str]) -> Any:
    """Recursively render {placeholder} strings in a JSON-like structure.

    If a string value is EXACTLY ``{key}`` (no surrounding text), the raw JSON
    value is parsed and returned so that arrays and booleans propagate as their
    native types instead of being embedded as strings.
    """
    if isinstance(template, str):
        stripped = template.strip()
        # Exact match → parse as JSON to preserve native types (arrays, bools)
        if stripped.startswith("{") and stripped.endswith("}") and stripped.count("{") == 1:
            var_name = stripped[1:-1]
            if var_name in variables:
                try:
                    return json.loads(variables[var_name])
                except (json.JSONDecodeError, TypeError):
                    return variables[var_name]
        # Otherwise do string interpolation
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result
    if isinstance(template, dict):
        return {k: _render_template(v, variables) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_template(item, variables) for item in template]
    return template


async def _call_target_api(
    client: httpx.AsyncClient,
    endpoint: str,
    request_template: dict,
    response_path: str,
    extra_headers: dict[str, str],
    prompt: str,
    context_filters: dict | None = None,
    team_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
    filter_enabled: bool = False,
    thread_id: str | None = None,
    metadata: dict | None = None,
    experiment_variables: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Send a prompt to the target API and extract the answer.

    Returns (answer, raw_response, elapsed_ms) where raw_response is the full
    JSON response and elapsed_ms is the round-trip time in milliseconds.
    """
    variables = {"prompt": prompt}
    if thread_id:
        variables["thread_id"] = thread_id
    if context_filters:
        variables["context_filters"] = json.dumps(context_filters)
    if team_filter is not None:
        variables["team_filter"] = json.dumps(team_filter)
    if tag_filter is not None:
        variables["tag_filter"] = json.dumps(tag_filter)
    variables["filter_enabled"] = json.dumps(filter_enabled)
    # Merge arbitrary metadata keys as template variables
    if metadata:
        for key, value in metadata.items():
            if key not in variables:
                variables[key] = json.dumps(value) if not isinstance(value, str) else value
    # Experiment variables take highest precedence (skip known filter keys already resolved)
    if experiment_variables:
        _filter_keys = {"filter_mode", "team_filter", "tag_filter", "filter_enabled"}
        for key, value in experiment_variables.items():
            if key not in _filter_keys:
                variables[key] = value

    body = _render_template(request_template, variables)

    t0 = time.monotonic()
    response = await client.post(
        endpoint,
        json=body,
        headers=extra_headers,
        timeout=120.0,
    )
    response.raise_for_status()
    elapsed_ms = round((time.monotonic() - t0) * 1000)

    result = response.json()
    raw_response = json.dumps(result)
    answer = _resolve_dot_path(result, response_path)
    if answer is None:
        return (raw_response, raw_response, elapsed_ms)
    return (str(answer), raw_response, elapsed_ms)


def render_llm_judge_prompt(
    evaluator: Evaluator,
    input_text: str,
    output_text: str,
    expected_output: str | None,
    context: str | None = None,
) -> list[dict[str, str]] | None:
    """Render the LLM judge prompt messages without calling the API.

    Returns the messages list ready for chat completion, or None if no
    prompt_template is configured.
    """
    config = evaluator.config or {}
    prompt_template = config.get("prompt_template", "")
    if not prompt_template:
        return None

    rendered = prompt_template.replace("{input}", input_text or "")
    rendered = rendered.replace("{output}", output_text or "")
    rendered = rendered.replace("{expected_output}", expected_output or "")
    rendered = rendered.replace("{context}", context or "")

    return [
        {"role": "system", "content": "You are an evaluation judge. Respond ONLY with valid JSON."},
        {"role": "user", "content": rendered},
    ]


def parse_llm_judge_response(content: str) -> dict:
    """Parse an LLM judge response string into a grader result dict.

    Returns {"pass": bool, "reason": str, "skipped": False} on success,
    or a failure dict if the response cannot be parsed.
    """
    json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if json_match:
        parsed = json.loads(json_match.group())
        return {
            "pass": bool(parsed.get("pass", False)),
            "reason": parsed.get("reason", ""),
            "skipped": False,
        }
    return {"pass": False, "reason": f"Could not parse LLM response: {content[:200]}", "skipped": False}


async def _run_llm_judge(
    llm: AnalysisLlmService,
    evaluator: Evaluator,
    input_text: str,
    output_text: str,
    expected_output: str | None,
    context: str | None = None,
) -> tuple[dict, LlmUsageInfo | None]:
    """Run an LLM-judge evaluator and return (grader_result, usage_info)."""
    messages = render_llm_judge_prompt(evaluator, input_text, output_text, expected_output, context)
    if messages is None:
        return {"pass": False, "reason": "No prompt_template configured", "skipped": True}, None

    try:
        content, usage = await asyncio.wait_for(
            llm.tracked_chat_completion(messages=messages, temperature=0.1),
            timeout=180.0,
        )
        return parse_llm_judge_response(content), usage

    except asyncio.TimeoutError:
        return {"pass": False, "reason": "LLM judge timed out after 180s", "skipped": True}, None
    except Exception as e:
        return {"pass": False, "reason": f"LLM judge error: {e}", "skipped": True}, None


def _run_deterministic(
    evaluator: Evaluator,
    output_text: str,
    test_case: TestCase,
    context: str | None = None,
    payload_key: str | None = None,
) -> dict:
    """Run a deterministic evaluator check."""
    config = evaluator.config or {}
    check_type = config.get("check_type", "")

    if check_type == "contains_urls":
        expected_urls = test_case.expected_page_urls or []
        if not expected_urls:
            return {"pass": True, "reason": "No expected URLs to check", "skipped": True}
        # Check against full API response (context) since URLs often appear
        # in source metadata rather than the answer text itself
        search_text = (context or output_text).lower()
        found_urls = [url for url in expected_urls if url.lower() in search_text]
        missing = [url for url in expected_urls if url.lower() not in search_text]
        passed = len(missing) == 0
        reason = "All expected URLs found" if passed else f"Missing URLs: {', '.join(missing)}"
        retrieved = extract_retrieved_urls(context or output_text, payload_key=payload_key)
        details = {
            "found_urls": found_urls,
            "missing_urls": missing,
            "retrieved_urls": retrieved,
        }
        recall = compute_recall_at_k(expected_urls, retrieved)
        if recall is not None:
            details["recall_at_k"] = recall
        return {
            "pass": passed,
            "reason": reason,
            "skipped": False,
            "details": details,
        }

    if check_type == "contains_sources":
        expected_sources = test_case.expected_sources or []
        if not expected_sources:
            return {"pass": True, "reason": "No expected sources to check", "skipped": True}
        search_text = (context or output_text).lower()
        missing = [s for s in expected_sources if s.lower() not in search_text]
        passed = len(missing) == 0
        reason = "All expected sources found" if passed else f"Missing sources: {', '.join(missing)}"
        return {"pass": passed, "reason": reason, "skipped": False}

    if check_type == "regex_match":
        pattern = config.get("pattern", "")
        if not pattern:
            return {"pass": False, "reason": "No regex pattern configured", "skipped": True}
        try:
            match = re.search(pattern, output_text, re.IGNORECASE | re.DOTALL)
            passed = match is not None
            reason = "Regex matched" if passed else f"Regex '{pattern}' did not match"
            return {"pass": passed, "reason": reason, "skipped": False}
        except re.error as e:
            return {"pass": False, "reason": f"Invalid regex: {e}", "skipped": True}

    if check_type == "string_contains":
        expected_strings = config.get("expected_strings", [])
        if isinstance(expected_strings, str):
            expected_strings = [expected_strings]
        if not expected_strings:
            return {"pass": False, "reason": "No expected strings configured", "skipped": True}
        missing = [s for s in expected_strings if s.lower() not in output_text.lower()]
        passed = len(missing) == 0
        reason = "All expected strings found" if passed else f"Missing: {', '.join(missing)}"
        return {"pass": passed, "reason": reason, "skipped": False}

    if check_type == "image_missing":
        # Extract ![alt](IMAGE_X) refs from output
        image_refs = re.findall(r"!\[[^\]]*\]\((IMAGE_\d+)\)", output_text)
        if not image_refs:
            return {"pass": True, "reason": "No image references in output", "skipped": True}
        ctx = context or ""
        missing = [ref for ref in image_refs if ref not in ctx]
        if not missing:
            return {"pass": True, "reason": f"All {len(image_refs)} image ref(s) found in context", "skipped": False}
        return {
            "pass": False,
            "reason": f"{len(missing)} of {len(image_refs)} image ref(s) missing in context: {', '.join(missing)}",
            "skipped": False,
        }

    if check_type == "length_threshold":
        # Use per-test-case max_answer_length if set, otherwise fall back to evaluator config default
        max_len = test_case.max_answer_length or config.get("default_max_length")
        if max_len:
            output_len = len(output_text)
            if output_len <= max_len:
                return {"pass": True, "reason": f"Output length ({output_len} chars) within limit ({max_len})", "skipped": False}
            return {"pass": False, "reason": f"Output length ({output_len} chars) exceeds limit ({max_len})", "skipped": False}
        # No length limit configured — fall through to LLM judge for hybrid evaluators
        return {"pass": False, "reason": "No max_answer_length configured, deferring to LLM", "skipped": False}

    if check_type == "image_ordering":
        # Extract IMAGE_X refs from output, verify ascending numeric order
        image_refs = re.findall(r"!\[[^\]]*\]\((IMAGE_(\d+))\)", output_text)
        if len(image_refs) < 2:
            return {"pass": True, "reason": "Fewer than 2 image references", "skipped": True}
        numbers = [int(num) for _, num in image_refs]
        for i in range(1, len(numbers)):
            if numbers[i] < numbers[i - 1]:
                return {
                    "pass": False,
                    "reason": f"Image ordering violation: IMAGE_{numbers[i-1]} before IMAGE_{numbers[i]}",
                    "skipped": False,
                }
        return {"pass": True, "reason": f"Image ordering correct ({len(numbers)} refs)", "skipped": False}

    if check_type == "response_time":
        elapsed_ms = config.get("_elapsed_ms")
        if elapsed_ms is None:
            return {"pass": False, "reason": "No response time data available", "skipped": True}
        max_ms = config.get("max_response_time_ms", 10000)
        passed = elapsed_ms <= max_ms

        def _fmt_ms(ms: int) -> str:
            return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"

        reason = (
            f"Response time {_fmt_ms(elapsed_ms)} within limit ({_fmt_ms(max_ms)})"
            if passed
            else f"Response time {_fmt_ms(elapsed_ms)} exceeds limit ({_fmt_ms(max_ms)})"
        )
        return {"pass": passed, "reason": reason, "skipped": False}

    return {"pass": False, "reason": f"Unknown check_type: {check_type}", "skipped": True}
