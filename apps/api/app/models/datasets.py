"""TestDataset, TestCase, JsonImport, and JsonImportStatus models."""

import enum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base

# Reserved tag marking a negative test case: the query intentionally has no relevant
# documents (e.g. a UI command), so retrieval ground truth must never be attached to it.
NO_RETRIEVAL_TAG = "no-retrieval-expected"


def is_no_retrieval_expected(tags: list | None) -> bool:
    return bool(tags) and NO_RETRIEVAL_TAG in tags


class JsonImportStatus(str, enum.Enum):
    success = "success"
    partial = "partial"
    error = "error"


class TestDataset(Base):
    __tablename__ = "test_datasets"
    __table_args__ = (
        Index("idx_test_datasets_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    tags = Column(JSONB, nullable=False, server_default=text("'[]'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    test_cases = relationship("TestCase", back_populates="dataset", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        Index("idx_test_cases_dataset_id", "dataset_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id = Column(
        UUID(as_uuid=True), ForeignKey("test_datasets.id", ondelete="CASCADE"), nullable=False
    )
    test_id = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    expected_answer = Column(Text)
    expected_sources = Column(JSONB, nullable=False, server_default=text("'[]'"))
    context_filters = Column(JSONB, nullable=False, server_default=text("'{}'"))
    team_filter = Column(JSONB, nullable=False, server_default=text("'[]'"))
    tag_filter = Column(JSONB, nullable=False, server_default=text("'[]'"))
    message_count = Column(Integer)
    has_summary = Column(Boolean, nullable=False, server_default=text("false"))
    folder = Column(String(255))
    document = Column(String(255))
    expected_page_urls = Column(JSONB, nullable=False, server_default=text("'[]'"))
    expected_source_types = Column(JSONB, nullable=False, server_default=text("'[]'"))
    max_answer_length = Column(Integer, nullable=True)
    follow_up_prompts = Column(JSONB, nullable=True)  # [{"prompt": "...", "expected_answer": "..."}]
    source_feedback_id = Column(UUID(as_uuid=True), nullable=True)
    source_trace_id = Column(UUID(as_uuid=True), nullable=True)
    tags = Column(JSONB, nullable=False, server_default=text("'[]'"))
    test_case_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    status = Column(String(32), nullable=False, server_default=text("'active'"))  # active | needs_work
    status_note = Column(Text, nullable=True)
    # Human sign-off: a reviewer confirmed this case is correct. Orthogonal to status;
    # validated_by is stamped server-side from the session, never client-supplied.
    validated = Column(Boolean, nullable=False, server_default=text("false"))
    validated_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    dataset = relationship("TestDataset", back_populates="test_cases")


class DatasetDuplicateDismissal(Base):
    """A user-confirmed 'these two cases are NOT duplicates' record.

    The duplicate scanner excludes any pair present here so a dismissed pair
    stops resurfacing on future scans. ``case_id_a``/``case_id_b`` are stored
    sorted (a < b as strings) so the pair is order-independent. Both FK to
    ``test_cases`` with ``ondelete=CASCADE`` — deleting either case removes the
    stale dismissal automatically.
    """

    __tablename__ = "dataset_duplicate_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "case_id_a", "case_id_b", name="uq_dup_dismissal_pair"
        ),
        Index("idx_dup_dismissal_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    case_id_a = Column(
        UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    case_id_b = Column(
        UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class JsonImport(Base):
    __tablename__ = "json_imports"
    __table_args__ = (
        Index("idx_json_imports_project_id", "project_id"),
        Index("idx_json_imports_created_at", text("created_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_type = Column(String(32), nullable=False)  # traces, feedback, evaluations, datasets, prompts
    filename = Column(String(512), nullable=False)
    record_count = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(
        Enum(JsonImportStatus, name="json_import_status"), nullable=False, server_default=text("'success'")
    )
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
