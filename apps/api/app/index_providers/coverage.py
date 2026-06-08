"""Pure coverage computation: corpus partitions × existing test cases.

Kept free of DB/IO so it is trivially unit-testable. The worker
(`routers/rag_coverage_worker.py`) loads the distribution and test cases, calls
:func:`compute_coverage`, and serialises the result to JSON.

"Coverage" of a partition value = how many test cases would exercise documents
carrying that value, judged by the test case's own scoping fields. Which field
expresses a given partition key is decided by :func:`coverage_fields_for`, with
sensible defaults and a generic fallback so arbitrary backends still work.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.index_providers.base import PartitionValue

# Partition key (lowercased) → which TestCase list/dict fields express it.
# A test case "covers" a value when the value appears in any mapped field.
_LIST_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "tags": ("tag_filter", "tags"),
    "tag": ("tag_filter", "tags"),
    "source_type": ("expected_source_types",),
    "source_types": ("expected_source_types",),
    "team": ("team_filter",),
    "page_url": ("expected_page_urls", "expected_sources"),
    "attachment_url": ("expected_page_urls", "expected_sources"),
    "url": ("expected_page_urls", "expected_sources"),
    "source": ("expected_sources", "expected_page_urls"),
}


@dataclass
class CoverageRow:
    value: str
    indexed_count: int
    covering_cases: int
    covered: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "indexed_count": self.indexed_count,
            "covering_cases": self.covering_cases,
            "covered": self.covered,
        }


@dataclass
class CoverageReport:
    partition_key: str
    total_values: int
    covered_values: int
    total_docs: int
    covered_docs: int
    value_coverage_pct: float
    doc_coverage_pct: float
    rows: list[CoverageRow] = field(default_factory=list)
    issues: list["PartitionIssue"] = field(default_factory=list)

    @property
    def gaps(self) -> list[CoverageRow]:
        return [r for r in self.rows if not r.covered]

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_key": self.partition_key,
            "total_values": self.total_values,
            "covered_values": self.covered_values,
            "total_docs": self.total_docs,
            "covered_docs": self.covered_docs,
            "value_coverage_pct": round(self.value_coverage_pct, 1),
            "doc_coverage_pct": round(self.doc_coverage_pct, 1),
            "rows": [r.to_dict() for r in self.rows],
            "issues": [i.to_dict() for i in self.issues],
        }


def coverage_fields_for(partition_key: str) -> tuple[str, ...]:
    """List-valued TestCase fields whose membership covers this partition key."""
    return _LIST_FIELD_MAP.get(partition_key.lower(), ())


def _norm_set(values: Any) -> set[str]:
    """Lowercased, stripped set of string members from a list-ish field."""
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(v).strip().lower() for v in values if v is not None and str(v).strip()}


def _case_covers(partition_key: str, value: str, test_case: dict[str, Any]) -> bool:
    """True if ``test_case`` scopes to documents carrying ``value`` for the key."""
    needle = value.strip().lower()
    if not needle:
        return False

    list_fields = coverage_fields_for(partition_key)
    if list_fields:
        for fname in list_fields:
            if needle in _norm_set(test_case.get(fname)):
                return True
        return False

    # Generic fallback for arbitrary keys: a context_filter equal to the value,
    # then a tag_filter membership as a last resort.
    ctx = test_case.get("context_filters")
    if isinstance(ctx, dict):
        cv = ctx.get(partition_key)
        if cv is not None and str(cv).strip().lower() == needle:
            return True
    return needle in _norm_set(test_case.get("tag_filter"))


def compute_coverage(
    partition_key: str,
    distribution: Sequence[PartitionValue],
    test_cases: Sequence[dict[str, Any]],
    *,
    min_covering_cases: int = 1,
) -> CoverageReport:
    """Compute per-value coverage of a corpus partition against test cases."""
    rows: list[CoverageRow] = []
    for pv in distribution:
        covering = sum(1 for tc in test_cases if _case_covers(partition_key, pv.value, tc))
        rows.append(
            CoverageRow(
                value=pv.value,
                indexed_count=pv.doc_count,
                covering_cases=covering,
                covered=covering >= min_covering_cases,
            )
        )
    rows.sort(key=lambda r: r.indexed_count, reverse=True)

    total_values = len(rows)
    covered_values = sum(1 for r in rows if r.covered)
    total_docs = sum(r.indexed_count for r in rows)
    covered_docs = sum(r.indexed_count for r in rows if r.covered)

    return CoverageReport(
        partition_key=partition_key,
        total_values=total_values,
        covered_values=covered_values,
        total_docs=total_docs,
        covered_docs=covered_docs,
        value_coverage_pct=(100.0 * covered_values / total_values) if total_values else 0.0,
        doc_coverage_pct=(100.0 * covered_docs / total_docs) if total_docs else 0.0,
        rows=rows,
        issues=detect_partition_issues(rows),
    )


# ── Partition-quality detection ─────────────────────────────────
#
# Surfaces likely *index* problems (mislabeled / fragmented / junk partition
# values) so they aren't mistaken for genuine coverage gaps. Pure + stateless;
# acknowledgements (the "this is intentional" memory) live in the DB and are
# applied by the caller/UI, not here.

# A bucket is a "tiny" stray only when it's far below the *typical* bucket size
# (a fraction of the median). Median-relative (not absolute) so a uniformly
# small distribution isn't flagged wholesale, and a small/uniform median yields
# a sub-1 threshold that integer counts never fall under.
TINY_MEDIAN_RATIO = 0.02
_PLACEHOLDER_VALUES = {
    "unknown", "none", "null", "n/a", "na", "-", "—", "undefined", "tbd", "test", "default",
}
_PAREN_RE = re.compile(r"\([^)]*\)")


@dataclass
class PartitionIssue:
    kind: str  # "near_duplicate" | "tiny_bucket" | "empty_or_placeholder"
    value: str
    severity: str  # "high" | "medium" | "low"
    message: str
    related_values: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "severity": self.severity,
            "message": self.message,
            "related_values": self.related_values,
        }


def _normalize_label(value: str) -> str:
    """Collapse a partition value to its comparable core for duplicate detection."""
    v = _PAREN_RE.sub(" ", value.lower())  # drop "(finanzbuchhaltung)" etc.
    v = re.sub(r"[^a-z0-9]+", " ", v)  # punctuation → space (case/spacing variants)
    return " ".join(v.split())


def detect_partition_issues(rows: Sequence[CoverageRow]) -> list[PartitionIssue]:
    """Flag partition values that likely indicate an index-quality problem.

    Each value yields at most one issue, with precedence
    near_duplicate > empty_or_placeholder > tiny_bucket.
    """
    issues: list[PartitionIssue] = []
    flagged: set[str] = set()

    # 1) near_duplicate — cluster by normalized label; flag non-canonical members.
    clusters: dict[str, list[CoverageRow]] = {}
    for r in rows:
        norm = _normalize_label(r.value)
        if norm:
            clusters.setdefault(norm, []).append(r)
    for members in clusters.values():
        if len(members) < 2:
            continue
        canonical = max(members, key=lambda r: r.indexed_count)
        for r in members:
            if r.value == canonical.value:
                continue
            issues.append(
                PartitionIssue(
                    kind="near_duplicate",
                    value=r.value,
                    severity="high",
                    message=(
                        f"Likely the same as '{canonical.value}' — the index may need cleanup "
                        f"(inconsistent labels for one category)."
                    ),
                    related_values=[canonical.value],
                )
            )
            flagged.add(r.value)

    # 2) empty_or_placeholder
    for r in rows:
        if r.value in flagged:
            continue
        stripped = r.value.strip()
        if not stripped or stripped.lower() in _PLACEHOLDER_VALUES:
            issues.append(
                PartitionIssue(
                    kind="empty_or_placeholder",
                    value=r.value,
                    severity="medium",
                    message="Empty or placeholder partition value — likely missing/junk metadata.",
                )
            )
            flagged.add(r.value)

    # 3) tiny_bucket — only meaningful with ≥3 values and a real size spread.
    counts = [r.indexed_count for r in rows]
    if len(rows) >= 3 and counts:
        median = statistics.median(counts)
        threshold = TINY_MEDIAN_RATIO * median
        for r in rows:
            if r.value in flagged:
                continue
            if r.indexed_count < threshold:
                issues.append(
                    PartitionIssue(
                        kind="tiny_bucket",
                        value=r.value,
                        severity="low",
                        message=(
                            f"Only {r.indexed_count} chunk(s) — far below the typical bucket "
                            f"(median {int(median)}); possible stray or mislabel."
                        ),
                    )
                )
                flagged.add(r.value)

    return issues
