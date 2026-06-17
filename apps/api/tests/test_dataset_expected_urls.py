"""Tests for promoting retrieved URLs into a test case's expected_page_urls."""

from __future__ import annotations

import pytest


async def _create_dataset_with_case(
    client, auth_headers, *, test_id: str = "case-1", expected_page_urls: list[str] | None = None
) -> tuple[str, str]:
    """Helper: create a dataset with one test case, return (dataset_id, case_id)."""
    resp = await client.post(
        "/api/datasets", headers=auth_headers, json={"name": "Expected URLs Dataset"}
    )
    assert resp.status_code == 201
    dataset_id = resp.json()["id"]

    body: dict = {"test_id": test_id, "prompt": "What is X?"}
    if expected_page_urls is not None:
        body["expected_page_urls"] = expected_page_urls
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases", headers=auth_headers, json=body
    )
    assert resp.status_code == 201
    return dataset_id, resp.json()["id"]


@pytest.mark.asyncio
async def test_add_expected_urls_merges_and_dedupes(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://a.example/1"]
    )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        json={
            "test_id": "case-1",
            # one duplicate, one new, one new — duplicate is dropped, order preserved
            "urls": ["https://a.example/1", "https://b.example/2", "https://c.example/3"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["expected_page_urls"] == [
        "https://a.example/1",
        "https://b.example/2",
        "https://c.example/3",
    ]


@pytest.mark.asyncio
async def test_add_expected_urls_strips_variant_suffix(client, auth_headers):
    """The executor stores eval results under a `[filtered]` suffixed test_id."""
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers, test_id="case-1")

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        json={"test_id": "case-1 [filtered]", "urls": ["https://x.example/page"]},
    )
    assert resp.status_code == 200
    assert resp.json()["expected_page_urls"] == ["https://x.example/page"]


@pytest.mark.asyncio
async def test_add_expected_urls_unknown_test_id_404(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        json={"test_id": "does-not-exist", "urls": ["https://x.example"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_expected_urls_requires_at_least_one_url(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        json={"test_id": "case-1", "urls": []},
    )
    assert resp.status_code == 422
