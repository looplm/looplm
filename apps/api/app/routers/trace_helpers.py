"""Pure helper/utility functions for trace endpoints."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_

from app.models.models import Span
from app.schemas.traces import SpanResponse, TraceTreeNode


def _parse_multi(value: str | None) -> list[str]:
    """Split comma-separated string into list, stripping whitespace."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _wildcard_to_like(value: str) -> str:
    """Convert user wildcard pattern (using *) to SQL LIKE pattern.

    Escapes existing SQL wildcards (% and _) then replaces * with %.
    """
    value = value.replace("%", r"\%").replace("_", r"\_")
    return value.replace("*", "%")


def _has_wildcard(value: str) -> bool:
    return "*" in value


def _multi_filter(column, values: list[str], mode: str, *, ilike: bool = False):
    """Build an IN/NOT IN or ILIKE/NOT ILIKE filter for multi-value params.

    Supports wildcard patterns using * (e.g. "eval-*" matches "eval-foo").
    When any value contains *, it is matched with ILIKE instead of exact =.
    """
    if not values:
        return None

    # Separate exact values from wildcard patterns
    exact = [v for v in values if not _has_wildcard(v)]
    wildcards = [v for v in values if _has_wildcard(v)]

    if ilike:
        # ilike mode: all values are already wrapped in %...%
        patterns = [column.ilike(f"%{_wildcard_to_like(v)}%") for v in values]
        combined = or_(*patterns)
        return ~combined if mode == "exclude" else combined

    # Build clauses for exact + wildcard values
    clauses = []
    if exact:
        clauses.append(column.in_(exact))
    for w in wildcards:
        clauses.append(column.ilike(_wildcard_to_like(w)))

    combined = or_(*clauses) if len(clauses) > 1 else clauses[0]
    return ~combined if mode == "exclude" else combined


def _build_span_tree(spans: list[Span]) -> list[SpanResponse]:
    """Build nested span tree from flat list."""
    span_map: dict[UUID, SpanResponse] = {}
    roots: list[SpanResponse] = []

    for s in spans:
        resp = SpanResponse(
            id=s.id,
            parent_span_id=s.parent_span_id,
            external_id=s.external_id,
            name=s.name,
            type=s.type.value if s.type else None,
            input=s.input,
            output=s.output,
            model=s.model,
            tokens_in=s.tokens_in,
            tokens_out=s.tokens_out,
            duration_ms=s.duration_ms,
            status=s.status,
            error_message=s.error_message,
        )
        span_map[s.id] = resp

    for s in spans:
        resp = span_map[s.id]
        if s.parent_span_id and s.parent_span_id in span_map:
            span_map[s.parent_span_id].children.append(resp)
        else:
            roots.append(resp)

    return roots


def _build_trace_tree(traces, root_id: UUID) -> TraceTreeNode:
    """Build a nested trace tree from flat list of child traces."""
    node_map: dict[UUID, TraceTreeNode] = {}

    # Create the root node placeholder
    root_node = TraceTreeNode(
        id=root_id,
        name="root",
        run_type=None,
        status=None,
        duration_ms=None,
        start_time=datetime.min,
    )
    node_map[root_id] = root_node

    # Create nodes for all children
    for t in traces:
        node = TraceTreeNode(
            id=t.id,
            name=t.name,
            run_type=t.run_type,
            status=t.status.value if t.status else None,
            duration_ms=t.duration_ms,
            start_time=t.start_time,
            end_time=t.end_time,
            error_message=t.error_message,
        )
        node_map[t.id] = node

    # Link children to parents
    for t in traces:
        node = node_map[t.id]
        parent_id = t.parent_trace_id or root_id
        if parent_id in node_map:
            node_map[parent_id].children.append(node)
        else:
            root_node.children.append(node)

    return root_node
