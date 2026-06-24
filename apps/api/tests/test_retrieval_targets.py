"""Tests for the per-project retrieval-metric target endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.retrieval_targets import DEFAULT_TARGETS


@pytest.mark.asyncio
async def test_get_targets_returns_defaults(client: AsyncClient, auth_headers):
    resp = await client.get("/api/pipeline/targets", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == DEFAULT_TARGETS


@pytest.mark.asyncio
async def test_put_targets_persists_and_clamps(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/pipeline/targets",
        headers=auth_headers,
        json={"recall": 0.9, "ndcg": 0.6, "mrr": 5, "hit_rate": -1, "precision": 0.4},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recall"] == 0.9
    assert body["mrr"] == 1.0  # clamped to [0, 1]
    assert body["hit_rate"] == 0.0

    # Persisted across requests.
    again = await client.get("/api/pipeline/targets", headers=auth_headers)
    assert again.json()["recall"] == 0.9
    assert again.json()["ndcg"] == 0.6
