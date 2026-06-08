"""TraceSignal — per-trace behavioral signals classified by the LLM.

Where ``IssueEvidence`` links a trace to an *issue*, ``TraceSignal`` records the
raw behavioral signals (refusal, frustration, task-incomplete, loop) detected on
a single trace. These rows are read by ``engine/signals.py`` and flow into the
existing clustering pipeline like any other signal source.
"""

from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, SignalType


class TraceSignal(Base):
    __tablename__ = "trace_signals"
    __table_args__ = (
        # One row per (trace, signal type) — re-classification updates, not duplicates.
        UniqueConstraint("trace_id", "signal_type", name="uq_trace_signal"),
        Index("idx_trace_signals_trace_id", "trace_id"),
        Index("idx_trace_signals_signal_type", "signal_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    signal_type = Column(Enum(SignalType, name="signal_type"), nullable=False)
    confidence = Column(Float, CheckConstraint("confidence >= 0 AND confidence <= 1"))
    detail = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    trace = relationship("Trace")
