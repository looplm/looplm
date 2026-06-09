"""Tests for trace list pagination — offset (default) and keyset (cursor).

The sample fixture creates 3 traces that share an identical start_time, which
is exactly the case that makes a tiebreaker-less sort non-deterministic — so it
doubles as a guard that keyset paging never drops or repeats a row.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

TRACES_URL = "/api/traces"


@pytest.mark.asyncio
async def test_offset_mode_unchanged(client: AsyncClient, auth_headers, sample_traces_and_spans):
    """Default (no cursor) keeps the offset contract: total + total_pages."""
    resp = await client.get(f"{TRACES_URL}?per_page=2", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["data"]) == 2
    pag = body["pagination"]
    assert pag["total"] == 3
    assert pag["total_pages"] == 2
    # Cursor fields are absent/null in offset mode.
    assert pag.get("next_cursor") is None
    assert pag.get("has_more") is None


@pytest.mark.asyncio
async def test_keyset_pages_through_all_rows_without_dupes(
    client: AsyncClient, auth_headers, sample_traces_and_spans
):
    """Walk the whole list via cursor; every row appears exactly once, in order."""
    seen: list[str] = []
    cursor = ""  # empty cursor => first keyset page
    order: list[str] = []
    for _ in range(10):  # generous upper bound; 3 rows @ per_page=2 => 2 pages
        resp = await client.get(
            f"{TRACES_URL}?per_page=2&cursor={cursor}", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        pag = body["pagination"]
        # Keyset mode does not compute totals.
        assert pag["total"] == 0
        assert pag["total_pages"] == 0
        ids = [row["id"] for row in body["data"]]
        seen.extend(ids)
        order.extend((row["start_time"], row["id"]) for row in body["data"])
        if not pag["has_more"]:
            assert pag["next_cursor"] is None
            break
        assert pag["next_cursor"]
        cursor = pag["next_cursor"]
    else:
        pytest.fail("keyset paging did not terminate")

    # All 3 rows, no duplicates.
    assert len(seen) == 3
    assert len(set(seen)) == 3
    # Stable strict-descending order on (start_time, id) despite equal start_times.
    assert order == sorted(order, reverse=True)


@pytest.mark.asyncio
async def test_keyset_invalid_cursor_rejected(client: AsyncClient, auth_headers):
    resp = await client.get(f"{TRACES_URL}?cursor=not-a-valid-cursor", headers=auth_headers)
    assert resp.status_code == 400
