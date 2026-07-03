"""Metadata-completeness and content/parser quality families.

Both take the already-sampled docs; ``analyze_metadata`` additionally uses the
provider's cheap server-side facets to compute *exact* whole-corpus fill rates
for facetable fields (the sample only backs the non-facetable and content
checks).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from app.index_providers.base import BaseIndexProvider
from app.index_providers.chunk_quality_common import (
    Finding,
    as_text,
    fold,
    normalize_text,
    pct,
    score_chunk,
)

# Critical fields a retrievable, attributable chunk should carry.
_CRITICAL = [("text", "chunk body"), ("title", "title"), ("url", "source URL"), ("parent", "parent id")]

_FACET_DRIFT_MAX_CARD = 200  # only hunt enum-drift in reasonably low-card fields


async def analyze_metadata(
    docs: list[dict],
    provider: BaseIndexProvider,
    total_docs: int,
    *,
    text_field: str | None,
    title_field: str | None,
    url_field: str | None,
    parent_field: str | None,
) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    n = len(docs)

    # ── Per-field fill/cardinality: exact via facets where possible ──────────
    field_reports: list[dict] = []
    try:
        pkeys = await provider.list_partition_keys()
    except Exception:
        pkeys = []
    for pk in pkeys:
        try:
            dist = await provider.get_partition_distribution(pk.key)
        except Exception:
            continue
        present = sum(d.doc_count for d in dist)
        capped = len(dist) >= 1000
        # Multivalued facet sums overcount (one doc, many values) — fill from sample.
        if pk.multivalued:
            fill = pct(sum(1 for d in docs if d.get(pk.key)), n) if n else None
            fill_source = "sample"
        else:
            fill = pct(min(present, total_docs), total_docs) if total_docs else None
            fill_source = "facet"
        field_reports.append({
            "field": pk.key,
            "fill_rate": fill,
            "fill_source": fill_source,
            "cardinality": len(dist),
            "cardinality_capped": capped,
            "multivalued": pk.multivalued,
            "top": [{"value": d.value, "count": d.doc_count} for d in dist[:5]],
        })

        # Enum drift: distinct raw values that fold to the same key.
        if not capped and 1 < len(dist) <= _FACET_DRIFT_MAX_CARD:
            groups: dict[str, list[str]] = defaultdict(list)
            for d in dist:
                groups[fold(d.value)].append(d.value)
            drifted = {k: v for k, v in groups.items() if len(v) > 1}
            if drifted:
                ex = [" / ".join(v) for v in list(drifted.values())[:3]]
                findings.append(Finding(
                    family="metadata", severity="info",
                    title=f"Inconsistent values in '{pk.key}'",
                    message=(
                        f"{len(drifted)} group(s) of values differ only by case/accents/"
                        f"whitespace — they fragment this field's facets."
                    ),
                    count=len(drifted), examples=ex,
                ))

    field_reports.sort(key=lambda r: (r["fill_rate"] is None, r["fill_rate"] or 0))

    # ── Critical-field coverage (from the sample; these are often not facetable) ─
    present_fields = {"text": text_field, "title": title_field, "url": url_field, "parent": parent_field}
    critical: dict[str, dict] = {}
    for key, _label in _CRITICAL:
        fname = present_fields[key]
        if not fname:
            critical[key] = {"field": None, "fill_rate": None}
            continue
        have = sum(1 for d in docs if as_text(d.get(fname)).strip())
        fill = pct(have, n)
        critical[key] = {"field": fname, "fill_rate": fill}
        sev = "critical" if (key in ("text", "url") and fill < 95) else "warn"
        if fill < 99 and key != "parent":
            findings.append(Finding(
                family="metadata", severity=sev,
                title=f"Missing {_label_for(key)} on some chunks",
                message=f"{round(100 - fill, 1)}% of sampled chunks have no '{fname}'.",
                count=n - have,
            ))

    # ── Orphans: no URL and no parent id → unattributable chunk ──────────────
    orphans = 0
    if url_field or parent_field:
        for d in docs:
            has_url = bool(as_text(d.get(url_field)).strip()) if url_field else False
            has_parent = bool(as_text(d.get(parent_field)).strip()) if parent_field else False
            if not has_url and not has_parent:
                orphans += 1
        if orphans:
            findings.append(Finding(
                family="metadata", severity="warn",
                title="Orphan chunks",
                message=f"{pct(orphans, n)}% of sampled chunks have neither a URL nor a parent id.",
                count=orphans,
            ))

    metrics = {
        "fields": field_reports,
        "critical": critical,
        "orphans": orphans,
        "orphans_pct": pct(orphans, n),
        "facetable_field_count": len(field_reports),
    }
    return metrics, findings


def _label_for(key: str) -> str:
    return {"text": "body", "title": "title", "url": "source URL", "parent": "parent id"}[key]


def analyze_content(docs: list[dict], *, text_field: str | None) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    n = len(docs)
    if not text_field or n == 0:
        return {"available": False}, findings

    mojibake = table_heavy = markup_heavy = 0
    mojibake_ex: list[str] = []
    line_freq: Counter[str] = Counter()
    for d in docs:
        t = as_text(d.get(text_field))
        if not t:
            continue
        flags = score_chunk(t)  # per-chunk core, shared with the per-case diagnosis endpoint
        if flags.mojibake:
            mojibake += 1
            if len(mojibake_ex) < 5:
                mojibake_ex.append(t[:120])
        if flags.table_heavy:
            table_heavy += 1
        if flags.markup_heavy:
            markup_heavy += 1
        # Boilerplate: substantial lines repeated across many chunks.
        for line in {normalize_text(ln) for ln in t.splitlines()}:
            if len(line) >= 25:
                line_freq[line] += 1

    boiler_cut = max(3, int(0.05 * n))
    boilerplate = [(ln, c) for ln, c in line_freq.most_common(20) if c >= boiler_cut]

    # Embedding coverage: detect a retrievable vector-like field in the sample.
    vec_field = _detect_vector_field(docs)
    if vec_field:
        have_vec = sum(1 for d in docs if isinstance(d.get(vec_field), list) and d.get(vec_field))
        embedding = {"field": vec_field, "coverage_pct": pct(have_vec, n)}
        if pct(have_vec, n) < 99:
            findings.append(Finding(
                family="content", severity="warn",
                title="Chunks missing embeddings",
                message=f"{round(100 - pct(have_vec, n), 1)}% of sampled chunks have an empty '{vec_field}'.",
                count=n - have_vec,
            ))
    else:
        embedding = {"field": None, "coverage_pct": None}

    if mojibake:
        findings.append(Finding(
            family="content", severity="warn" if pct(mojibake, n) >= 0.5 else "info",
            title="Encoding artifacts (mojibake)",
            message=f"{pct(mojibake, n)}% of chunks contain mis-decoded characters (e.g. 'Ã¼' for 'ü').",
            count=mojibake, examples=mojibake_ex,
        ))
    if table_heavy and pct(table_heavy, n) >= 5:
        findings.append(Finding(
            family="content", severity="info",
            title="Table-heavy chunks",
            message=f"{pct(table_heavy, n)}% of chunks are dominated by table markup — often poor for retrieval.",
            count=table_heavy,
        ))
    if markup_heavy and pct(markup_heavy, n) >= 5:
        findings.append(Finding(
            family="content", severity="info",
            title="Raw markup in chunks",
            message=f"{pct(markup_heavy, n)}% of chunks contain raw HTML/markup tags.",
            count=markup_heavy,
        ))
    if boilerplate:
        findings.append(Finding(
            family="content", severity="info",
            title="Repeated boilerplate",
            message=(
                f"{len(boilerplate)} line(s) (headers/footers/disclaimers) repeat across many chunks "
                f"and dilute their embeddings."
            ),
            count=sum(c for _, c in boilerplate),
            examples=[f"{ln[:80]} (×{c})" for ln, c in boilerplate[:5]],
        ))

    metrics = {
        "available": True,
        "mojibake": mojibake, "mojibake_pct": pct(mojibake, n),
        "table_heavy": table_heavy, "table_heavy_pct": pct(table_heavy, n),
        "markup_heavy": markup_heavy, "markup_heavy_pct": pct(markup_heavy, n),
        "boilerplate": [{"line": ln[:120], "count": c} for ln, c in boilerplate[:10]],
        "embedding": embedding,
    }
    return metrics, findings


def _detect_vector_field(docs: list[dict]) -> str | None:
    """A field whose value is a long list of numbers in any sampled doc."""
    for d in docs:
        for key, value in d.items():
            if (
                isinstance(value, list) and len(value) >= 16
                and all(isinstance(x, (int, float)) for x in value[:4])
            ):
                return key
    return None
