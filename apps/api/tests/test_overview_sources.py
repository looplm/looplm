"""Tests for GET /api/overview/sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider
from app.models.source_registry import SourceExpectation, SourceGapRun
from app.services.overview_sources import collapse_gap_status

NOW = datetime.now(timezone.utc)


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


@pytest_asyncio.fixture
async def provider(db_session, test_project):
    p = IndexProvider(
        id=uuid4(), project_id=test_project.id, name="Azure index",
        type=IndexProviderType.azure_search, config={"index_name": "idx"},
        api_key=b"k", base_url="https://search.example.com",
    )
    db_session.add(p)
    await db_session.commit()
    return p


def _expectation(project_id, provider_id, name, **meta):
    return SourceExpectation(
        id=uuid4(), project_id=project_id, provider_id=provider_id, name=name, **meta
    )


def _gap_run(project_id, provider_id, created_at, rows, status="completed"):
    covered = sum(1 for r in rows if collapse_gap_status(r["status"]) == "covered")
    return SourceGapRun(
        id=uuid4(), project_id=project_id, provider_id=provider_id, status=status,
        total=len(rows), processed=len(rows), created_at=created_at,
        completed_at=created_at,
        results={
            "summary": {
                "total": len(rows),
                "covered": covered,
                "missing": sum(1 for r in rows if r["status"] == "missing"),
                "review": sum(1 for r in rows if r["status"] == "review"),
                "acked": sum(1 for r in rows if r["status"] == "acked"),
            },
            "rows": rows,
        },
    )


@pytest_asyncio.fixture
async def seeded(db_session, test_project, provider):
    """Three sources across two Typ values, with one gap run covering all three."""
    e1 = _expectation(test_project.id, provider.id, "GasNZV", typ="Gesetz",
                      sparte="Gas", publisher="BMWK", adapter_tag="gesetze")
    e2 = _expectation(test_project.id, provider.id, "StromNZV", typ="Gesetz",
                      sparte="Strom", publisher="BMWK", adapter_tag="gesetze")
    # Deliberately no typ: unset metadata is a signal, not noise.
    e3 = _expectation(test_project.id, provider.id, "MaKo Guide",
                      sparte="Strom", publisher="BDEW", adapter_tag="bdew-mako")
    db_session.add_all([e1, e2, e3])
    await db_session.flush()

    rows = [
        {"expectation_id": str(e1.id), "status": "covered_url", "chunk_count": 12},
        {"expectation_id": str(e2.id), "status": "missing", "chunk_count": 0},
        {"expectation_id": str(e3.id), "status": "covered_title", "chunk_count": 5},
    ]
    db_session.add(_gap_run(test_project.id, provider.id, NOW - timedelta(days=1), rows))
    await db_session.commit()
    return e1, e2, e3


def test_collapse_gap_status_matches_the_client_rule():
    # Both covered_* variants mean covered; the frontend collapses them the same way.
    assert collapse_gap_status("covered_url") == "covered"
    assert collapse_gap_status("covered_title") == "covered"
    assert collapse_gap_status("missing") == "missing"
    assert collapse_gap_status("review") == "review"
    assert collapse_gap_status("acked") == "acked"
    assert collapse_gap_status(None) == "unknown"
    assert collapse_gap_status("something-new") == "unknown"


@pytest.mark.asyncio
async def test_provider_type_counts(client, headers, provider, seeded):
    r = await client.get("/api/overview/sources", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["by_type"] == [{"type": "azure_search", "provider_count": 1}]
    assert len(body["providers"]) == 1
    assert body["providers"][0]["source_count"] == 3
    # No live document_count here: that needs an index round trip and stays lazy.
    assert "document_count" not in body["providers"][0]


@pytest.mark.asyncio
async def test_registry_dimension_cross_tab(client, headers, seeded):
    r = await client.get("/api/overview/sources", headers=headers)
    dims = {d["key"]: d for d in r.json()["registry"]["dimensions"]}

    typ = {v["label"]: v for v in dims["typ"]["values"]}
    assert typ["Gesetz"]["count"] == 2
    assert typ["Gesetz"]["covered"] == 1
    assert typ["Gesetz"]["missing"] == 1

    sparte = {v["label"]: v for v in dims["sparte"]["values"]}
    assert sparte["Strom"]["count"] == 2
    assert sparte["Gas"]["covered"] == 1

    assert r.json()["registry"]["total_sources"] == 3


@pytest.mark.asyncio
async def test_unset_metadata_is_kept_as_its_own_bucket(client, headers, seeded):
    r = await client.get("/api/overview/sources", headers=headers)
    dims = {d["key"]: d for d in r.json()["registry"]["dimensions"]}
    unset = next(v for v in dims["typ"]["values"] if v["value"] is None)
    assert unset["label"] == "(not set)"
    assert unset["count"] == 1


@pytest.mark.asyncio
async def test_top_n_truncation_folds_the_tail(client, headers, db_session, test_project, provider):
    for i in range(5):
        db_session.add(
            _expectation(test_project.id, provider.id, f"src-{i}", typ=f"Type-{i}")
        )
    await db_session.commit()

    r = await client.get("/api/overview/sources", params={"top": 2}, headers=headers)
    typ = next(d for d in r.json()["registry"]["dimensions"] if d["key"] == "typ")
    assert typ["truncated"] is True
    assert typ["distinct_values"] == 5
    assert typ["values"][-1]["label"] == "3 more"
    assert typ["values"][-1]["count"] == 3


@pytest.mark.asyncio
async def test_coverage_latest_and_history(client, headers, db_session, test_project, provider, seeded):
    older_rows = [{"expectation_id": str(seeded[0].id), "status": "missing", "chunk_count": 0}]
    db_session.add(
        _gap_run(test_project.id, provider.id, NOW - timedelta(days=10), older_rows)
    )
    await db_session.commit()

    r = await client.get("/api/overview/sources", headers=headers)
    coverage = r.json()["coverage"]
    # Oldest first, one point per run. Runs are never summed: coverage is a level.
    assert len(coverage["history"]) == 2
    assert coverage["history"][0]["covered"] == 0
    assert coverage["history"][1]["covered"] == 2
    assert coverage["latest"]["covered"] == 2
    assert coverage["latest"]["total"] == 3
    assert coverage["latest"]["covered_rate"] == round(2 / 3, 4)


@pytest.mark.asyncio
async def test_incomplete_gap_runs_are_ignored(client, headers, db_session, test_project, provider, seeded):
    db_session.add(
        _gap_run(test_project.id, provider.id, NOW, [], status="running")
    )
    await db_session.commit()
    r = await client.get("/api/overview/sources", headers=headers)
    # The running run must not become "latest" and blank the coverage numbers.
    assert r.json()["coverage"]["latest"]["covered"] == 2


@pytest.mark.asyncio
async def test_stale_when_the_source_list_grew(client, headers, db_session, test_project, provider, seeded):
    db_session.add(_expectation(test_project.id, provider.id, "Newly added", typ="Gesetz"))
    await db_session.commit()
    r = await client.get("/api/overview/sources", headers=headers)
    coverage = r.json()["coverage"]
    assert coverage["stale"] is True
    assert "4 sources now, 3 then" in coverage["stale_reason"]


@pytest.mark.asyncio
async def test_stale_when_the_last_run_is_old(client, headers, db_session, test_project, provider):
    e = _expectation(test_project.id, provider.id, "Only", typ="Gesetz")
    db_session.add(e)
    await db_session.flush()
    rows = [{"expectation_id": str(e.id), "status": "covered_url", "chunk_count": 1}]
    db_session.add(_gap_run(test_project.id, provider.id, NOW - timedelta(days=40), rows))
    await db_session.commit()

    r = await client.get("/api/overview/sources", headers=headers)
    assert r.json()["coverage"]["stale"] is True
    assert "40 days ago" in r.json()["coverage"]["stale_reason"]


@pytest.mark.asyncio
async def test_fresh_run_is_not_stale(client, headers, seeded):
    r = await client.get("/api/overview/sources", headers=headers)
    assert r.json()["coverage"]["stale"] is False
    assert r.json()["coverage"]["stale_reason"] is None


@pytest.mark.asyncio
async def test_no_gap_run_is_reported_as_stale(client, headers, db_session, test_project, provider):
    db_session.add(_expectation(test_project.id, provider.id, "Unanalysed", typ="Gesetz"))
    await db_session.commit()
    r = await client.get("/api/overview/sources", headers=headers)
    coverage = r.json()["coverage"]
    assert coverage["latest"] is None
    assert coverage["history"] == []
    assert coverage["stale"] is True
    assert coverage["stale_reason"] == "No gap analysis has run yet"


@pytest.mark.asyncio
async def test_project_with_no_provider(client, headers):
    r = await client.get("/api/overview/sources", headers=headers)
    body = r.json()
    assert body["providers"] == []
    assert body["by_type"] == []
    assert body["registry"]["total_sources"] == 0


@pytest.mark.asyncio
async def test_indexed_sources_kpi_is_null_without_a_provider(client, headers):
    """Null, not zero: zero would claim an empty index rather than "not configured"."""
    r = await client.get(
        "/api/overview/summary", params={"bucket": "day", "days": 7}, headers=headers
    )
    kpi = next(k for k in r.json()["kpis"] if k["key"] == "indexed_sources")
    assert kpi["value"] is None
    assert kpi["sub"] == "No index provider connected"


@pytest.mark.asyncio
async def test_indexed_sources_kpi_counts_registry_sources(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "day", "days": 7}, headers=headers
    )
    kpi = next(k for k in r.json()["kpis"] if k["key"] == "indexed_sources")
    assert kpi["value"] == 3.0
    assert kpi["sub"] == "1 provider"
    # Index state has no previous period, so no delta is offered.
    assert kpi["change_pct"] is None


@pytest.mark.asyncio
async def test_provider_filter_scopes_the_registry(client, headers, db_session, test_project, provider, seeded):
    other = IndexProvider(
        id=uuid4(), project_id=test_project.id, name="Second", type=IndexProviderType.azure_search,
        config={"index_name": "idx2"}, api_key=b"k", base_url="https://s2.example.com",
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add(_expectation(test_project.id, other.id, "Elsewhere", typ="Spec"))
    await db_session.commit()

    r = await client.get(
        "/api/overview/sources", params={"provider_id": str(provider.id)}, headers=headers
    )
    assert r.json()["registry"]["total_sources"] == 3
    # Providers are always listed in full so the picker can offer them.
    assert len(r.json()["providers"]) == 2
