"""Tests for the safe expression DSL used by Code evaluators."""

import pytest

from app.services.safe_expression import ExpressionError, evaluate_bool_expression


def _names(**over):
    base = {
        "input": "What is the capital of France?",
        "output": "The capital of France is Paris.",
        "expected_output": "Paris",
        "context": "France ... capital ... Paris ...",
        "retrieved_urls": ["https://example.com/a", "https://example.com/b"],
        "expected_urls": ["https://example.com/a"],
        "expected_sources": ["Paris"],
    }
    base.update(over)
    return base


def test_substring_and_helpers():
    assert evaluate_bool_expression("contains(output, expected_output)", _names()) is True
    assert evaluate_bool_expression("expected_output in output", _names()) is True
    assert evaluate_bool_expression('"Berlin" in output', _names()) is False


def test_membership_and_comprehension():
    assert evaluate_bool_expression(
        "all(u in retrieved_urls for u in expected_urls)", _names()
    ) is True
    assert evaluate_bool_expression(
        "all(u in retrieved_urls for u in expected_urls)",
        _names(expected_urls=["https://example.com/missing"]),
    ) is False


def test_numeric_and_len():
    assert evaluate_bool_expression("len(output) > 5", _names()) is True
    assert evaluate_bool_expression("len(retrieved_urls) >= 2", _names()) is True


def test_regex_helper():
    assert evaluate_bool_expression(r'matches("cap[it]+al", output)', _names()) is True


def test_empty_expression_raises():
    with pytest.raises(ExpressionError):
        evaluate_bool_expression("   ", _names())


@pytest.mark.parametrize(
    "expr",
    [
        "output.__class__",  # attribute access to dunders is blocked
        "__import__('os')",  # imports are not available
        "().__class__.__bases__",  # sandbox escape attempt
        "open('/etc/passwd')",  # IO not available
    ],
)
def test_dangerous_expressions_blocked(expr):
    with pytest.raises(ExpressionError):
        evaluate_bool_expression(expr, _names())
