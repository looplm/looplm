"""ProjectMember model for role-based section access control."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.models import Base

ALL_SECTIONS = ["observe", "evaluate", "improve"]

SECTION_PAGES: dict[str, list[str]] = {
    "observe": ["dashboard", "traces", "analytics", "feedback", "costs"],
    "evaluate": ["evaluations", "evaluators", "datasets"],
    "improve": ["advisor", "routes", "prompts"],
}

ALL_PAGES = [page for pages in SECTION_PAGES.values() for page in pages]

PAGE_TO_SECTION: dict[str, str] = {
    page: section for section, pages in SECTION_PAGES.items() for page in pages
}


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False, server_default=text("'member'"))
    allowed_sections = Column(
        JSONB, nullable=False, server_default=text("'[\"observe\",\"evaluate\",\"improve\"]'::jsonb")
    )
    allowed_pages = Column(JSONB, nullable=True, server_default=text("null"))
    write_pages = Column(JSONB, nullable=True, server_default=text("null"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships")
