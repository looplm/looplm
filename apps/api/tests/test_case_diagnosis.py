"""Tests for the per-case retrieval diagnosis: score_chunk flags + the /case-diagnosis endpoint."""

from __future__ import annotations

import pytest

from app.index_providers.base import CorpusDoc
from app.index_providers.chunk_quality_common import score_chunk


# --- score_chunk (per-chunk quality flags) --------------------------------

def test_score_chunk_clean_chunk_has_no_issues():
    text = "This is a normal, readable paragraph. " * 20  # ~150 tokens, clean prose
    flags = score_chunk(text, has_vector=True)
    assert flags.issues() == []
    assert flags.token_estimate > 40


def test_score_chunk_flags_tiny_and_giant():
    tiny = score_chunk("word " * 10, has_vector=True)  # ~12 tokens
    assert "tiny" in tiny.issues()
    giant = score_chunk("word " * 2000, has_vector=True)  # well over GIANT_TOKENS
    assert "giant" in giant.issues()


def test_score_chunk_flags_mojibake_and_markup():
    assert "mojibake" in score_chunk("Preis in EurÃ¼ pro StÃ¼ck", has_vector=True).issues()
    markup = "<div><span>x</span></div><p>y</p><br/><b>z</b><i>q</i>" * 2
    assert "markup_heavy" in score_chunk(markup, has_vector=True).issues()


def test_score_chunk_missing_embedding_only_when_known_false():
    text = "Readable content here. " * 20
    assert "missing_embedding" in score_chunk(text, has_vector=False).issues()
    assert "missing_embedding" not in score_chunk(text, has_vector=True).issues()
    assert "missing_embedding" not in score_chunk(text, has_vector=None).issues()


# --- /case-diagnosis endpoint ---------------------------------------------

class _FakeProvider:
    """Stands in for the Azure index: a fixed ranking + a doc-by-key lookup."""

    def __init__(self, ranking: list[CorpusDoc], docs: dict[str, dict]):
        self._ranking = ranking
        self._docs = docs

    async def search_documents(self, query, n, filters=None, *, mode="keyword", query_vector=None):
        return self._ranking[:n]

    async def fetch_documents_by_key(self, ids):
        return {i: self._docs[i] for i in ids if i in self._docs}

    async def aclose(self):
        pass


CLEAN = "This is a clear, self-contained paragraph about the topic. " * 20  # clean, ~180 tokens


