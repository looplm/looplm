"""Route frequency analysis service — analyzes span-level execution patterns."""

from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Integration, Span, Trace
from app.schemas.route_analysis import (
    BottleneckNode,
    BottleneckResponse,
    RouteAnalysisResponse,
    RouteEdge,
    RouteNode,
)

logger = logging.getLogger(__name__)


async def get_route_analysis(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> RouteAnalysisResponse:
    """Analyze route frequencies at span level for LangGraph topology."""
    # Verify ownership
    integration = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.project_id == project_id,
        )
    )
    if not integration.scalar_one_or_none():
        raise ValueError("Integration not found")

    # Get all traces for this integration
    trace_ids_q = select(Trace.id).where(Trace.integration_id == integration_id)

    # Node stats from spans (span-level analysis)
    nodes_q = (
        select(
            Span.name,
            Span.type,
            func.count(Span.id).label("call_count"),
            func.avg(Span.duration_ms).label("avg_latency_ms"),
            func.sum(Span.duration_ms).label("total_duration_ms"),
            func.sum(case((Span.status == "error", 1), else_=0)).label("failure_count"),
        )
        .where(Span.trace_id.in_(trace_ids_q))
        .group_by(Span.name, Span.type)
    )
    node_rows = (await db.execute(nodes_q)).all()

    nodes: list[RouteNode] = []
    node_id_map: dict[str, RouteNode] = {}
    for row in node_rows:
        node_id = f"{row.name or 'unnamed'}::{row.type or 'unknown'}"
        avg_lat = float(row.avg_latency_ms) if row.avg_latency_ms is not None else None
        total_dur = float(row.total_duration_ms) if row.total_duration_ms is not None else 0.0
        error_rate = (row.failure_count / row.call_count) if row.call_count > 0 else 0.0
        node = RouteNode(
            id=node_id,
            name=row.name or "unnamed",
            run_type=str(row.type) if row.type else None,
            call_count=row.call_count,
            avg_latency_ms=round(avg_lat, 1) if avg_lat is not None else None,
            error_rate=round(error_rate, 4),
            total_duration_ms=round(total_dur, 1),
        )
        nodes.append(node)
        node_id_map[node_id] = node

    # Edge frequencies from parent_span_id → child span relationships
    child = Span.__table__.alias("child")
    parent = Span.__table__.alias("parent")

    edges_q = (
        select(
            parent.c.name.label("parent_name"),
            parent.c.type.label("parent_type"),
            child.c.name.label("child_name"),
            child.c.type.label("child_type"),
            func.count().label("frequency"),
            func.avg(child.c.duration_ms).label("avg_latency_ms"),
        )
        .where(
            and_(
                child.c.parent_span_id == parent.c.id,
                child.c.trace_id.in_(trace_ids_q),
                parent.c.trace_id.in_(trace_ids_q),
            )
        )
        .group_by(parent.c.name, parent.c.type, child.c.name, child.c.type)
    )
    edge_rows = (await db.execute(edges_q)).all()

    edges: list[RouteEdge] = []
    for row in edge_rows:
        source = f"{row.parent_name or 'unnamed'}::{row.parent_type or 'unknown'}"
        target = f"{row.child_name or 'unnamed'}::{row.child_type or 'unknown'}"
        if source in node_id_map and target in node_id_map:
            avg_lat = float(row.avg_latency_ms) if row.avg_latency_ms is not None else None
            edges.append(
                RouteEdge(
                    source=source,
                    target=target,
                    frequency=row.frequency,
                    avg_latency_ms=round(avg_lat, 1) if avg_lat is not None else None,
                )
            )

    # Detect sequential edges among sibling spans (same parent_span_id),
    # ordered by start time within the same parent.
    sibling_q = (
        select(
            Span.parent_span_id,
            Span.name,
            Span.type,
            Span.created_at,
        )
        .where(
            and_(
                Span.trace_id.in_(trace_ids_q),
                Span.parent_span_id.isnot(None),
            )
        )
        .order_by(Span.parent_span_id, Span.created_at)
    )
    sibling_rows = (await db.execute(sibling_q)).all()

    # Group by parent and build sequential edges between siblings
    edge_counter: dict[tuple[str, str], int] = defaultdict(int)
    current_parent = None
    prev_node_id = None
    for row in sibling_rows:
        node_id = f"{row.name or 'unnamed'}::{row.type or 'unknown'}"
        if row.parent_span_id != current_parent:
            current_parent = row.parent_span_id
            prev_node_id = node_id
            continue
        if prev_node_id and prev_node_id != node_id:
            edge_counter[(prev_node_id, node_id)] += 1
        prev_node_id = node_id

    # Add sibling sequential edges that aren't already covered by parent-child
    existing_edges = {(e.source, e.target) for e in edges}
    for (src, tgt), freq in edge_counter.items():
        if (src, tgt) not in existing_edges and src in node_id_map and tgt in node_id_map:
            edges.append(RouteEdge(source=src, target=tgt, frequency=freq, avg_latency_ms=None))

    # Root nodes: spans with no parent
    root_q = (
        select(Span.name, Span.type)
        .where(
            Span.trace_id.in_(trace_ids_q),
            Span.parent_span_id.is_(None),
        )
        .group_by(Span.name, Span.type)
    )
    root_rows = (await db.execute(root_q)).all()
    root_ids = [
        f"{r.name or 'unnamed'}::{r.type or 'unknown'}"
        for r in root_rows
        if f"{r.name or 'unnamed'}::{r.type or 'unknown'}" in node_id_map
    ]

    # Calculate edge weights as percentage of total outgoing edges from source
    source_totals: dict[str, int] = defaultdict(int)
    for e in edges:
        source_totals[e.source] += e.frequency
    for e in edges:
        total_from_source = source_totals[e.source]
        if total_from_source > 0:
            e.weight = round(e.frequency / total_from_source, 4)
            e.percentage = round(e.frequency / total_from_source * 100, 2)

    total_q = select(func.count(Trace.id)).where(Trace.integration_id == integration_id)
    total = (await db.execute(total_q)).scalar() or 0

    return RouteAnalysisResponse(
        nodes=nodes, edges=edges, total_traces=total, root_node_ids=root_ids
    )


