"""Tests for promoting retrieved URLs into a test case's expected_page_urls."""

from __future__ import annotations

import pytest

from app.models.chunk_labels import ChunkGoldLabel, ChunkRelevanceLabel


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
async def test_get_expected_urls_reflects_current_state(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://a.example/1"]
    )

    # Initial state
    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "case-1 [unfiltered]"},  # variant suffix tolerated
    )
    assert resp.status_code == 200
    assert resp.json()["expected_page_urls"] == ["https://a.example/1"]

    # After a promote, GET reflects the merged set
    await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        json={"test_id": "case-1", "urls": ["https://b.example/2"]},
    )
    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "case-1"},
    )
    assert resp.json()["expected_page_urls"] == ["https://a.example/1", "https://b.example/2"]


@pytest.mark.asyncio
async def test_get_expected_urls_unknown_test_id_404(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)
    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "nope"},
    )
    assert resp.status_code == 404


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


# --- Sync from chunk labels ---


async def _add_label(
    db_session,
    project,
    user,
    *,
    test_id: str,
    chunk_id: str,
    relevance: int,
    url: str | None,
    annotator: str | None = None,
):
    db_session.add(
        ChunkRelevanceLabel(
            project_id=project.id,
            test_id=test_id,
            chunk_id=chunk_id,
            relevance=relevance,
            url=url,
            labeled_by=None if annotator else user.id,
            annotator=annotator,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_sync_replace_recomputes_from_labels(
    client, auth_headers, db_session, test_project, test_user
):
    """Replace discards the manual list and rebuilds it from gold-relevant labels,
    ordered by grade descending; irrelevant chunks and duplicate URLs are excluded."""
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://stale.example/old"]
    )
    for chunk_id, relevance, url in [
        ("c-high", 3, "https://a.example/high"),
        ("c-low", 1, "https://b.example/low"),
        ("c-irrelevant", 0, "https://c.example/ignored"),
        ("c-dup", 2, "https://b.example/low"),  # same URL, higher grade — one entry, grade 2 wins
        ("c-no-url", 3, None),
    ]:
        await _add_label(
            db_session, test_project, test_user,
            test_id="case-1", chunk_id=chunk_id, relevance=relevance, url=url,
        )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "replace"
    assert len(data["updated"]) == 1
    case = data["updated"][0]
    assert case["expected_page_urls"] == ["https://a.example/high", "https://b.example/low"]
    assert case["added"] == 2
    assert case["removed"] == 1  # the stale manual URL is gone

    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "case-1"},
    )
    assert resp.json()["expected_page_urls"] == [
        "https://a.example/high",
        "https://b.example/low",
    ]


@pytest.mark.asyncio
async def test_sync_merge_appends_only_missing_urls(
    client, auth_headers, db_session, test_project, test_user
):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://a.example/kept"]
    )
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-1", chunk_id="c1", relevance=2, url="https://a.example/kept",
    )
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-1", chunk_id="c2", relevance=3, url="https://b.example/new",
    )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "merge"},
    )
    assert resp.status_code == 200
    case = resp.json()["updated"][0]
    assert case["expected_page_urls"] == ["https://a.example/kept", "https://b.example/new"]
    assert case["added"] == 1
    assert case["removed"] == 0


@pytest.mark.asyncio
async def test_sync_gold_override_wins_over_vote(
    client, auth_headers, db_session, test_project, test_user
):
    """A chunk voted irrelevant but adjudicated relevant lands in the expected set."""
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-1", chunk_id="c1", relevance=0, url="https://a.example/adjudicated",
    )
    db_session.add(
        ChunkGoldLabel(
            project_id=test_project.id, test_id="case-1", chunk_id="c1", relevance=2
        )
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "replace"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"][0]["expected_page_urls"] == ["https://a.example/adjudicated"]


@pytest.mark.asyncio
async def test_sync_ai_labels_excluded_from_human_gold(
    client, auth_headers, db_session, test_project, test_user
):
    """AI-judge labels don't count under the default gold_source=human, but do under ai."""
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-1", chunk_id="c1", relevance=3, url="https://a.example/ai-only",
        annotator="AI",
    )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "replace"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "NO_LABELED_URLS"

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "replace", "gold_source": "ai"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"][0]["expected_page_urls"] == ["https://a.example/ai-only"]


