"""Safe expression evaluation for code evaluators — a DSL, not arbitrary code.

A "Code" evaluator is authored as a single boolean expression over the eval context (the model
input/output, retrieved context, expected answer/URLs). Expressions are evaluated with
``simpleeval``, which forbids imports and attribute access to dunders, caps string/power sizes,
and only allows the whitelisted helper functions below. No file, network, or process access is
reachable. This is the "safe DSL first" step; full sandboxed code execution can come later.
"""

from __future__ import annotations

import re
from typing import Any

from simpleeval import EvalWithCompoundTypes, InvalidExpression


class ExpressionError(Exception):
    """Raised for an empty, malformed, or disallowed expression (surfaced as a skipped check)."""


def _matches(pattern: Any, text: Any) -> bool:
    """Case-insensitive regex search; a bad pattern is a non-match rather than an error."""
    try:
        return re.search(str(pattern), str(text), re.IGNORECASE | re.DOTALL) is not None
    except re.error:
        return False


def _contains(text: Any, sub: Any) -> bool:
    """Case-insensitive substring test."""
    return str(sub).lower() in str(text).lower()


# The only callables an expression may invoke. No attribute access, imports, or IO are possible.
SAFE_FUNCTIONS: dict[str, Any] = {
    "len": len,
    "any": any,
    "all": all,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "lower": lambda x: str(x).lower(),
    "upper": lambda x: str(x).upper(),
    "matches": _matches,
    "contains": _contains,
}

# Variables exposed to an expression, with docs shown in the UI. Keep in sync with
# build_expression_namespace in eval_runners.
EXPRESSION_VARIABLES: list[tuple[str, str]] = [
    ("input", "The test case input / query."),
    ("output", "The model's answer text."),
    ("expected_output", "The expected answer, or an empty string."),
    ("context", "The full retrieved context / API response text."),
    ("retrieved_urls", "List of source URLs the retriever returned."),
    ("expected_urls", "List of ground-truth source URLs for the case."),
    ("expected_sources", "List of expected source strings for the case."),
]


def evaluate_bool_expression(expression: str, names: dict[str, Any]) -> bool:
    """Evaluate a boolean expression against ``names``; raise ExpressionError on any failure."""
    expr = (expression or "").strip()
    if not expr:
        raise ExpressionError("empty expression")
    evaluator = EvalWithCompoundTypes(names=names, functions=dict(SAFE_FUNCTIONS))
    try:
        return bool(evaluator.eval(expr))
    except InvalidExpression as exc:
        raise ExpressionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - report any eval failure as a controlled error
        raise ExpressionError(f"{type(exc).__name__}: {exc}") from exc


# Representative values (right types) used to validate a generated expression parses and only
# uses allowed constructs/variables — a NameError here means a hallucinated variable.
_SAMPLE_NAMESPACE: dict[str, Any] = {
    "input": "What is the capital of France?",
    "output": "The capital of France is Paris.",
    "expected_output": "Paris",
    "context": "France ... capital ... Paris ...",
    "retrieved_urls": ["https://example.com/a", "https://example.com/b"],
    "expected_urls": ["https://example.com/a"],
    "expected_sources": ["Paris"],
}


def validate_expression(expression: str) -> str | None:
    """Return an error string if the expression is empty/malformed/disallowed, else None."""
    try:
        evaluate_bool_expression(expression, dict(_SAMPLE_NAMESPACE))
    except ExpressionError as exc:
        return str(exc)
    return None


def strip_expression(text: str) -> str:
    """Clean an LLM reply down to a bare expression (drop code fences and surrounding quotes)."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        s = re.sub(r"^[A-Za-z]+\n", "", s).strip()  # drop an optional ```python language tag
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        s = s[1:-1].strip()
    return s


def build_generation_system_prompt() -> str:
    """System prompt that constrains an LLM to emit a single DSL boolean expression."""
    vars_doc = "\n".join(f"- {name}: {desc}" for name, desc in EXPRESSION_VARIABLES)
    funcs = ", ".join(sorted(SAFE_FUNCTIONS))
    return (
        "You translate a plain-language description of a retrieval/LLM evaluation check into a "
        "single Python boolean expression for a restricted DSL.\n\n"
        "Available variables:\n"
        f"{vars_doc}\n\n"
        f"Only these helper functions may be called: {funcs}.\n"
        "Rules:\n"
        "- Return ONE boolean expression and nothing else: no assignments, imports, attribute or "
        "method access (no dot access), function definitions, code fences, or explanation.\n"
        "- The expression must evaluate truthy when the check passes.\n"
        "- Prefer the helpers (e.g. contains(output, x), matches(pattern, output)) over method "
        "calls, since attribute access is not allowed. Use only the variables listed above.\n"
        'Example — "the answer mentions all expected sources": '
        "all(contains(output, s) for s in expected_sources)"
    )
