"""Duplicate / near-duplicate detection across a project's test-case prompts.

Purely lexical and deterministic — no embeddings or LLM calls. Prompts are
short German questions, so we combine word-token and character-trigram Jaccard
similarity, which handles both identical prompts and high-overlap paraphrases.

For the dataset sizes we deal with (hundreds of cases) the all-pairs O(n^2)
comparison is trivial. If a project grows into the thousands, block candidates
by shared token before the pairwise pass (not needed today).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_labels import (
    ChunkGoldLabel,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)
# Trailing punctuation / quoting we strip so "Wie geht das?" == "wie geht das"
_TRIM_CHARS = " \t\r\n.,;:!?\"'`´»«„“”‚‘’()[]{}-–—"


def normalize_prompt(text: str | None) -> str:
    """Lowercase, collapse whitespace, and strip surrounding punctuation."""
    if not text:
        return ""
    collapsed = " ".join(text.split()).lower()
    return collapsed.strip(_TRIM_CHARS)


def _tokens(normalized: str) -> set[str]:
    return set(_WORD_RE.findall(normalized))


def _trigrams(normalized: str) -> set[str]:
    compact = normalized.replace(" ", "")
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def similarity(norm_a: str, norm_b: str) -> float:
    """Lexical similarity in [0, 1]: max of word-token and trigram Jaccard.

    Both prompts must already be normalized via :func:`normalize_prompt`.
    Word Jaccard captures shared vocabulary; trigram Jaccard is more forgiving
    of morphology (German compounds/inflection) and short prompts.
    """
    if not norm_a or not norm_b:
        return 0.0
    word = _jaccard(_tokens(norm_a), _tokens(norm_b))
    tri = _jaccard(_trigrams(norm_a), _trigrams(norm_b))
    return max(word, tri)


@dataclass
class _Case:
    """Minimal view of a test case needed for clustering."""

    id: str
    dataset_id: str
    dataset_name: str
    test_id: str
    prompt: str
    expected_answer: str | None
    status: str
    normalized: str = field(default="")


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Order-independent key for a case-id pair (matches stored dismissals)."""
    return (a, b) if a <= b else (b, a)


