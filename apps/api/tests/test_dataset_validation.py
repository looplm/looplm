"""Tests for the test-case validation sign-off flow (validated + validator attribution)."""

from __future__ import annotations

import pytest


async def _create_dataset_with_case(client, auth_headers) -> tuple[str, str]:
    """Create a dataset with one test case, return (dataset_id, case_id)."""
    resp = await client.post(
        "/api/datasets",
        headers=auth_headers,
        json={"name": "Validation Test Dataset"},
    )
    assert resp.status_code == 201
    dataset_id = resp.json()["id"]

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={"test_id": "case-1", "prompt": "What is X?"},
    )
    assert resp.status_code == 201
    return dataset_id, resp.json()["id"]


@pytest.mark.asyncio
async def test_validate_and_unvalidate(client, auth_headers):
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)

    # New cases start unvalidated
    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    case = detail["test_cases"][0]
    assert case["validated"] is False
    assert case["validated_at"] is None
    assert case["validated_by_email"] is None
    assert detail["validated_count"] == 0

    # Validate: the endpoint stamps the current user (email local part) server-side
    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"validated": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validated"] is True
    assert body["validated_at"] is not None
    assert body["validated_by_email"] == "test"  # from test@example.com

    # Count reflected on the dataset detail
    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    assert detail["validated_count"] == 1
    assert detail["test_cases"][0]["validated_by_email"] == "test"

    # Un-validate clears attribution and timestamp
    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"validated": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validated"] is False
    assert body["validated_at"] is None
    assert body["validated_by_email"] is None

    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    assert detail["validated_count"] == 0


@pytest.mark.asyncio
async def test_validated_is_client_supplied_identity_ignored(client, auth_headers):
    """A client cannot spoof the validator: only the boolean is honored, id is server-stamped."""
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)

    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        # validated_by / validated_at are not accepted fields; only `validated` matters.
        json={"validated": True, "validated_by": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 200
    assert resp.json()["validated_by_email"] == "test"


@pytest.mark.asyncio
async def test_validation_orthogonal_to_status(client, auth_headers):
    """Validating does not change status; needs_work and validated coexist."""
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)

    await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"validated": True},
    )
    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "needs_work", "status_note": "still verifying"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_work"
    assert body["validated"] is True
    assert body["validated_by_email"] == "test"

    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    assert detail["needs_work_count"] == 1
    assert detail["validated_count"] == 1
