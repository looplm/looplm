"""Shared primitives for chunk/metadata quality analysis.

The analysis is split across modules to stay readable; the dataclasses, field
detection, tokenisation and small statistics helpers all the families rely on
live here so neither ``chunk_quality`` nor ``chunk_quality_checks`` has to import
the other (no circular import).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Penalty applied to the 0-100 health score per finding, by severity.
SEVERITY_WEIGHTS = {"critical": 15, "warn": 6, "info": 1}

# Rough char→token ratio (≈4 chars/token for mixed German/English prose). Used
# only for human-friendly size bucketing, not for anything that must be exact.
CHARS_PER_TOKEN = 4
TINY_TOKENS = 40      # below this a chunk rarely carries a retrievable idea
GIANT_TOKENS = 1200   # above this many embedding models truncate

# Field-name candidates, lowercased, in priority order. The index schema is
# external and not guaranteed to use these names, so detection is best-effort
# with sensible fallbacks.
TEXT_FIELDS = ["chunk_text", "content", "text", "body", "chunk", "passage"]
TITLE_FIELDS = ["page_title", "title", "heading", "document_title", "attachment_filename", "name"]
URL_FIELDS = ["page_url", "url", "attachment_url", "source_url", "link", "uri"]
PARENT_FIELDS = ["page_id", "parent_id", "document_id", "doc_id", "source_id", "file_id"]
ORDINAL_FIELDS = [
    "chunk_index", "chunk_number", "chunk_idx", "chunk_no", "ordinal",
    "sequence", "seq", "position", "order", "page_number",
]
GROUP_FIELDS = ["source_type", "content_type", "doc_type", "type", "tags", "sparte", "adapter_tag"]


# Common UTF-8-decoded-as-Latin-1 mojibake signatures (e.g. "Ã¼" where a "ü" should be).
MOJIBAKE_SIGNATURES = ("Ã¤", "Ã¶", "Ã¼", "ÃŸ", "Ã„", "Ã–", "Ãœ", "â€", "Â ", "Ã©", "Ã¨", "ï¿½")
_TAG_RE = re.compile(r"<[a-zA-Z/][^>]{0,40}>")


@dataclass
class ChunkFlags:
    """Per-chunk quality signals — the single-chunk core shared by the corpus content analysis
    (``analyze_content``) and the per-case retrieval diagnosis endpoint."""

    token_estimate: int
    empty: bool
    tiny: bool           # too short to carry a retrievable idea (< TINY_TOKENS)
    giant: bool          # long enough that many embedding models truncate (> GIANT_TOKENS)
    mojibake: bool       # mis-decoded characters, which break German keyword + embedding matching
    table_heavy: bool    # dominated by pipe/tab table markup — poor for retrieval
    markup_heavy: bool   # raw HTML/markup tags left in the text
    missing_embedding: bool  # the chunk has no vector, so it is invisible to vector/hybrid search

    def issues(self) -> list[str]:
        """The flags that are set, as stable slugs (empty list = a clean chunk)."""
        names = (
            "empty", "tiny", "giant", "mojibake", "table_heavy", "markup_heavy", "missing_embedding",
        )
        return [n for n in names if getattr(self, n)]


def score_chunk(text: str, has_vector: bool | None = None) -> ChunkFlags:
    """Quality flags for a single chunk's text.

    ``has_vector`` is the chunk's embedding presence when known (e.g. from a live index fetch);
    ``None`` leaves ``missing_embedding`` unset (we can't tell). Thresholds mirror the corpus-wide
    :func:`app.index_providers.chunk_quality_checks.analyze_content` so a per-chunk verdict and the
    aggregate findings agree.
    """
    t = as_text(text)
    toks = est_tokens(t)
    return ChunkFlags(
        token_estimate=toks,
        empty=not t.strip(),
        tiny=0 < toks < TINY_TOKENS,
        giant=toks > GIANT_TOKENS,
        mojibake=any(sig in t for sig in MOJIBAKE_SIGNATURES),
        table_heavy=bool(t) and (t.count("|") + t.count("\t")) > max(10, len(t) / 40),
        markup_heavy=len(_TAG_RE.findall(t)) > 5,
        missing_embedding=has_vector is False,
    )


@dataclass
class Finding:
    """One actionable observation, mirroring the index-explorer ``MetadataHint``."""

    family: str           # size | duplication | metadata | content
    severity: str         # info | warn | critical
    title: str
    message: str
    count: int = 0        # how many chunks the finding concerns (0 = not countable)
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "count": self.count,
            "examples": self.examples[:5],
        }


def pick_field(keys: set[str], candidates: list[str]) -> str | None:
    """First candidate present among ``keys`` (case-insensitive), or None."""
    lower = {k.lower(): k for k in keys}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def as_text(value) -> str:
    """Coerce a field value to a string ("" for None)."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def est_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def normalize_text(s: str) -> str:
    """Whitespace-collapsed, lowercased form for exact-duplicate hashing."""
    return re.sub(r"\s+", " ", s).strip().lower()


def fold(s: str) -> str:
    """Accent-folded, lowercased, trimmed — for enum-drift comparison."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


_WORD = re.compile(r"\w+", re.UNICODE)


def words(s: str) -> list[str]:
    return _WORD.findall(s.lower())


def shingles(tokens: list[str], k: int = 5, cap: int = 300) -> set[str]:
    """Set of word k-grams (capped) — the unit for near-duplicate/overlap Jaccard."""
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    upper = min(len(tokens) - k + 1, cap)
    return {" ".join(tokens[i : i + k]) for i in range(upper)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list (q in [0,1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return float(sorted_vals[-1])
    return float(sorted_vals[lo] + (sorted_vals[lo + 1] - sorted_vals[lo]) * frac)


def distribution(values: list[int | float]) -> dict:
    """Count/min/p5/p25/p50/p75/p95/max/mean/stdev/cv of a numeric list."""
    if not values:
        return {"count": 0}
    sv = sorted(values)
    n = len(sv)
    mean = sum(sv) / n
    var = sum((v - mean) ** 2 for v in sv) / n
    stdev = var ** 0.5
    return {
        "count": n,
        "min": round(float(sv[0]), 2),
        "p5": round(percentile(sv, 0.05), 2),
        "p25": round(percentile(sv, 0.25), 2),
        "p50": round(percentile(sv, 0.50), 2),
        "p75": round(percentile(sv, 0.75), 2),
        "p95": round(percentile(sv, 0.95), 2),
        "max": round(float(sv[-1]), 2),
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "cv": round(stdev / mean, 3) if mean else 0.0,
    }


def pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 2) if whole else 0.0
