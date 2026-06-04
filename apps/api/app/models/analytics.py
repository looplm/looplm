"""Analytics models — request-type clustering analysis."""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class RequestClusterAnalysis(Base):
    """Stores results of LLM-based clustering of user requests into intent themes.

    Mirrors ``TopQuestionsAnalysis`` but operates over *all* traffic in a window
    (not just feedback-bearing traces). Each theme in ``results`` carries an
    ``outcome`` cross-tab ({success, degraded, failure, fb_positive, fb_negative})
    that drives the request-type × outcome heatmap.
    """

    __tablename__ = "request_cluster_analyses"
    __table_args__ = (
        Index("idx_request_cluster_analyses_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total_requests = Column(Integer, nullable=False, server_default=text("0"))
    processed_requests = Column(Integer, nullable=False, server_default=text("0"))
    results = Column(JSONB, nullable=True)
    filter_from_date = Column(DateTime(timezone=True), nullable=True)
    filter_to_date = Column(DateTime(timezone=True), nullable=True)
    filter_environment = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
