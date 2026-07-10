"""Chunk & metadata quality analysis over a connected retrieval index.

The index is chunk-level (each indexed document is one chunk). This reads a
representative *sample* of chunks once (``provider.sample_corpus``) and scores
their quality across five always-on families:

* **size** — length distribution & consistency, tiny/giant/empty outliers;
* **duplication** — exact duplicates, near-duplicates, and adjacent-chunk
  overlap within a parent document;
* **metadata** — per-field fill rate, cardinality, orphans, enum drift
  (see :mod:`chunk_quality_checks`);
* **content** — boilerplate, table soup, mojibake, embedding coverage
  (see :mod:`chunk_quality_checks`);
* **boundary** — chunks cut mid-sentence/mid-table, severed numbered steps
  (see :mod:`chunk_quality_boundary`).

Opt-in extended passes (LLM judge, embedding cohesion, retrieval frequency,
claim boundary) live in :mod:`chunk_quality_extended` and merge into the same
report. Everything except the metadata facet calls is pure and synchronous, so
the families are unit-testable against a synthetic doc list with no live index.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.index_providers.base import BaseIndexProvider
from app.index_providers.chunk_quality_boundary import analyze_boundaries
from app.index_providers.chunk_quality_checks import analyze_content, analyze_metadata
from app.index_providers.chunk_quality_common import (
    GIANT_TOKENS,
    GROUP_FIELDS,
    ID_FIELDS,
    ORDINAL_FIELDS,
    PARENT_FIELDS,
    SEVERITY_WEIGHTS,
    TEXT_FIELDS,
    TINY_TOKENS,
    TITLE_FIELDS,
    URL_FIELDS,
    Finding,
    as_text,
    distribution,
    est_tokens,
    jaccard,
    normalize_text,
    pct,
    pick_field,
    shingles,
    words,
)

DEFAULT_SAMPLE_SIZE = 8000
# Histogram edges in tokens. Open-ended top bucket.
_HIST_EDGES = [0, 50, 150, 300, 600, 1000, 2000]
# Near-duplicate detection is O(sample); cap the docs it scans to bound cost.
_NEAR_DUP_MAX_DOCS = 6000
_NEAR_DUP_PERMS = 12
_NEAR_DUP_BANDS = 4  # 4 bands × 3 rows
_NEAR_DUP_THRESHOLD = 0.8


@dataclass
class ChunkQualityReport:
    score: int
    total_docs: int
    sample_size: int          # docs actually analysed
    requested_sample: int
    fields: dict = field(default_factory=dict)
    families: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    # Per-pass LLM/embedding usage totals (extended passes only), serialized.
    usage: dict = field(default_factory=dict)
    # The sampled docs, kept in memory so extended passes reuse the sample
    # instead of re-reading the index. Never serialized.
    docs: list[dict] = field(default_factory=list, repr=False)

    def summary(self) -> dict:
        by_sev = Counter(f.severity for f in self.findings)
        return {
            "score": self.score,
            "sample_size": self.sample_size,
            "total_docs": self.total_docs,
            "findings_total": len(self.findings),
            "findings_by_severity": dict(by_sev),
            "critical": by_sev.get("critical", 0),
            "warn": by_sev.get("warn", 0),
            "info": by_sev.get("info", 0),
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "score": self.score,
            "total_docs": self.total_docs,
            "sample_size": self.sample_size,
            "requested_sample": self.requested_sample,
            "fields": self.fields,
            "families": self.families,
            "findings": [f.to_dict() for f in self.findings],
            "usage": self.usage,
        }


def compute_score(findings: list[Finding]) -> int:
    penalty = sum(SEVERITY_WEIGHTS.get(f.severity, 0) for f in findings)
    return max(0, 100 - penalty)


# ── Size & consistency ───────────────────────────────────────────────────────

def analyze_size(
    docs: list[dict], *, text_field: str | None, group_field: str | None
) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    n = len(docs)
    if not text_field or n == 0:
        return {"available": False}, findings

    tokens: list[int] = []
    empty = 0
    by_group: dict[str, list[int]] = defaultdict(list)
    for d in docs:
        t = as_text(d.get(text_field))
        if not t.strip():
            empty += 1
        tok = est_tokens(t)
        tokens.append(tok)
        if group_field:
            by_group[as_text(d.get(group_field)) or "(none)"].append(tok)

    tiny = sum(1 for x in tokens if x < TINY_TOKENS)
    giant = sum(1 for x in tokens if x > GIANT_TOKENS)
    hist = _histogram(tokens)
    groups = {
        g: {"count": len(v), "median": distribution(v)["p50"], "cv": distribution(v)["cv"]}
        for g, v in sorted(by_group.items(), key=lambda kv: -len(kv[1]))[:20]
    }
    dist = distribution(tokens)

    if empty:
        findings.append(Finding(
            family="size", severity="critical" if pct(empty, n) >= 1 else "warn",
            title="Empty chunks",
            message=f"{pct(empty, n)}% of sampled chunks have no body text.",
            count=empty,
        ))
    if pct(tiny, n) >= 10:
        findings.append(Finding(
            family="size", severity="warn",
            title="Many very small chunks",
            message=f"{pct(tiny, n)}% of chunks are under ~{TINY_TOKENS} tokens — often too thin to retrieve on.",
            count=tiny,
        ))
    if pct(giant, n) >= 5:
        findings.append(Finding(
            family="size", severity="warn",
            title="Oversized chunks",
            message=f"{pct(giant, n)}% of chunks exceed ~{GIANT_TOKENS} tokens — risking embedding truncation.",
            count=giant,
        ))
    if dist.get("cv", 0) >= 0.8:
        findings.append(Finding(
            family="size", severity="info",
            title="Inconsistent chunk sizes",
            message=f"Chunk length varies widely (coefficient of variation {dist['cv']}).",
        ))

    metrics = {
        "available": True,
        "group_field": group_field,
        "tokens": dist,
        "histogram": hist,
        "tiny": tiny, "tiny_pct": pct(tiny, n),
        "giant": giant, "giant_pct": pct(giant, n),
        "empty": empty, "empty_pct": pct(empty, n),
        "by_group": groups,
    }
    return metrics, findings


def _histogram(tokens: list[int]) -> list[dict]:
    edges = _HIST_EDGES
    buckets = [0] * len(edges)
    for x in tokens:
        placed = False
        for i in range(len(edges) - 1):
            if edges[i] <= x < edges[i + 1]:
                buckets[i] += 1
                placed = True
                break
        if not placed:
            buckets[-1] += 1
    out = []
    for i in range(len(edges) - 1):
        out.append({"label": f"{edges[i]}–{edges[i + 1]}", "count": buckets[i]})
    out.append({"label": f"{edges[-1]}+", "count": buckets[-1]})
    return out


# ── Duplication & overlap ──────────────────────────────────────────────────-─

def analyze_duplication(
    docs: list[dict], *, text_field: str | None, parent_field: str | None, ordinal_field: str | None
) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    n = len(docs)
    if not text_field or n == 0:
        return {"available": False}, findings

    texts = [as_text(d.get(text_field)) for d in docs]

    # ── Exact duplicates ─────────────────────────────────────────────────────
    by_hash: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(texts):
        norm = normalize_text(t)
        if norm:
            by_hash[hashlib.blake2b(norm.encode("utf-8"), digest_size=16).hexdigest()].append(i)
    clusters = [idxs for idxs in by_hash.values() if len(idxs) > 1]
    dup_chunks = sum(len(c) - 1 for c in clusters)
    dup_ex = [texts[c[0]][:120] for c in sorted(clusters, key=len, reverse=True)[:5]]

    # ── Near-duplicates (MinHash LSH on word-shingles) ───────────────────────
    shingle_sets, scanned = _build_shingles(texts)
    near_pairs = _near_duplicate_pairs(shingle_sets)

    # ── Adjacent overlap within a parent document ────────────────────────────
    adjacency = _adjacency_overlap(docs, texts, parent_field=parent_field, ordinal_field=ordinal_field)

    if pct(dup_chunks, n) >= 1:
        findings.append(Finding(
            family="duplication", severity="warn",
            title="Duplicate chunks",
            message=f"{pct(dup_chunks, n)}% of sampled chunks are exact duplicates of another — wasted recall slots.",
            count=dup_chunks, examples=dup_ex,
        ))
    if pct(near_pairs, max(scanned, 1)) >= 2:
        findings.append(Finding(
            family="duplication", severity="info",
            title="Near-duplicate chunks",
            message=f"{near_pairs} near-duplicate pair(s) (≥{int(_NEAR_DUP_THRESHOLD * 100)}% similar) in the sample.",
            count=near_pairs,
        ))
    if adjacency.get("pairs"):
        if adjacency["zero_overlap_pct"] >= 90 and ordinal_field:
            findings.append(Finding(
                family="duplication", severity="info",
                title="No chunk overlap",
                message="Adjacent chunks rarely share text — the chunker's overlap window may be disabled.",
            ))
        elif adjacency["median_overlap_pct"] >= 50:
            findings.append(Finding(
                family="duplication", severity="warn",
                title="Excessive chunk overlap",
                message=f"Adjacent chunks share a median {adjacency['median_overlap_pct']}% of content — redundant.",
            ))

    metrics = {
        "available": True,
        "exact_duplicates": dup_chunks, "exact_duplicate_pct": pct(dup_chunks, n),
        "exact_clusters": len(clusters),
        "near_duplicate_pairs": near_pairs, "near_dup_scanned": scanned,
        "adjacency": adjacency,
    }
    return metrics, findings


def _build_shingles(texts: list[str]) -> tuple[list[set[str]], int]:
    """Word-shingle sets for up to ``_NEAR_DUP_MAX_DOCS`` evenly-sampled texts."""
    n = len(texts)
    if n <= _NEAR_DUP_MAX_DOCS:
        idxs = range(n)
    else:
        step = n / _NEAR_DUP_MAX_DOCS
        idxs = [int(i * step) for i in range(_NEAR_DUP_MAX_DOCS)]
    sets = [shingles(words(texts[i])) for i in idxs]
    return sets, len(sets)


def _near_duplicate_pairs(shingle_sets: list[set[str]]) -> int:
    """Count distinct doc pairs with Jaccard ≥ threshold via banded MinHash LSH."""
    rows = max(1, _NEAR_DUP_PERMS // _NEAR_DUP_BANDS)
    # Per-doc MinHash signature: min shingle hash under each of N salted hashes.
    sigs: list[list[int]] = []
    for s in shingle_sets:
        if not s:
            sigs.append([0] * _NEAR_DUP_PERMS)
            continue
        sig = []
        for p in range(_NEAR_DUP_PERMS):
            salt = bytes([p])
            sig.append(min(
                int.from_bytes(hashlib.blake2b(sh.encode("utf-8"), key=salt, digest_size=8).digest(), "big")
                for sh in s
            ))
        sigs.append(sig)

    candidates: set[tuple[int, int]] = set()
    for b in range(_NEAR_DUP_BANDS):
        buckets: dict[tuple, list[int]] = defaultdict(list)
        for i, sig in enumerate(sigs):
            if shingle_sets[i]:
                buckets[tuple(sig[b * rows : (b + 1) * rows])].append(i)
        for members in buckets.values():
            if len(members) > 1:
                for a_idx in range(len(members)):
                    for b_idx in range(a_idx + 1, len(members)):
                        candidates.add((members[a_idx], members[b_idx]))

    confirmed = 0
    for i, j in candidates:
        if jaccard(shingle_sets[i], shingle_sets[j]) >= _NEAR_DUP_THRESHOLD:
            confirmed += 1
    return confirmed


def _adjacency_overlap(
    docs: list[dict], texts: list[str], *, parent_field: str | None, ordinal_field: str | None
) -> dict:
    """Overlap between consecutive chunks of the same parent document."""
    if not parent_field:
        return {"available": False, "reason": "no parent id field", "pairs": 0}

    groups: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(docs):
        pid = as_text(d.get(parent_field)).strip()
        if pid:
            groups[pid].append(i)

    overlaps: list[float] = []
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        if ordinal_field:
            idxs = sorted(idxs, key=lambda i: _ordinal(docs[i].get(ordinal_field)))
        for a, b in zip(idxs, idxs[1:]):
            sa, sb = shingles(words(texts[a])), shingles(words(texts[b]))
            if sa and sb:
                overlaps.append(len(sa & sb) / min(len(sa), len(sb)))

    if not overlaps:
        return {"available": True, "ordered": bool(ordinal_field), "pairs": 0,
                "multi_chunk_parents": sum(1 for v in groups.values() if len(v) > 1)}
    dist = distribution([round(o * 100, 2) for o in overlaps])
    zero = sum(1 for o in overlaps if o == 0)
    return {
        "available": True,
        "ordered": bool(ordinal_field),
        "pairs": len(overlaps),
        "multi_chunk_parents": sum(1 for v in groups.values() if len(v) > 1),
        "median_overlap_pct": dist["p50"],
        "mean_overlap_pct": dist["mean"],
        "zero_overlap_pct": pct(zero, len(overlaps)),
    }


def _ordinal(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


# ── Orchestration ──────────────────────────────────────────────────────────-─

async def run_chunk_quality(
    provider: BaseIndexProvider,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    stratify_by: str | None = None,
    progress_cb=None,
) -> ChunkQualityReport:
    """Sample the corpus once and score it across the four families.

    ``progress_cb(processed: int)`` is awaited (when provided) after sampling and
    at the end so a background worker can persist coarse progress. Raises
    ``NotImplementedError`` if the provider can't sample its corpus — the worker
    turns that into a graceful "unavailable" result.
    """
    total_docs = await provider.test_connection()
    docs = await provider.sample_corpus(sample_size, stratify_by=stratify_by)
    if progress_cb is not None:
        await progress_cb(len(docs))

    keys: set[str] = set().union(*(d.keys() for d in docs)) if docs else set()
    id_field = pick_field(keys, ID_FIELDS)
    text_field = pick_field(keys, TEXT_FIELDS)
    title_field = pick_field(keys, TITLE_FIELDS)
    url_field = pick_field(keys, URL_FIELDS)
    parent_field = pick_field(keys, PARENT_FIELDS)
    ordinal_field = pick_field(keys, ORDINAL_FIELDS)
    group_field = pick_field(keys, GROUP_FIELDS)

    findings: list[Finding] = []
    families: dict = {}

    size_m, size_f = analyze_size(docs, text_field=text_field, group_field=group_field)
    families["size"] = size_m
    findings += size_f

    dup_m, dup_f = analyze_duplication(
        docs, text_field=text_field, parent_field=parent_field, ordinal_field=ordinal_field
    )
    families["duplication"] = dup_m
    findings += dup_f

    meta_m, meta_f = await analyze_metadata(
        docs, provider, total_docs,
        text_field=text_field, title_field=title_field, url_field=url_field, parent_field=parent_field,
    )
    families["metadata"] = meta_m
    findings += meta_f

    content_m, content_f = analyze_content(docs, text_field=text_field)
    families["content"] = content_m
    findings += content_f

    boundary_m, boundary_f = analyze_boundaries(
        docs, text_field=text_field, id_field=id_field,
        parent_field=parent_field, ordinal_field=ordinal_field,
    )
    families["boundary"] = boundary_m
    findings += boundary_f

    if progress_cb is not None:
        await progress_cb(len(docs))

    return ChunkQualityReport(
        score=compute_score(findings),
        total_docs=total_docs,
        sample_size=len(docs),
        requested_sample=sample_size,
        fields={
            "id": id_field, "text": text_field, "title": title_field, "url": url_field,
            "parent": parent_field, "ordinal": ordinal_field, "group": group_field,
        },
        families=families,
        findings=findings,
        docs=docs,
    )