def find_duplicate_groups(
    cases: list[dict[str, Any]],
    *,
    threshold: float = 0.8,
    scope: str = "all",
    dismissed_pairs: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster ``cases`` into duplicate groups.

    ``cases`` are dicts with keys: ``id``, ``dataset_id``, ``dataset_name``,
    ``test_id``, ``prompt``, ``expected_answer``, ``status``.

    - Exact tier: prompts equal after normalization (edge weight 1.0).
    - Near tier: ``similarity >= threshold``.
    - ``scope="within_dataset"`` only links cases sharing a ``dataset_id``.
    - Pairs present in ``dismissed_pairs`` are never linked.

    Returns groups (>= 2 members) sorted by descending match score, each:
    ``{"match_type", "score", "members": [...]}``. ``score`` on a member is its
    max similarity to any other member in the group.
    """
    dismissed_pairs = dismissed_pairs or set()
    items = [
        _Case(
            id=str(c["id"]),
            dataset_id=str(c["dataset_id"]),
            dataset_name=c.get("dataset_name", ""),
            test_id=c.get("test_id", ""),
            prompt=c.get("prompt", "") or "",
            expected_answer=c.get("expected_answer"),
            status=c.get("status") or "active",
            normalized=normalize_prompt(c.get("prompt")),
        )
        for c in cases
    ]
    items = [it for it in items if it.normalized]

    n = len(items)
    uf = _UnionFind(n)
    # Track the best score seen on each surviving edge, per unordered index pair.
    edge_score: dict[tuple[int, int], float] = {}

    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            if scope == "within_dataset" and a.dataset_id != b.dataset_id:
                continue
            if _pair_key(a.id, b.id) in dismissed_pairs:
                continue
            score = 1.0 if a.normalized == b.normalized else similarity(a.normalized, b.normalized)
            if score >= threshold:
                uf.union(i, j)
                edge_score[(i, j)] = score

    # Gather clusters
    clusters: dict[int, list[int]] = {}
    for idx in range(n):
        clusters.setdefault(uf.find(idx), []).append(idx)

    # Per-member score = best edge score to any other member of its cluster.
    member_score: dict[int, float] = {idx: 0.0 for idx in range(n)}
    for (i, j), score in edge_score.items():
        member_score[i] = max(member_score[i], score)
        member_score[j] = max(member_score[j], score)

    groups: list[dict[str, Any]] = []
    for members_idx in clusters.values():
        if len(members_idx) < 2:
            continue
        group_score = max(member_score[idx] for idx in members_idx)
        match_type = "exact" if group_score >= 1.0 else "near"
        members = [
            {
                "case_id": items[idx].id,
                "dataset_id": items[idx].dataset_id,
                "dataset_name": items[idx].dataset_name,
                "test_id": items[idx].test_id,
                "prompt": items[idx].prompt,
                "expected_answer": items[idx].expected_answer,
                "status": items[idx].status,
                "score": round(member_score[idx], 4),
            }
            # Deterministic order: highest-score member first, then test_id.
            for idx in sorted(
                members_idx, key=lambda k: (-member_score[k], items[k].test_id)
            )
        ]
        groups.append(
            {
                "match_type": match_type,
                "score": round(group_score, 4),
                "members": members,
            }
        )

    groups.sort(key=lambda g: (-g["score"], -len(g["members"])))
    return groups


# --- Merge ---------------------------------------------------------------

_LIST_FIELDS = (
    "expected_sources",
    "expected_page_urls",
    "expected_source_types",
    "tags",
    "team_filter",
    "tag_filter",
)


def merge_case_fields(keep: Any, others: list[Any]) -> None:
    """Fold field values from ``others`` into ``keep`` (mutates ``keep``).

    - Empty scalar fields on ``keep`` (expected_answer, max_answer_length,
      folder, document) are filled from the first non-empty among ``others``.
    - List fields are unioned, order-preserving, keep's values first.
    - ``follow_up_prompts`` (list of dicts) are concatenated and de-duplicated.
    - ``context_filters`` / ``metadata`` are shallow-merged, keep wins on
      conflicting keys.

    ``keep`` and ``others`` are ``TestCase`` ORM instances. Callers delete the
    ``others`` afterwards.
    """
    for scalar in ("expected_answer", "max_answer_length", "folder", "document"):
        if getattr(keep, scalar, None) in (None, ""):
            for other in others:
                val = getattr(other, scalar, None)
                if val not in (None, ""):
                    setattr(keep, scalar, val)
                    break

    for field_name in _LIST_FIELDS:
        merged = list(getattr(keep, field_name, None) or [])
        seen = set(merged)
        for other in others:
            for val in getattr(other, field_name, None) or []:
                if val not in seen:
                    merged.append(val)
                    seen.add(val)
        setattr(keep, field_name, merged)

    # follow_up_prompts: list of dicts — concat + de-dupe by serialized content.
    fups = list(keep.follow_up_prompts or [])
    seen_fups = {repr(sorted(f.items())) if isinstance(f, dict) else repr(f) for f in fups}
    for other in others:
        for f in other.follow_up_prompts or []:
            key = repr(sorted(f.items())) if isinstance(f, dict) else repr(f)
            if key not in seen_fups:
                fups.append(f)
                seen_fups.add(key)
    keep.follow_up_prompts = fups or None

    for dict_field, attr in (("context_filters", "context_filters"), ("metadata", "test_case_metadata")):
        merged_dict: dict[str, Any] = {}
        for other in others:
            other_val = getattr(other, attr, None)
            if isinstance(other_val, dict):
                merged_dict.update(other_val)
        keep_val = getattr(keep, attr, None)
        if isinstance(keep_val, dict):
            merged_dict.update(keep_val)  # keep wins on conflicts
        setattr(keep, attr, merged_dict)


async def merge_case_labeling(
    db: AsyncSession,
    project_id: UUID,
    keep_test_id: str,
    source_test_ids: list[str],
) -> None:
    """Fold the labeling (and hence retrieval) data of merged cases onto the kept case.

    Chunk relevance labels, adjudicated gold verdicts, and the labeling-complete flag are all
    keyed by ``(project_id, test_id)`` with no foreign key to the ``test_cases`` row (retrieval
    metrics are derived from them by ``test_id``). So when duplicate cases are merged and the
    losers deleted, their human judgments would be orphaned and the retrieval numbers that depend
    on them lost. This re-points those rows from each merged case's ``test_id`` to the kept case's,
    so no labeling effort is discarded.

    Conflicts resolve in favour of the kept case's existing rows:

    - relevance labels dedup by ``(chunk_id, annotator identity)`` — a human's judgment and an
      ``AI`` judgment of the same chunk are distinct rows and both survive;
    - gold verdicts dedup by ``chunk_id`` (one gold per chunk);
    - labeling status is a single row per ``test_id`` — the kept case's wins if it has one, else a
      ``complete`` source row (any) is moved over, otherwise the first.

    Sources equal to ``keep_test_id`` are skipped: they already share the kept case's rows. Must be
    called before the merged cases are flushed away (order relative to the delete does not matter —
    there is no FK — but it must run in the same transaction).
    """
    sources = [t for t in dict.fromkeys(source_test_ids) if t and t != keep_test_id]
    if not sources:
        return

    async def _rows(model):
        keep_rows = (
            await db.execute(
                select(model).where(model.project_id == project_id, model.test_id == keep_test_id)
            )
        ).scalars().all()
        src_rows = (
            await db.execute(
                select(model).where(model.project_id == project_id, model.test_id.in_(sources))
            )
        ).scalars().all()
        return keep_rows, src_rows

    # Relevance labels: dedup on (chunk_id, labeled_by, annotator) so distinct annotators are kept.
    def _rel_key(row: ChunkRelevanceLabel) -> tuple:
        return (row.chunk_id, str(row.labeled_by) if row.labeled_by else None, row.annotator)

    keep_rel, src_rel = await _rows(ChunkRelevanceLabel)
    claimed = {_rel_key(r) for r in keep_rel}
    for row in src_rel:
        key = _rel_key(row)
        if key in claimed:
            await db.delete(row)
        else:
            row.test_id = keep_test_id
            claimed.add(key)

    # Gold verdicts: one per chunk_id.
    keep_gold, src_gold = await _rows(ChunkGoldLabel)
    gold_claimed = {r.chunk_id for r in keep_gold}
    for row in src_gold:
        if row.chunk_id in gold_claimed:
            await db.delete(row)
        else:
            row.test_id = keep_test_id
            gold_claimed.add(row.chunk_id)

    # Labeling status: single row per test_id.
    keep_status, src_status = await _rows(TestCaseLabelingStatus)
    if keep_status:
        for row in src_status:
            await db.delete(row)
    elif src_status:
        winner = next((r for r in src_status if r.complete), src_status[0])
        winner.test_id = keep_test_id
        for row in src_status:
            if row is not winner:
                await db.delete(row)
