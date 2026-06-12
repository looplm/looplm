"""Wanted-status gap analysis: compare SourceExpectations against the index.

Three matching strategies, tried in order per expectation:

1. **URL hash** — the RDE indexer derives its ``page_id`` deterministically as
   ``sha1(canonical_url)[:16]``, so an expectation with a direct document URL
   can be checked exactly via a bulk ID lookup. An expectation may carry an
   HTML page and a PDF twin of the same document; either one indexed counts as
   covered.
2. **Platform rows** — many expectations legitimately share one entry-point URL
   (a documents portal / landing page the crawler walks). For those the URL
   hash says nothing about the individual document, so the URL check is
   skipped and we fall through to:
3. **Title search** — full-text search for the expectation name (scoped to the
   expectation's ``adapter_tag`` when set), scored by token overlap between
   the name and the best hit's title. Strong overlap ⇒ covered (by title);
   weak overlap ⇒ flagged for human review rather than silently classified.

URL canonicalization MUST stay in sync with the indexer
(``rde-rag-indexer/src/external/url-canonicalizer.ts``): strip URL fragments,
and rewrite ebics' rotating signed-download paths to their stable form.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.index_providers.base import BaseIndexProvider

# A URL shared by at least this many expectations is a platform entry point,
# not an individual document URL.
SHARED_URL_THRESHOLD = 3

# Title-overlap thresholds: >= STRONG ⇒ covered_title, >= WEAK ⇒ review.
STRONG_TITLE_OVERLAP = 0.6
WEAK_TITLE_OVERLAP = 0.3

_TITLE_SEARCH_TOP = 10

_EBICS_SIGNED_PATH = re.compile(r"/securedl/sdl-[^/]+/")

# Tokens that carry no identity for matching German/English document names.
# Accent-folded forms (für→fur, über→uber) because _normalize folds before
# the stopword check.
_STOPWORDS = {
    "der", "die", "das", "des", "dem", "den", "und", "oder", "fur", "fuer",
    "von", "vom", "zur", "zum", "mit", "uber", "ueber", "nach", "bei", "the",
    "and", "for", "aus", "auf", "ein", "eine", "einer", "eines", "im",
    "in", "an", "als", "auch",
}


def canonicalize_url(url: str) -> str:
    """Mirror of the indexer's URL canonicalization (keep in sync!)."""
    url = url.strip()
    url = url.split("#", 1)[0]
    url = _EBICS_SIGNED_PATH.sub("/securedl/", url)
    return url


def page_id_for(url: str) -> str:
    """The indexer's deterministic external page id: sha1(canonical)[:16]."""
    return hashlib.sha1(canonicalize_url(url).encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> list[str]:
    """Lowercased, accent-folded, significant tokens of a document name/title."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("ß", "ss")
    tokens = re.split(r"[^a-z0-9]+", text)
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def title_overlap(name: str, candidate: str) -> float:
    """Fraction of the expectation name's tokens present in a candidate title."""
    name_tokens = _normalize(name)
    if not name_tokens:
        return 0.0
    cand = set(_normalize(candidate))
    hit = sum(1 for t in name_tokens if t in cand)
    return hit / len(name_tokens)


@dataclass
class ExpectationInput:
    """The slice of a SourceExpectation row the engine needs (ORM-free)."""

    id: str
    name: str
    html_url: str | None = None
    pdf_url: str | None = None
    adapter_tag: str | None = None
    ack_note: str | None = None


@dataclass
class GapRowResult:
    expectation_id: str
    name: str
    adapter_tag: str | None
    status: str  # covered_url | covered_title | review | missing | acked
    detail: str
    chunk_count: int = 0
    matched_title: str | None = None
    matched_url: str | None = None
    title_score: float | None = None

    def to_dict(self) -> dict:
        return {
            "expectation_id": self.expectation_id,
            "name": self.name,
            "adapter_tag": self.adapter_tag,
            "status": self.status,
            "detail": self.detail,
            "chunk_count": self.chunk_count,
            "matched_title": self.matched_title,
            "matched_url": self.matched_url,
            "title_score": self.title_score,
        }


@dataclass
class GapReport:
    rows: list[GapRowResult] = field(default_factory=list)

    def summary(self) -> dict:
        by_status = Counter(r.status for r in self.rows)
        return {
            "total": len(self.rows),
            "by_status": dict(by_status),
            "covered": by_status["covered_url"] + by_status["covered_title"],
            "missing": by_status["missing"],
            "review": by_status["review"],
            "acked": by_status["acked"],
        }

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "rows": [r.to_dict() for r in self.rows]}


