"""Tests for the pure RAG coverage-computation helper."""

from __future__ import annotations

from app.index_providers.base import CorpusDoc, PartitionValue
from app.index_providers.coverage import (
    CoverageRow,
    compute_coverage,
    coverage_fields_for,
    detect_partition_issues,
)
import pytest

from app.index_providers.azure_search_sampling import spread_offsets, spread_sample
from app.routers.rag_coverage_worker import (
    _build_user_prompt,
    _fit_budget,
    _sources_from_refs,
)


def _pv(value: str, count: int) -> PartitionValue:
    return PartitionValue(value=value, doc_count=count)


def _row(value: str, count: int) -> CoverageRow:
    return CoverageRow(value=value, indexed_count=count, covering_cases=0, covered=False)


def _issue_map(rows):
    return {i.value: i for i in detect_partition_issues(rows)}


# ── field mapping ──────────────────────────────────────────────

def test_known_keys_map_to_expected_fields():
    assert "tag_filter" in coverage_fields_for("tags")
    assert coverage_fields_for("source_type") == ("expected_source_types",)
    assert coverage_fields_for("team") == ("team_filter",)


def test_unknown_key_has_no_list_fields():
    assert coverage_fields_for("mandant") == ()


# ── coverage computation ───────────────────────────────────────

def test_tag_partition_marks_uncovered_and_covered():
    distribution = [_pv("bundesnetzagentur", 804), _pv("gesetze", 120)]
    test_cases = [{"tag_filter": ["gesetze"]}]

    report = compute_coverage("tags", distribution, test_cases)

    assert report.total_values == 2
    assert report.covered_values == 1
    # rows sorted by indexed_count desc → bundesnetzagentur first
    assert report.rows[0].value == "bundesnetzagentur"
    assert report.rows[0].covered is False
    assert report.rows[0].covering_cases == 0
    gap_values = {g.value for g in report.gaps}
    assert gap_values == {"bundesnetzagentur"}
    # doc coverage = 120 / (804+120); the field is unrounded, to_dict() rounds.
    assert report.doc_coverage_pct == 100 * 120 / 924
    assert report.to_dict()["doc_coverage_pct"] == 13.0


def test_matching_is_case_insensitive():
    report = compute_coverage("tags", [_pv("BNetzA", 10)], [{"tag_filter": ["bnetza"]}])
    assert report.rows[0].covered is True


def test_min_covering_cases_threshold():
    distribution = [_pv("edifact", 50)]
    test_cases = [{"tag_filter": ["edifact"]}]  # only one covering case
    report = compute_coverage("tags", distribution, test_cases, min_covering_cases=2)
    assert report.rows[0].covering_cases == 1
    assert report.rows[0].covered is False


def test_source_type_uses_expected_source_types_field():
    report = compute_coverage(
        "source_type",
        [_pv("festlegung", 30), _pv("page", 200)],
        [{"expected_source_types": ["festlegung"]}],
    )
    by_value = {r.value: r for r in report.rows}
    assert by_value["festlegung"].covered is True
    assert by_value["page"].covered is False


def test_unknown_key_falls_back_to_context_filters():
    report = compute_coverage(
        "mandant",
        [_pv("Stadtwerke", 5), _pv("Other", 5)],
        [{"context_filters": {"mandant": "stadtwerke"}}],
    )
    by_value = {r.value: r for r in report.rows}
    assert by_value["Stadtwerke"].covered is True
    assert by_value["Other"].covered is False


def test_empty_distribution_gives_zero_pct():
    report = compute_coverage("tags", [], [{"tag_filter": ["x"]}])
    assert report.total_values == 0
    assert report.value_coverage_pct == 0.0
    assert report.doc_coverage_pct == 0.0


def test_to_dict_shape_is_json_serialisable():
    report = compute_coverage("tags", [_pv("a", 1)], [])
    d = report.to_dict()
    assert d["partition_key"] == "tags"
    assert d["rows"][0] == {
        "value": "a",
        "indexed_count": 1,
        "covering_cases": 0,
        "covered": False,
    }
    assert d["issues"] == []


# ── partition-quality detection ────────────────────────────────

