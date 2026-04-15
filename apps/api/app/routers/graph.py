"""Aggregate execution graph endpoint."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.models.models import Integration, Trace
from app.models.project import Project
from app.schemas.graph import AggregateGraphEdge, AggregateGraphNode, AggregateGraphResponse

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _make_node_id(name: str | None, run_type: str | None) -> str:
    return f"{name or 'unnamed'}::{run_type or 'unknown'}"


@router.get("/aggregate", response_model=AggregateGraphResponse)
async def get_aggregate_graph(
    integration_id: UUID | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Build an aggregate execution graph showing execution patterns across traces."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Base conditions scoped to project's integrations
    conditions = [Trace.integration_id.in_(project_integration_ids)]
    if integration_id:
        conditions.append(Trace.integration_id == integration_id)
    if start_after:
        conditions.append(Trace.start_time > start_after)
    if start_before:
        conditions.append(Trace.start_time < start_before)

    # --- Nodes: GROUP BY name, run_type ---
    nodes_q = (
        select(
            Trace.name,
            Trace.run_type,
            func.count(Trace.id).label("execution_count"),
            func.avg(Trace.duration_ms).label("avg_duration_ms"),
            func.sum(
                case((Trace.status == "failure", 1), else_=0)
            ).label("failure_count"),
            func.sum(
                case((Trace.status == "success", 1), else_=0)
            ).label("success_count"),
        )
        .where(*conditions)
        .group_by(Trace.name, Trace.run_type)
    )
    nodes_result = await db.execute(nodes_q)
    node_rows = nodes_result.all()

    nodes: list[AggregateGraphNode] = []
    node_id_set: set[str] = set()
    for row in node_rows:
        node_id = _make_node_id(row.name, row.run_type)
        node_id_set.add(node_id)
        avg_dur = float(row.avg_duration_ms) if row.avg_duration_ms is not None else None
        nodes.append(
            AggregateGraphNode(
                id=node_id,
                name=row.name or "unnamed",
                run_type=row.run_type,
                execution_count=row.execution_count,
                avg_duration_ms=round(avg_dur, 1) if avg_dur is not None else None,
                failure_count=row.failure_count or 0,
                success_count=row.success_count or 0,
            )
        )

    # --- Edges: self-join on parent_trace_id ---
    child = Trace.__table__.alias("child")
    parent = Trace.__table__.alias("parent")

    edge_conditions = [
        child.c.parent_trace_id == parent.c.id,
        child.c.integration_id.in_(project_integration_ids),
        parent.c.integration_id.in_(project_integration_ids),
    ]
    if integration_id:
        edge_conditions.append(child.c.integration_id == integration_id)
        edge_conditions.append(parent.c.integration_id == integration_id)
    if start_after:
        edge_conditions.append(child.c.start_time > start_after)
    if start_before:
        edge_conditions.append(child.c.start_time < start_before)

    edges_q = (
        select(
            parent.c.name.label("parent_name"),
            parent.c.run_type.label("parent_run_type"),
            child.c.name.label("child_name"),
            child.c.run_type.label("child_run_type"),
            func.count().label("weight"),
        )
        .where(and_(*edge_conditions))
        .group_by(
            parent.c.name,
            parent.c.run_type,
            child.c.name,
            child.c.run_type,
        )
    )
    edges_result = await db.execute(edges_q)
    edge_rows = edges_result.all()

    edges: list[AggregateGraphEdge] = []
    for row in edge_rows:
        source = _make_node_id(row.parent_name, row.parent_run_type)
        target = _make_node_id(row.child_name, row.child_run_type)
        if source in node_id_set and target in node_id_set:
            edges.append(
                AggregateGraphEdge(source=source, target=target, weight=row.weight)
            )

    # --- Root nodes: traces with no parent ---
    root_conditions = [*conditions, Trace.parent_trace_id.is_(None)]
    roots_q = (
        select(Trace.name, Trace.run_type)
        .where(*root_conditions)
        .group_by(Trace.name, Trace.run_type)
    )
    roots_result = await db.execute(roots_q)
    root_node_ids = [
        _make_node_id(row.name, row.run_type)
        for row in roots_result.all()
        if _make_node_id(row.name, row.run_type) in node_id_set
    ]

    # --- Total traces analyzed ---
    total_q = select(func.count(Trace.id)).where(*conditions)
    total = (await db.execute(total_q)).scalar() or 0

    return AggregateGraphResponse(
        nodes=nodes,
        edges=edges,
        total_traces_analyzed=total,
        root_node_ids=root_node_ids,
    )