def classify_shared_urls(expectations: list[ExpectationInput]) -> set[str]:
    """URLs used by >= SHARED_URL_THRESHOLD rows — platform entry points."""
    counts: Counter[str] = Counter()
    for e in expectations:
        for url in (e.html_url, e.pdf_url):
            if url:
                counts[canonicalize_url(url)] += 1
    return {u for u, c in counts.items() if c >= SHARED_URL_THRESHOLD}


async def run_gap_analysis(
    provider: BaseIndexProvider,
    expectations: list[ExpectationInput],
    *,
    id_field: str = "page_id",
    tag_field: str = "tags",
    progress_cb=None,
) -> GapReport:
    """Match every expectation against the index; returns per-row verdicts.

    ``progress_cb(processed: int)`` is awaited periodically when provided, so a
    background worker can persist progress.
    """
    shared = classify_shared_urls(expectations)

    # Strategy 1 prep: bulk-resolve the page_ids of all direct (non-shared) URLs.
    direct_ids: dict[str, str] = {}  # page_id -> canonical url (for detail text)
    for e in expectations:
        for url in (e.html_url, e.pdf_url):
            if url:
                canon = canonicalize_url(url)
                if canon not in shared:
                    direct_ids[page_id_for(url)] = canon
    found_counts = (
        await provider.lookup_ids(id_field, list(direct_ids)) if direct_ids else {}
    )

    report = GapReport()
    for i, e in enumerate(expectations):
        row = await _match_one(provider, e, shared, found_counts, tag_field=tag_field)
        report.rows.append(row)
        if progress_cb is not None and (i + 1) % 10 == 0:
            await progress_cb(i + 1)
    if progress_cb is not None:
        await progress_cb(len(expectations))
    return report


async def _match_one(
    provider: BaseIndexProvider,
    e: ExpectationInput,
    shared: set[str],
    found_counts: dict[str, int],
    *,
    tag_field: str,
) -> GapRowResult:
    # Strategy 1: exact URL-hash hit on either variant.
    direct_urls = [
        u for u in (e.html_url, e.pdf_url) if u and canonicalize_url(u) not in shared
    ]
    for url in direct_urls:
        pid = page_id_for(url)
        count = found_counts.get(pid, 0)
        if count > 0:
            variant = "PDF" if url == e.pdf_url else "HTML"
            return GapRowResult(
                expectation_id=e.id,
                name=e.name,
                adapter_tag=e.adapter_tag,
                status="covered_url",
                detail=f"{variant} variant indexed (page_id {pid})",
                chunk_count=count,
                matched_url=url,
            )

    # Strategy 2/3: platform rows (or direct rows that missed) → title search,
    # first scoped to the expected adapter tag, then globally — a document can
    # legitimately be indexed by a different crawler than the source list assumed
    # (e.g. a bdew.de Anwendungshilfe that is also published on the MaKo platform).
    async def _best_match(filters: dict[str, str] | None) -> tuple[float, str | None, str | None]:
        score_best, title_best, url_best = 0.0, None, None
        try:
            docs = await provider.search_documents(e.name, _TITLE_SEARCH_TOP, filters)
        except NotImplementedError:
            docs = []
        for d in docs:
            for candidate in filter(None, (d.title, d.url)):
                score = title_overlap(e.name, candidate)
                if score > score_best:
                    score_best, title_best, url_best = score, d.title, d.url
        return score_best, title_best, url_best

    scoped = {tag_field: e.adapter_tag} if e.adapter_tag else None
    best_score, best_title, best_url = await _best_match(scoped)
    cross_tag = False
    if scoped is not None and best_score < STRONG_TITLE_OVERLAP:
        global_score, global_title, global_url = await _best_match(None)
        if global_score > best_score:
            best_score, best_title, best_url = global_score, global_title, global_url
            cross_tag = best_score >= WEAK_TITLE_OVERLAP

    if e.ack_note:
        status, detail = "acked", f"Acknowledged: {e.ack_note}"
    elif best_score >= STRONG_TITLE_OVERLAP:
        status = "covered_title"
        detail = f"Title match ({best_score:.0%} token overlap)"
        if cross_tag:
            detail += f" — found under a different tag than expected '{e.adapter_tag}'"
    elif best_score >= WEAK_TITLE_OVERLAP:
        status = "review"
        detail = f"Weak title match ({best_score:.0%}) — verify manually"
        if cross_tag:
            detail += f" (found outside expected tag '{e.adapter_tag}')"
    else:
        status = "missing"
        checked = (
            f"checked page_ids of {len(direct_urls)} direct URL(s) and"
            if direct_urls
            else "platform row;"
        )
        detail = f"No match: {checked} no title hit in index"
    return GapRowResult(
        expectation_id=e.id,
        name=e.name,
        adapter_tag=e.adapter_tag,
        status=status,
        detail=detail,
        matched_title=best_title,
        matched_url=best_url,
        title_score=round(best_score, 3) if best_score else None,
    )