def test_near_duplicate_flags_parenthetical_variant():
    rows = [_row("FiBu", 331), _row("FiBu (Finanzbuchhaltung)", 7), _row("EDM", 7126)]
    issues = _issue_map(rows)
    assert "FiBu" not in issues  # canonical (larger) not flagged
    dup = issues["FiBu (Finanzbuchhaltung)"]
    assert dup.kind == "near_duplicate"
    assert dup.severity == "high"
    assert dup.related_values == ["FiBu"]
    assert "EDM" not in issues


def test_near_duplicate_flags_case_and_whitespace_variants():
    rows = [_row("Netz", 800), _row("  netz ", 5), _row("Other", 800)]
    issues = _issue_map(rows)
    assert issues["  netz "].kind == "near_duplicate"
    assert issues["  netz "].related_values == ["Netz"]


def test_tiny_bucket_flagged_only_with_spread():
    rows = [_row("A", 1000), _row("B", 900), _row("C", 3)]
    issues = _issue_map(rows)
    assert issues["C"].kind == "tiny_bucket"
    assert issues["C"].severity == "low"
    assert "A" not in issues and "B" not in issues


def test_uniformly_small_distribution_not_flagged():
    rows = [_row("A", 4), _row("B", 5), _row("C", 6)]
    # median 5, threshold = max(10, 0.02*5)=10 → all below 10, but this would flag all;
    # guard: tiny requires being far below median. Here counts ~ median, so none flagged.
    issues = _issue_map(rows)
    assert issues == {}


def test_empty_and_placeholder_flagged():
    rows = [_row("EDM", 500), _row("", 12), _row("unknown", 9), _row("N/A", 4)]
    issues = _issue_map(rows)
    assert issues[""].kind == "empty_or_placeholder"
    assert issues["unknown"].kind == "empty_or_placeholder"
    assert issues["N/A"].kind == "empty_or_placeholder"
    assert "EDM" not in issues


def test_near_duplicate_takes_precedence_over_tiny():
    rows = [_row("FiBu", 500), _row("FiBu (alt)", 2), _row("X", 600)]
    issues = _issue_map(rows)
    # the 2-chunk variant is both a duplicate AND tiny → reported as near_duplicate only
    assert issues["FiBu (alt)"].kind == "near_duplicate"


def test_compute_coverage_includes_detected_issues():
    dist = [_pv("FiBu", 331), _pv("FiBu (Finanzbuchhaltung)", 7)]
    report = compute_coverage("team", dist, [])
    kinds = {i.value: i.kind for i in report.issues}
    assert kinds.get("FiBu (Finanzbuchhaltung)") == "near_duplicate"


# ── suggestion source attribution ──────────────────────────────

def _doc(doc_id: str, title: str | None, url: str | None, snippet: str = "text"):
    return CorpusDoc(id=doc_id, title=title, url=url, snippet=snippet)


def test_source_refs_map_to_cited_documents_only():
    docs = [
        _doc("1", "Vertragsmanagement", "https://wiki/x/1"),
        _doc("2", "kVASy", "https://wiki/x/2"),
        _doc("3", "winEV", "https://wiki/x/3"),
    ]
    sources = _sources_from_refs(docs, [1, "3"])
    assert [s.url for s in sources] == ["https://wiki/x/1", "https://wiki/x/3"]


def test_source_refs_out_of_range_or_missing_fall_back_to_all_docs():
    docs = [_doc("1", "A", "https://wiki/a"), _doc("2", "B", "https://wiki/b")]
    assert len(_sources_from_refs(docs, None)) == 2
    assert len(_sources_from_refs(docs, [9, "nope"])) == 2
    assert len(_sources_from_refs(docs, [])) == 2


def test_sources_dedupe_chunks_of_the_same_page():
    docs = [
        _doc("chunk-1", "Page", "https://wiki/page"),
        _doc("chunk-2", "Page", "https://wiki/page"),
        _doc("chunk-3", "Other", None),
    ]
    sources = _sources_from_refs(docs, [1, 2, 3])
    assert [(s.title, s.url) for s in sources] == [
        ("Page", "https://wiki/page"),
        ("Other", None),
    ]