async def get_bottlenecks(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession,
    limit: int = 10,
) -> BottleneckResponse:
    """Identify bottleneck nodes: high frequency + high latency at span level."""
    route_data = await get_route_analysis(integration_id, project_id, db)

    if not route_data.nodes:
        return BottleneckResponse(total_traces=route_data.total_traces)

    max_latency = max((n.avg_latency_ms or 0) for n in route_data.nodes) or 1
    max_calls = max(n.call_count for n in route_data.nodes) or 1

    bottlenecks: list[BottleneckNode] = []
    for node in route_data.nodes:
        lat = node.avg_latency_ms or 0
        lat_score = lat / max_latency
        freq_score = node.call_count / max_calls
        error_score = node.error_rate
        score = (lat_score * 0.4) + (freq_score * 0.3) + (error_score * 0.3)

        reasons = []
        if lat_score > 0.7:
            reasons.append(f"high latency ({lat:.0f}ms avg)")
        if freq_score > 0.7:
            reasons.append(f"high frequency ({node.call_count} calls)")
        if error_score > 0.1:
            reasons.append(f"high error rate ({node.error_rate:.1%})")

        if reasons:
            bottlenecks.append(
                BottleneckNode(
                    node_id=node.id,
                    name=node.name,
                    run_type=node.run_type,
                    call_count=node.call_count,
                    avg_latency_ms=lat,
                    error_rate=node.error_rate,
                    bottleneck_score=round(score, 4),
                    reason="; ".join(reasons),
                )
            )

    bottlenecks.sort(key=lambda b: b.bottleneck_score, reverse=True)
    return BottleneckResponse(
        bottlenecks=bottlenecks[:limit], total_traces=route_data.total_traces
    )