@pytest.mark.asyncio
async def test_sync_dataset_wide_skips_unlabeled_cases(
    client, auth_headers, db_session, test_project, test_user
):
    """Without a test_id every labeled case syncs; cases without labels keep their URLs."""
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, test_id="labeled", expected_page_urls=["https://old.example"]
    )
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={
            "test_id": "unlabeled",
            "prompt": "What is Y?",
            "expected_page_urls": ["https://manual.example/keep"],
        },
    )
    assert resp.status_code == 201
    await _add_label(
        db_session, test_project, test_user,
        test_id="labeled", chunk_id="c1", relevance=2, url="https://a.example/from-label",
    )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert [c["test_id"] for c in data["updated"]] == ["labeled"]
    assert data["skipped"] == ["unlabeled"]

    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "unlabeled"},
    )
    assert resp.json()["expected_page_urls"] == ["https://manual.example/keep"]


@pytest.mark.asyncio
async def test_sync_already_in_sync_reports_unchanged(
    client, auth_headers, db_session, test_project, test_user
):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://a.example/1"]
    )
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-1", chunk_id="c1", relevance=2, url="https://a.example/1",
    )

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "case-1", "mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == []
    assert data["unchanged"] == ["case-1"]


@pytest.mark.asyncio
async def test_sync_all_datasets_one_click(
    client, auth_headers, db_session, test_project, test_user
):
    """The project-wide sync applies to every dataset and groups the outcome per dataset."""
    ds_a, _ = await _create_dataset_with_case(
        client, auth_headers, test_id="case-a", expected_page_urls=["https://old.example/a"]
    )
    resp = await client.post(
        "/api/datasets", headers=auth_headers, json={"name": "Second Dataset"}
    )
    ds_b = resp.json()["id"]
    resp = await client.post(
        f"/api/datasets/{ds_b}/cases",
        headers=auth_headers,
        json={"test_id": "case-b", "prompt": "What is B?"},
    )
    assert resp.status_code == 201
    resp = await client.post(
        f"/api/datasets/{ds_b}/cases",
        headers=auth_headers,
        json={
            "test_id": "case-unlabeled",
            "prompt": "What is C?",
            "expected_page_urls": ["https://manual.example/keep"],
        },
    )
    assert resp.status_code == 201

    await _add_label(
        db_session, test_project, test_user,
        test_id="case-a", chunk_id="c1", relevance=2, url="https://a.example/1",
    )
    await _add_label(
        db_session, test_project, test_user,
        test_id="case-b", chunk_id="c2", relevance=3, url="https://b.example/2",
    )

    resp = await client.post(
        "/api/datasets/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_updated"] == 2
    assert data["total_skipped"] == 1
    assert data["total_unchanged"] == 0

    by_id = {d["dataset_id"]: d for d in data["datasets"]}
    assert by_id[ds_a]["updated"][0]["expected_page_urls"] == ["https://a.example/1"]
    assert [c["test_id"] for c in by_id[ds_b]["updated"]] == ["case-b"]
    assert by_id[ds_b]["skipped"] == ["case-unlabeled"]

    # The unlabeled case kept its manual URLs even in replace mode.
    resp = await client.get(
        f"/api/datasets/{ds_b}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "case-unlabeled"},
    )
    assert resp.json()["expected_page_urls"] == ["https://manual.example/keep"]


@pytest.mark.asyncio
async def test_sync_unknown_test_id_404(client, auth_headers):
    dataset_id, _ = await _create_dataset_with_case(client, auth_headers)
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"test_id": "nope", "mode": "replace"},
    )
    assert resp.status_code == 404
