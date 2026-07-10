"""Boundary-quality checks for chunk splitting.

The classic chunker failure is cutting mid-content instead of at a semantic
boundary: a chunk that starts mid-sentence, ends without finishing one, slices
a table row in half, or severs step N from step N+1 of a numbered procedure.
Retrieved in isolation such chunks read as fragments.

Pure and synchronous like the size/duplication families: everything operates on
the already-sampled doc list, so it is unit-testable against synthetic docs.
Heuristics are deliberately conservative — a flag means "very likely cut
mid-content", not "possibly imperfect" — because the output feeds a per-run
trend metric that must stay comparable across chunker versions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.index_providers.chunk_quality_common import Finding, as_text, pct

# A chunk starting with one of these characters continues something upstream.
_CONTINUATION_CHARS = ",;)]}»"
# Terminal characters a finished chunk plausibly ends on. Closing quotes and
# brackets after the terminal mark are stripped before this check.
_TERMINAL_CHARS = ".!?:;…"
_CLOSING_CHARS = "\"'”’)]»«"

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+\S")
_BULLET_ITEM_RE = re.compile(r"^\s*[-*•]\s+\S")

# Cap on stored per-issue example snippets.
_MAX_EXAMPLES = 8
_SNIPPET_CHARS = 140


@dataclass
class BoundaryFlags:
    """Boundary signals for a single chunk's text."""

    bad_start: bool          # opens mid-sentence (lowercase or continuation punctuation)
    bad_end: bool            # ends without terminal punctuation (and not a table/list line)
    mid_table: bool          # first or last line is a table row — the table is split
    mid_list: bool           # opens on numbered item > 1 — the list started upstream
    first_list_number: int | None  # numbered-item ordinal on the first line, if any
    last_list_number: int | None   # numbered-item ordinal on the last line, if any

    def issues(self) -> list[str]:
        names = ("bad_start", "bad_end", "mid_table", "mid_list")
        return [n for n in names if getattr(self, n)]


