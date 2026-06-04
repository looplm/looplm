"""GitHub App integration models.

Two records, both scoped to one project:

- `ProjectGithubApp` holds the project's GitHub App *identity* — the App id,
  OAuth client id/secret, and signing private key. These configure the App
  before any OAuth flow can run, so they live separately from the installation.
  `client_secret` and `private_key` are encrypted at the app layer (Fernet).
- `GithubInstallation` links one of that App's installations (and a chosen repo)
  to the project. Only the installation_id is sensitive; installation tokens are
  minted on-demand (1h TTL) and never persisted.

A project with no `ProjectGithubApp` row falls back to the instance-wide App
configured via `GITHUB_APP_*` env settings (see `github_app.resolve_creds`).
"""

from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProjectGithubApp(Base):
    """A project's own GitHub App identity. Secrets are encrypted at rest."""

    __tablename__ = "project_github_apps"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_github_apps_project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_id = Column(String(64), nullable=False)
    app_name = Column(String(255), nullable=True)  # slug used to build install URLs
    client_id = Column(String(255), nullable=False)
    client_secret = Column(LargeBinary, nullable=False)  # encrypted at app layer
    private_key = Column(LargeBinary, nullable=False)  # encrypted PEM
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


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
    repo_default_branch = Column(String(255), nullable=True)  # the repo's own default branch
    repo_branch = Column(String(255), nullable=True)  # the branch chosen to sync (falls back to default)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