def build_markdown_report(results: dict, provider_name: str, generated_at: str) -> str:
    """Render a persisted gap-run ``results`` blob as an actionable report."""
    summary = results.get("summary", {})
    rows = results.get("rows", [])
    by_status = summary.get("by_status", {})

    def rows_with(status: str) -> list[dict]:
        return [r for r in rows if r.get("status") == status]

    lines: list[str] = []
    lines.append(f"# Source coverage gap report — {provider_name}")
    lines.append("")
    lines.append(f"Generated: {generated_at} · Expectations: {summary.get('total', 0)}")
    lines.append("")
    lines.append("| Status | Count | Meaning |")
    lines.append("|---|---:|---|")
    lines.append(
        f"| ✅ covered (URL) | {by_status.get('covered_url', 0)} | "
        "exact page_id hit for the source's own URL |"
    )
    lines.append(
        f"| ✅ covered (title) | {by_status.get('covered_title', 0)} | "
        "strong title match within the source's adapter tag |"
    )
    lines.append(
        f"| 🟡 review | {by_status.get('review', 0)} | weak match — verify manually |"
    )
    lines.append(f"| ❌ missing | {by_status.get('missing', 0)} | no evidence in the index |")
    lines.append(
        f"| ✔ acknowledged | {by_status.get('acked', 0)} | known/intentional, muted |"
    )
    lines.append("")

    # Per-adapter-tag breakdown so the indexer owner sees which crawler to fix.
    tags = sorted({r.get("adapter_tag") or "(untagged)" for r in rows})
    lines.append("## Coverage by adapter tag")
    lines.append("")
    lines.append("| Adapter tag | Covered | Review | Missing | Acked |")
    lines.append("|---|---:|---:|---:|---:|")
    for tag in tags:
        trs = [r for r in rows if (r.get("adapter_tag") or "(untagged)") == tag]
        c = Counter(r["status"] for r in trs)
        lines.append(
            f"| `{tag}` | {c['covered_url'] + c['covered_title']} | "
            f"{c['review']} | {c['missing']} | {c['acked']} |"
        )
    lines.append("")

    if rows_with("missing"):
        lines.append("## ❌ Missing sources (action needed in the indexer)")
        lines.append("")
        for r in rows_with("missing"):
            lines.append(f"- **{r['name']}** (`{r.get('adapter_tag') or 'untagged'}`) — {r['detail']}")
        lines.append("")

    if rows_with("review"):
        lines.append("## 🟡 Needs review (weak matches)")
        lines.append("")
        lines.append("| Source | Best match in index | Overlap |")
        lines.append("|---|---|---:|")
        for r in rows_with("review"):
            score = f"{(r.get('title_score') or 0) * 100:.0f}%"
            lines.append(f"| {r['name']} | {r.get('matched_title') or '—'} | {score} |")
        lines.append("")

    if rows_with("acked"):
        lines.append("## ✔ Acknowledged (intentional gaps)")
        lines.append("")
        for r in rows_with("acked"):
            lines.append(f"- {r['name']} — {r['detail']}")
        lines.append("")

    return "\n".join(lines)