@pytest.mark.asyncio
async def test_case_diagnosis_classifies_missed_chunks(
    client, auth_headers, db_session, test_user, test_project, monkeypatch
):
    from uuid import uuid4

    from app.models.base import IndexProviderType
    from app.models.chunk_labels import ChunkRelevanceLabel
    from app.models.datasets import TestCase, TestDataset
    from app.models.index_providers import IndexProvider

    # A dataset + case, and an index provider row (its build is monkeypatched below).
    ds = TestDataset(id=uuid4(), project_id=test_project.id, name="Diag DS")
    db_session.add(ds)
    await db_session.flush()
    db_session.add(
        TestCase(id=uuid4(), dataset_id=ds.id, test_id="diag", prompt="Wie geht das genau?")
    )
    db_session.add(
        IndexProvider(
            id=uuid4(), project_id=test_project.id, type=IndexProviderType.azure_search,
            name="idx", api_key=b"x", config={},
        )
    )
    # Six judged-relevant chunks (human labels). c_good is retrieved; the other five are missed.
    for cid in ("c_good", "c_buried", "c_tiny", "c_novec", "c_missing", "c_unret"):
        db_session.add(
            ChunkRelevanceLabel(
                project_id=test_project.id, test_id="diag", chunk_id=cid, relevance=2,
                labeled_by=test_user.id, content_preview=f"snapshot of {cid}",
            )
        )
    await db_session.commit()

    # Keyword ranking: c_good @1, c_buried @2. The rest never surface in the ranking.
    ranking = [CorpusDoc(id="c_good"), CorpusDoc(id="c_buried")]
    docs = {
        "c_buried": {"chunk_text": CLEAN, "vector": [0.1] * 32},   # clean+embedded, ranked past k
        "c_tiny": {"chunk_text": "word " * 10, "vector": [0.1] * 32},  # too short → bad_chunk
        "c_novec": {"chunk_text": CLEAN},                          # no embedding → missing_embedding
        "c_unret": {"chunk_text": CLEAN, "vector": [0.1] * 32},    # clean+embedded, never ranked
        # c_missing intentionally absent → not_in_index
    }
    fake = _FakeProvider(ranking, docs)
    monkeypatch.setattr(
        "app.routers.chunk_labels._helpers.build_index_provider", lambda row: fake
    )
    monkeypatch.setattr(
        "app.routers.chunk_labels.diagnosis.build_index_provider", lambda row: fake
    )

    async def _no_embed(settings, text):
        return None

    monkeypatch.setattr("app.routers.chunk_labels._helpers.embed_query", _no_embed)

    resp = await client.get(
        "/api/pipeline/case-diagnosis",
        headers=auth_headers,
        params={"test_id": "diag", "k": 1, "retriever": "keyword", "refresh": "true"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["available"] is True
    assert data["relevant_count"] == 6
    assert data["retrieved_relevant_count"] == 1  # c_good
    assert data["missed_count"] == 5

    verdicts = {c["chunk_id"]: c["verdict"] for c in data["missed"]}
    assert verdicts == {
        "c_buried": "buried",
        "c_tiny": "bad_chunk",
        "c_novec": "missing_embedding",
        "c_missing": "not_in_index",
        "c_unret": "unretrievable",
    }
    assert data["summary"]["bad_chunk"] == 1
    assert data["summary"]["missing_embedding"] == 1

    tiny = next(c for c in data["missed"] if c["chunk_id"] == "c_tiny")
    assert "tiny" in tiny["flags"]
    buried = next(c for c in data["missed"] if c["chunk_id"] == "c_buried")
    assert buried["rank"] == 2 and buried["has_embedding"] is True
    missing = next(c for c in data["missed"] if c["chunk_id"] == "c_missing")
    assert missing["content_preview"] == "snapshot of c_missing"  # label fallback


@pytest.mark.asyncio
async def test_case_diagnosis_does_not_false_flag_missing_embedding(
    client, auth_headers, db_session, test_user, test_project, monkeypatch
):
    """Azure vector fields are usually non-retrievable, so a fetched doc exposes no vector even
    when the chunk is embedded. A retrieved chunk must read as 'buried', and an unretrieved one as
    'unretrievable' — never 'missing_embedding' — when embeddings can't be observed."""
    from uuid import uuid4

    from app.models.base import IndexProviderType
    from app.models.chunk_labels import ChunkRelevanceLabel
    from app.models.datasets import TestCase, TestDataset
    from app.models.index_providers import IndexProvider

    ds = TestDataset(id=uuid4(), project_id=test_project.id, name="NoVec DS")
    db_session.add(ds)
    await db_session.flush()
    db_session.add(TestCase(id=uuid4(), dataset_id=ds.id, test_id="nv", prompt="Frage?"))
    db_session.add(
        IndexProvider(
            id=uuid4(), project_id=test_project.id, type=IndexProviderType.azure_search,
            name="idx", api_key=b"x", config={},
        )
    )
    for cid in ("c_top", "c_ranked2", "c_absent"):
        db_session.add(
            ChunkRelevanceLabel(
                project_id=test_project.id, test_id="nv", chunk_id=cid, relevance=2,
                labeled_by=test_user.id, content_preview=f"snap {cid}",
            )
        )
    await db_session.commit()

    # c_top @1, c_ranked2 @2 are retrieved (by every head, incl. dense). No fetched doc exposes a
    # vector field — as with a real Azure index where the vector field isn't retrievable.
    ranking = [CorpusDoc(id="c_top"), CorpusDoc(id="c_ranked2")]
    docs = {
        "c_ranked2": {"chunk_text": CLEAN},  # retrieved but no visible vector → must be "buried"
        "c_absent": {"chunk_text": CLEAN},   # never retrieved, vectors unobservable → "unretrievable"
    }
    fake = _FakeProvider(ranking, docs)
    monkeypatch.setattr("app.routers.chunk_labels._helpers.build_index_provider", lambda row: fake)
    monkeypatch.setattr("app.routers.chunk_labels.diagnosis.build_index_provider", lambda row: fake)

    async def _no_embed(settings, text):
        return None

    monkeypatch.setattr("app.routers.chunk_labels._helpers.embed_query", _no_embed)

    resp = await client.get(
        "/api/pipeline/case-diagnosis",
        headers=auth_headers,
        params={"test_id": "nv", "k": 1, "retriever": "keyword", "refresh": "true"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    verdicts = {c["chunk_id"]: c["verdict"] for c in data["missed"]}
    assert verdicts == {"c_ranked2": "buried", "c_absent": "unretrievable"}
    assert "missing_embedding" not in data["summary"]


@pytest.mark.asyncio
async def test_case_diagnosis_no_index_provider(client, auth_headers, test_project):
    resp = await client.get(
        "/api/pipeline/case-diagnosis", headers=auth_headers, params={"test_id": "nope"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_connected"] is False
    assert data["available"] is False