def _first_last_lines(text: str) -> tuple[str, str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "", ""
    return lines[0], lines[-1]


def _list_number(line: str) -> int | None:
    m = _NUMBERED_ITEM_RE.match(line)
    return int(m.group(1)) if m else None


def boundary_flags(text: str) -> BoundaryFlags:
    """Boundary signals for one chunk. Empty text raises no flags."""
    t = as_text(text).strip()
    if not t:
        return BoundaryFlags(False, False, False, False, None, None)

    first_line, last_line = _first_last_lines(t)
    first_number = _list_number(first_line)
    last_number = _list_number(last_line)

    first_char = t[0]
    bad_start = (
        not _TABLE_ROW_RE.match(first_line)
        and first_number is None
        and not _BULLET_ITEM_RE.match(first_line)
        and (first_char.islower() or first_char in _CONTINUATION_CHARS)
    )

    # List and table lines legitimately end without punctuation; those boundaries
    # are judged by mid_table / severed-step adjacency instead.
    end_is_structural = bool(
        _TABLE_ROW_RE.match(last_line)
        or last_number is not None
        or _BULLET_ITEM_RE.match(last_line)
    )
    stripped_end = t.rstrip(_CLOSING_CHARS)
    bad_end = (
        not end_is_structural
        and bool(stripped_end)
        and stripped_end[-1] not in _TERMINAL_CHARS
    )

    return BoundaryFlags(
        bad_start=bad_start,
        bad_end=bad_end,
        mid_table=bool(_TABLE_ROW_RE.match(first_line) or _TABLE_ROW_RE.match(last_line)),
        mid_list=first_number is not None and first_number > 1,
        first_list_number=first_number,
        last_list_number=last_number,
    )


def _ordinal(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _severed_steps(
    docs: list[dict],
    flags: list[BoundaryFlags],
    *,
    parent_field: str | None,
    ordinal_field: str | None,
) -> tuple[int, int, list[int]]:
    """Numbered step N ending a chunk while N+1 opens the parent's next chunk.

    Returns ``(severed_pairs, adjacent_pairs_checked, offender_indexes)``. Needs
    both a parent id and an ordinal so "next chunk" is well-defined; without
    them nothing is checked.
    """
    if not parent_field or not ordinal_field:
        return 0, 0, []

    groups: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(docs):
        pid = as_text(d.get(parent_field)).strip()
        if pid:
            groups[pid].append(i)

    severed = 0
    checked = 0
    offenders: list[int] = []
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        idxs = sorted(idxs, key=lambda i: _ordinal(docs[i].get(ordinal_field)))
        for a, b in zip(idxs, idxs[1:]):
            ord_a, ord_b = _ordinal(docs[a].get(ordinal_field)), _ordinal(docs[b].get(ordinal_field))
            if ord_a == float("inf") or ord_b != ord_a + 1:
                continue
            checked += 1
            last_n, first_n = flags[a].last_list_number, flags[b].first_list_number
            if last_n is not None and first_n is not None and first_n == last_n + 1:
                severed += 1
                offenders.append(a)
    return severed, checked, offenders


def analyze_boundaries(
    docs: list[dict],
    *,
    text_field: str | None,
    id_field: str | None,
    parent_field: str | None,
    ordinal_field: str | None,
) -> tuple[dict, list[Finding]]:
    """Boundary-quality metrics + findings over the sampled docs."""
    findings: list[Finding] = []
    n = len(docs)
    if not text_field or n == 0:
        return {"available": False}, findings

    flags = [boundary_flags(as_text(d.get(text_field))) for d in docs]

    counts = {issue: 0 for issue in ("bad_start", "bad_end", "mid_table", "mid_list")}
    examples: list[dict] = []
    for i, f in enumerate(flags):
        issues = f.issues()
        for issue in issues:
            counts[issue] += 1
        if issues and len(examples) < _MAX_EXAMPLES:
            text = as_text(docs[i].get(text_field)).strip()
            snippet = text[:_SNIPPET_CHARS] if issues[0] in ("bad_start", "mid_list", "mid_table") \
                else text[-_SNIPPET_CHARS:]
            examples.append({
                "chunk_id": as_text(docs[i].get(id_field)) if id_field else "",
                "issue": issues[0],
                "snippet": snippet,
            })

    severed, checked, severed_idxs = _severed_steps(
        docs, flags, parent_field=parent_field, ordinal_field=ordinal_field
    )
    for i in severed_idxs[:3]:
        if len(examples) < _MAX_EXAMPLES + 3:
            text = as_text(docs[i].get(text_field)).strip()
            examples.append({
                "chunk_id": as_text(docs[i].get(id_field)) if id_field else "",
                "issue": "severed_steps",
                "snippet": text[-_SNIPPET_CHARS:],
            })

    if pct(counts["bad_end"], n) >= 15:
        findings.append(Finding(
            family="boundary", severity="warn",
            title="Chunks end mid-content",
            message=(
                f"{pct(counts['bad_end'], n)}% of sampled chunks end without terminal "
                "punctuation. The splitter is likely hitting its size cap mid-sentence."
            ),
            count=counts["bad_end"],
        ))
    if pct(counts["bad_start"], n) >= 15:
        findings.append(Finding(
            family="boundary", severity="warn",
            title="Chunks start mid-sentence",
            message=(
                f"{pct(counts['bad_start'], n)}% of sampled chunks open in lowercase or on "
                "continuation punctuation, so their antecedent lives in the previous chunk."
            ),
            count=counts["bad_start"],
        ))
    if pct(counts["mid_table"], n) >= 1:
        findings.append(Finding(
            family="boundary", severity="info",
            title="Tables split across chunks",
            message=f"{pct(counts['mid_table'], n)}% of chunks start or end inside a table.",
            count=counts["mid_table"],
        ))
    if severed:
        findings.append(Finding(
            family="boundary", severity="info",
            title="Numbered steps severed across chunks",
            message=(
                f"{severed} adjacent chunk pair(s) split a numbered procedure "
                "(step N ends one chunk, step N+1 opens the next)."
            ),
            count=severed,
        ))

    metrics = {
        "available": True,
        "sampled": n,
        "bad_start": counts["bad_start"], "bad_start_pct": pct(counts["bad_start"], n),
        "bad_end": counts["bad_end"], "bad_end_pct": pct(counts["bad_end"], n),
        "mid_table": counts["mid_table"], "mid_table_pct": pct(counts["mid_table"], n),
        "mid_list": counts["mid_list"], "mid_list_pct": pct(counts["mid_list"], n),
        "severed_steps": severed,
        "adjacent_pairs_checked": checked,
        "examples": examples,
    }
    return metrics, findings