def test_user_prompt_numbers_excerpts_for_citation():
    docs = [_doc("1", "Titel", "https://wiki/a", "Inhalt A"), _doc("2", None, None, "Inhalt B")]
    prompt = _build_user_prompt("tags", "uebersicht", docs)
    assert "[1] (Titel) Inhalt A" in prompt
    assert "[2] Inhalt B" in prompt


def test_user_prompt_without_excerpts_is_explicit():
    assert "(no text excerpts available)" in _build_user_prompt("tags", "uebersicht", [])


# ── even-spaced sampling across a slice ────────────────────────

def test_spread_offsets_cover_the_whole_slice():
    assert spread_offsets(800, 8) == [0, 100, 200, 300, 400, 500, 600, 700]


def test_spread_offsets_never_repeat_or_overrun():
    offsets = spread_offsets(5, 8)
    assert offsets == [0, 1, 2, 3, 4]
    assert spread_offsets(1, 8) == [0]
    assert spread_offsets(0, 8) == [0]
    assert max(spread_offsets(9, 4)) < 9


def test_spread_offsets_clamped_to_azure_skip_ceiling():
    offsets = spread_offsets(5_000_000, 8, max_skip=100)
    assert offsets[0] == 0
    assert max(offsets) <= 100


# ── grounding budget ───────────────────────────────────────────

def _snippet_doc(chars: int):
    return CorpusDoc(id="c", title=None, url=None, snippet="x" * chars)


def test_budget_drops_whole_excerpts_never_slices():
    docs = [_snippet_doc(400), _snippet_doc(400), _snippet_doc(400)]
    kept = _fit_budget(docs, budget=900)
    assert len(kept) == 2
    assert all(len(d.snippet) == 400 for d in kept)  # nothing was cut


def test_budget_always_keeps_the_first_excerpt():
    kept = _fit_budget([_snippet_doc(5_000)], budget=100)
    assert len(kept) == 1
    assert len(kept[0].snippet) == 5_000


def test_budget_keeps_everything_that_fits():
    docs = [_snippet_doc(100) for _ in range(5)]
    assert len(_fit_budget(docs, budget=10_000)) == 5


# ── spread_sample against a fake Azure client ──────────────────

class _FakeResults:
    """Mimics the SDK's async paged iterator (async iteration + awaitable count)."""

    def __init__(self, docs: list[dict], total: int):
        self._docs = docs
        self._total = total

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def get_count(self):
        return self._total


class _FakeSearchClient:
    def __init__(self, corpus: list[dict], fail_at: set[int] | None = None):
        self._corpus = corpus
        self._fail_at = fail_at or set()
        self.skips: list[int] = []

    async def search(self, *, top: int, skip: int = 0, **kwargs):
        self.skips.append(skip)
        if skip in self._fail_at:
            raise RuntimeError("backend hiccup")
        return _FakeResults(self._corpus[skip : skip + top], len(self._corpus))


@pytest.mark.asyncio
async def test_spread_sample_walks_the_slice_not_its_head():
    corpus = [{"chunk_text": f"chunk {i}"} for i in range(100)]
    client = _FakeSearchClient(corpus)
    docs = await spread_sample(client, "tags/any(t: t eq 'x')", ["chunk_text"], 5)
    assert client.skips == [0, 20, 40, 60, 80]
    assert [d["chunk_text"] for d in docs] == [
        "chunk 0", "chunk 20", "chunk 40", "chunk 60", "chunk 80",
    ]


@pytest.mark.asyncio
async def test_spread_sample_survives_a_failed_offset():
    corpus = [{"chunk_text": f"chunk {i}"} for i in range(100)]
    docs = await spread_sample(_FakeSearchClient(corpus, fail_at={40}), None, None, 5)
    assert [d["chunk_text"] for d in docs] == ["chunk 0", "chunk 20", "chunk 60", "chunk 80"]


@pytest.mark.asyncio
async def test_spread_sample_on_empty_slice_returns_nothing():
    assert await spread_sample(_FakeSearchClient([]), "team eq 'ghost'", None, 5) == []
