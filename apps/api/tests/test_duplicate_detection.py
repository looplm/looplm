"""Tests for cross-dataset duplicate-question detection."""

from __future__ import annotations

import pytest

from app.services.duplicate_detection import (
    find_duplicate_groups,
    normalize_prompt,
    similarity,
)


def _case(cid: str, dataset_id: str, prompt: str, **kw) -> dict:
    return {
        "id": cid,
        "dataset_id": dataset_id,
        "dataset_name": kw.get("dataset_name", dataset_id),
        "test_id": kw.get("test_id", cid),
        "prompt": prompt,
        "expected_answer": kw.get("expected_answer"),
        "status": kw.get("status", "active"),
    }


# --- Pure similarity helpers ---------------------------------------------

def test_normalize_prompt_collapses_and_strips():
    assert normalize_prompt("  Wie   geht das? ") == normalize_prompt("wie geht das")
    assert normalize_prompt(None) == ""


def test_similarity_bounds():
    a = normalize_prompt("Wie stoße ich den Massennachrichtenversand an")
    assert similarity(a, a) == 1.0
    assert similarity(a, "") == 0.0
    lo = similarity(
        normalize_prompt("Wie archiviere ich eine PARTIN"),
        normalize_prompt("Welche Felder beim Anlegen eines Marktteilnehmers"),
    )
    assert lo < 0.3


# --- Grouping -------------------------------------------------------------

def test_exact_duplicates_grouped_across_datasets():
    cases = [
        _case("a", "d1", "Wie stoße ich den Massennachrichtenversand an?"),
        _case("b", "d2", "wie stoße ich den massennachrichtenversand an"),
        _case("c", "d1", "Wie archiviere ich eine PARTIN in kVASy?"),
    ]
    groups = find_duplicate_groups(cases, threshold=0.8, scope="all")
    assert len(groups) == 1
    g = groups[0]
    assert g["match_type"] == "exact"
    assert {m["case_id"] for m in g["members"]} == {"a", "b"}


def test_near_duplicates_flagged_and_typed_near():
    cases = [
        _case("a", "d1", "Ich mache gerade einen Bilanzkreiswechsel. Wo begrenze ich den alten"),
        _case("b", "d1", "Ich mache gerade einen Bilanzkreiswechsel. Wo begrenze ich den alten Vertrag"),
    ]
    groups = find_duplicate_groups(cases, threshold=0.8, scope="all")
    assert len(groups) == 1
    assert groups[0]["match_type"] == "near"
    assert 0.8 <= groups[0]["score"] < 1.0


def test_threshold_excludes_loose_matches():
    cases = [
        _case("a", "d1", "Wie lege ich einen neuen Marktpartner an"),
        _case("b", "d1", "Wie kündige ich einen Vertrag beim Marktpartner"),
    ]
    assert find_duplicate_groups(cases, threshold=0.9, scope="all") == []


def test_dismissed_pair_excluded():
    from app.services.duplicate_detection import _pair_key

    cases = [
        _case("a", "d1", "Wie geht das genau?"),
        _case("b", "d2", "wie geht das genau"),
    ]
    assert len(find_duplicate_groups(cases, threshold=0.8, scope="all")) == 1
    dismissed = {_pair_key("a", "b")}
    assert find_duplicate_groups(cases, threshold=0.8, scope="all", dismissed_pairs=dismissed) == []


def test_within_dataset_scope_ignores_cross_dataset_pairs():
    cases = [
        _case("a", "d1", "Wie geht das genau?"),
        _case("b", "d2", "wie geht das genau"),
    ]
    assert find_duplicate_groups(cases, threshold=0.8, scope="within_dataset") == []
    cases.append(_case("c", "d1", "Wie geht das genau!"))
    groups = find_duplicate_groups(cases, threshold=0.8, scope="within_dataset")
    assert len(groups) == 1
    assert {m["case_id"] for m in groups[0]["members"]} == {"a", "c"}


def test_transitive_cluster_merges_three():
    cases = [
        _case("a", "d1", "Wie stoße ich den Massennachrichtenversand an?"),
        _case("b", "d2", "Wie stoße ich den Massennachrichtenversand an?"),
        _case("c", "d3", "wie stoße ich den massennachrichtenversand an"),
    ]
    groups = find_duplicate_groups(cases, threshold=0.8, scope="all")
    assert len(groups) == 1
    assert len(groups[0]["members"]) == 3


# --- API endpoints --------------------------------------------------------

async def _make_dataset(client, auth_headers, name: str) -> str:
    resp = await client.post("/api/datasets", headers=auth_headers, json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _add_case(client, auth_headers, dataset_id: str, test_id: str, prompt: str, **body) -> str:
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={"test_id": test_id, "prompt": prompt, **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_duplicates_endpoint_finds_cross_dataset(client, auth_headers):
    d1 = await _make_dataset(client, auth_headers, "DS one")
    d2 = await _make_dataset(client, auth_headers, "DS two")
    await _add_case(client, auth_headers, d1, "img-mnv", "Wie stoße ich den Massennachrichtenversand an?")
    await _add_case(client, auth_headers, d2, "mnv-gpm", "wie stoße ich den massennachrichtenversand an")
    await _add_case(client, auth_headers, d1, "partin", "Wie archiviere ich eine PARTIN?")

    resp = await client.get("/api/datasets/duplicates", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cases"] == 3
    assert len(data["groups"]) == 1
    assert data["duplicate_cases"] == 2
    assert data["groups"][0]["match_type"] == "exact"


@pytest.mark.asyncio
async def test_merge_unions_fields_and_deletes_others(client, auth_headers):
    d1 = await _make_dataset(client, auth_headers, "Merge DS")
    keep = await _add_case(
        client, auth_headers, d1, "keep", "Wie geht das genau?",
        expected_sources=["https://a.example"], tags=["x"],
    )
    other = await _add_case(
        client, auth_headers, d1, "other", "wie geht das genau",
        expected_answer="Antwort", expected_sources=["https://b.example"], tags=["y"],
    )

    resp = await client.post(
        "/api/datasets/duplicates/merge",
        headers=auth_headers,
        json={"keep_case_id": keep, "merge_case_ids": [other]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    assert merged["id"] == keep
    assert merged["expected_answer"] == "Antwort"  # backfilled from other
    assert set(merged["expected_sources"]) == {"https://a.example", "https://b.example"}
    assert set(merged["tags"]) == {"x", "y"}

    # The merged case is gone; only "keep" remains.
    detail = (await client.get(f"/api/datasets/{d1}", headers=auth_headers)).json()
    assert detail["test_count"] == 1
    assert detail["test_cases"][0]["id"] == keep


@pytest.mark.asyncio
async def test_dismiss_hides_group_on_next_scan(client, auth_headers):
    d1 = await _make_dataset(client, auth_headers, "Dismiss DS")
    a = await _add_case(client, auth_headers, d1, "a", "Wie geht das genau?")
    b = await _add_case(client, auth_headers, d1, "b", "wie geht das genau")

    assert len((await client.get("/api/datasets/duplicates", headers=auth_headers)).json()["groups"]) == 1

    resp = await client.post(
        "/api/datasets/duplicates/dismiss",
        headers=auth_headers,
        json={"case_ids": [a, b]},
    )
    assert resp.status_code == 204

    assert (await client.get("/api/datasets/duplicates", headers=auth_headers)).json()["groups"] == []

    # Dismissing again is idempotent (no unique-constraint blow-up).
    resp = await client.post(
        "/api/datasets/duplicates/dismiss",
        headers=auth_headers,
        json={"case_ids": [a, b]},
    )
    assert resp.status_code == 204
