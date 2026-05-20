"""GitHub App integration models.

A `GithubInstallation` links one GitHub App installation to one project.
Only the installation_id is sensitive; installation tokens are minted
on-demand (1h TTL) and never persisted.
"""

from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class GithubInstallation(Base):
    __tablename__ = "github_installations"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_github_installations_project_id"),
        Index("idx_github_installations_installation_id", "installation_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id = Column(BigInteger, nullable=False)
    account_login = Column(String(255), nullable=False)
    account_type = Column(String(32), nullable=False, server_default=text("'User'"))
    repo_full_name = Column(String(512), nullable=True)
    repo_default_branch = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
