"""Tests for the first-party tracing ingest endpoint and key management."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_ingest_key
from app.models.models import IngestKey, Integration, IntegrationType, Span, Trace
from app.models.project import Project

INGEST_URL = "/api/v1/ingest/traces"


@pytest_asyncio.fixture
async def looplm_integration(db_session: AsyncSession, test_project: Project) -> Integration:
    integ = Integration(
        id=uuid4(),
        project_id=test_project.id,
        type=IntegrationType.looplm,
        name="My App Tracing",
        api_key=b"placeholder",
    )
    db_session.add(integ)
    await db_session.commit()
    await db_session.refresh(integ)
    return integ


@pytest_asyncio.fixture
async def ingest_key(db_session: AsyncSession, looplm_integration: Integration) -> str:
    """Create an ingest key and return its plaintext (Authorization value)."""
    plaintext, key_hash, key_prefix = generate_ingest_key()
    key = IngestKey(
        id=uuid4(),
        integration_id=looplm_integration.id,
        name="default",
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db_session.add(key)
    await db_session.commit()
    return plaintext


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ── Ingest happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_persists_trace_and_spans(client, db_session, looplm_integration, ingest_key):
    payload = {
        "traces": [
            {
                "external_id": "trace-1",
                "name": "chat",
                "start_time": "2026-06-03T10:00:00Z",
                "end_time": "2026-06-03T10:00:02Z",
                "status": "success",
                "spans": [
                    {"external_id": "s1", "name": "agent", "type": "chain"},
                    {
                        "external_id": "s2",
                        "name": "gpt",
                        "type": "llm",
                        "model": "gpt-4o",
                        "input_tokens": 120,
                        "output_tokens": 80,
                        "parent_external_id": "s1",
                    },
                ],
            }
        ]
    }
    resp = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["accepted"] == 1
    assert len(body["trace_ids"]) == 1

    trace = (
        await db_session.execute(
            select(Trace).where(Trace.external_id == "trace-1")
        )
    ).scalar_one()
    assert trace.name == "chat"
    assert trace.duration_ms == 2000  # derived from start/end

    spans = (
        await db_session.execute(select(Span).where(Span.trace_id == trace.id))
    ).scalars().all()
    assert len(spans) == 2
    by_name = {s.name: s for s in spans}
    assert by_name["gpt"].tokens_in == 120
    assert by_name["gpt"].tokens_out == 80
    assert by_name["gpt"].model == "gpt-4o"
    # parent_external_id resolved to the chain span's internal id
    assert by_name["gpt"].parent_span_id == by_name["agent"].id

    # last_received_at updated
    refreshed = (
        await db_session.execute(
            select(Integration).where(Integration.id == looplm_integration.id)
        )
    ).scalar_one()
    assert refreshed.last_received_at is not None


@pytest.mark.asyncio
async def test_ingest_is_idempotent(client, db_session, ingest_key):
    payload = {"traces": [{"external_id": "dup-1", "name": "v1", "start_time": "2026-06-03T10:00:00Z"}]}
    r1 = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert r1.status_code == 201
    r2 = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert r2.status_code == 201

    traces = (
        await db_session.execute(select(Trace).where(Trace.external_id == "dup-1"))
    ).scalars().all()
    assert len(traces) == 1  # no duplicate row


@pytest.mark.asyncio
async def test_ingest_generates_ids_when_missing(client, db_session, ingest_key):
    payload = {"traces": [{"name": "anon", "spans": [{"type": "llm"}]}]}
    resp = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert resp.status_code == 201
    assert len(resp.json()["trace_ids"]) == 1


# ── Auth ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_rejects_missing_key(client):
    resp = await client.post(INGEST_URL, json={"traces": [{"name": "x"}]})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_key(client, ingest_key):
    resp = await client.post(
        INGEST_URL, json={"traces": [{"name": "x"}]}, headers=_headers("llm_sk_bogus")
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_rejects_non_prefixed_key(client):
    resp = await client.post(
        INGEST_URL, json={"traces": [{"name": "x"}]}, headers=_headers("not-a-looplm-key")
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_rejects_revoked_key(client, db_session, looplm_integration):
    from datetime import datetime, timezone

    plaintext, key_hash, key_prefix = generate_ingest_key()
    key = IngestKey(
        id=uuid4(),
        integration_id=looplm_integration.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        revoked_at=datetime.now(timezone.utc),
    )
    db_session.add(key)
    await db_session.commit()

    resp = await client.post(
        INGEST_URL, json={"traces": [{"name": "x"}]}, headers=_headers(plaintext)
    )
    assert resp.status_code == 401


# ── Limits ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_rejects_oversized_batch(client, ingest_key, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ingest_max_batch", 2)
    payload = {"traces": [{"name": f"t{i}"} for i in range(3)]}
    resp = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_ingest_rejects_too_many_spans(client, ingest_key, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ingest_max_spans_per_trace", 1)
    payload = {"traces": [{"name": "t", "spans": [{"type": "llm"}, {"type": "tool"}]}]}
    resp = await client.post(INGEST_URL, json=payload, headers=_headers(ingest_key))
    assert resp.status_code == 413


# ── Key management endpoints ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_list_revoke_ingest_key(client, looplm_integration, auth_headers):
    base = f"/api/integrations/{looplm_integration.id}/ingest-keys"

    # create
    resp = await client.post(base, json={"name": "ci"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["key"].startswith("llm_sk_")  # plaintext returned once
    assert created["name"] == "ci"
    key_id = created["id"]

    # list (no plaintext field)
    resp = await client.get(base, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert "key" not in data[0]
    assert data[0]["key_prefix"].startswith("llm_sk_")

    # revoke
    resp = await client.delete(f"{base}/{key_id}", headers=auth_headers)
    assert resp.status_code == 204

    # the revoked key no longer authorizes ingest
    plaintext = created["key"]
    resp = await client.post(INGEST_URL, json={"traces": [{"name": "x"}]}, headers=_headers(plaintext))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_keys_rejected_for_non_looplm_integration(
    client, test_integration, auth_headers
):
    # test_integration is a langfuse integration → keys not allowed
    base = f"/api/integrations/{test_integration.id}/ingest-keys"
    resp = await client.post(base, json={"name": "x"}, headers=auth_headers)
    assert resp.status_code == 400
