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
