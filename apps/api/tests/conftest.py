"""Shared test fixtures — uses SQLite for isolation, no PostgreSQL needed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from app.auth import create_access_token, hash_password
from app.models.models import Base, Integration, IntegrationType, Span, SpanType, Trace, TraceStatus
from app.models.project import Project
from app.models.user import User
from app.models.chunk_labels import (  # noqa: F401 — register tables for create_all
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)

# ---------------------------------------------------------------------------
# Patch PostgreSQL types to work with SQLite before table creation
# ---------------------------------------------------------------------------
from sqlalchemy.ext.compiler import compiles

@compiles(PG_UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

# ---------------------------------------------------------------------------
# Engine / session using async SQLite
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    # Patch PostgreSQL-specific server defaults so SQLite can create tables.
    from sqlalchemy.schema import DefaultClause

    for table in Base.metadata.tables.values():
        for col in table.columns:
            sd = col.server_default
            if sd is not None and hasattr(sd, "arg") and hasattr(sd.arg, "text"):
                default_text = sd.arg.text
                if default_text == "now()":
                    col.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
                elif default_text.endswith("::jsonb"):
                    col.server_default = DefaultClause(text(default_text.replace("::jsonb", "")))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Override FastAPI deps
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    from app.main import app
    from app.db import get_db

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(id=uuid4(), email="test@example.com", hashed_password=hash_password("testpass123"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
def auth_headers(test_user: User, test_project: Project) -> dict[str, str]:
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession, test_user: User) -> Project:
    project = Project(id=uuid4(), owner_id=test_user.id, name="Default")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_integration(db_session: AsyncSession, test_project: Project) -> Integration:
    integ = Integration(
        id=uuid4(),
        project_id=test_project.id,
        type=IntegrationType.langfuse,
        name="Test Integration",
        api_key=b"fake-encrypted-key",
        base_url="https://example.com",
    )
    db_session.add(integ)
    await db_session.commit()
    await db_session.refresh(integ)
    return integ


@pytest_asyncio.fixture
async def sample_traces_and_spans(db_session: AsyncSession, test_integration: Integration):
    """Create 3 traces each with a chain→llm→tool span hierarchy."""
    traces = []
    for i in range(3):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"ext-trace-{i}",
            name=f"trace-{i}",
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
        db_session.add(t)
        await db_session.flush()

        chain = Span(
            id=uuid4(), trace_id=t.id, name="agent_chain", type=SpanType.chain,
            duration_ms=500 + i * 100, status="ok",
            created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        db_session.add(chain)
        await db_session.flush()

        llm = Span(
            id=uuid4(), trace_id=t.id, parent_span_id=chain.id,
            name="gpt4_call", type=SpanType.llm,
            duration_ms=300 + i * 50, status="ok",
            created_at=datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        db_session.add(llm)

        tool = Span(
            id=uuid4(), trace_id=t.id, parent_span_id=chain.id,
            name="search_tool", type=SpanType.tool,
            duration_ms=100 + i * 20, status="error" if i == 2 else "ok",
            created_at=datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        )
        db_session.add(tool)
        traces.append(t)

    await db_session.commit()
    return traces
