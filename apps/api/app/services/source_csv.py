"""Parser for product-owner source lists (semicolon CSV) into expectations.

Tolerant of the real-world shape of these exports: decorative preamble rows
before the header, semicolon delimiters, localized column names, and rows
where only one of the HTML/PDF link columns is filled. The client is
responsible for decoding the file to text (incl. cp1252 legacy exports).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Header-name fragments → expectation field. Matched case-insensitively against
# the detected header row, so minor renames in the export keep working.
_COLUMN_PATTERNS: list[tuple[str, str]] = [
    (r"^quelle", "name"),
    (r"^typ", "typ"),
    (r"ver(ö|oe)ffentlicht", "publisher"),
    (r"sparte", "sparte"),
    (r"^thema", "thema"),
    (r"hierarchie", "hierarchie"),
    (r"update[- ]?frequenz", "update_frequency"),
    (r"link.*html", "html_url"),
    (r"link.*pdf", "pdf_url"),
    (r"kommentar", "comment"),
]

# Default mapping of URL host → indexer adapter tag (chunk `tags` value).
_HOST_TO_ADAPTER: list[tuple[str, str]] = [
    ("gesetze-im-internet.de", "gesetze"),
    ("bdew-mako.de", "bdew-mako"),
    ("bdew.de", "bdew-anwendungshilfen"),
    ("bundesnetzagentur.de", "bundesnetzagentur"),
    ("bsi.bund.de", "bsi-smart-metering"),
    ("ebics.de", "ebics"),
]
_DEFAULT_ADAPTER = "weitere-quellen"


@dataclass
class ParsedSource:
    name: str
    html_url: str | None = None
    pdf_url: str | None = None
    adapter_tag: str | None = None
    typ: str | None = None
    sparte: str | None = None
    thema: str | None = None
    publisher: str | None = None
    hierarchie: str | None = None
    update_frequency: str | None = None
    comment: str | None = None


@dataclass
class ParseResult:
    sources: list[ParsedSource] = field(default_factory=list)
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def adapter_tag_for(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    for fragment, tag in _HOST_TO_ADAPTER:
        if fragment in host:
            return tag
    return _DEFAULT_ADAPTER


def _find_header(rows: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    """Locate the header row and map column index → expectation field."""
    for i, row in enumerate(rows[:20]):
        mapping: dict[int, str] = {}
        for j, cell in enumerate(row):
            cell = cell.strip()
            for pattern, target in _COLUMN_PATTERNS:
                if target not in mapping.values() and re.search(pattern, cell, re.IGNORECASE):
                    mapping[j] = target
                    break
        if "name" in mapping.values() and (
            "html_url" in mapping.values() or "pdf_url" in mapping.values()
        ):
            return i, mapping
    return None


def parse_source_csv(csv_text: str) -> ParseResult:
    result = ParseResult()
    delimiter = ";" if csv_text.count(";") >= csv_text.count(",") else ","
    rows = list(csv.reader(io.StringIO(csv_text), delimiter=delimiter))

    header = _find_header(rows)
    if header is None:
        result.warnings.append(
            "No header row found (need a name column like 'Quelle' plus at least "
            "one link column like 'Link (HTML)')"
        )
        return result
    header_idx, mapping = header

    seen_names: dict[str, int] = {}
    for row in rows[header_idx + 1 :]:
        values = {target: row[j].strip() for j, target in mapping.items() if j < len(row)}
        name = values.get("name") or ""
        html_url = values.get("html_url") or None
        pdf_url = values.get("pdf_url") or None
        if html_url and not html_url.startswith("http"):
            html_url = None
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = None
        if not name or (not html_url and not pdf_url):
            if any(v for v in values.values()):
                result.skipped_rows += 1
            continue

        # Duplicate names get a numbered suffix so each row stays addressable.
        if name in seen_names:
            seen_names[name] += 1
            result.warnings.append(f"Duplicate name '{name}' — imported as '{name} ({seen_names[name]})'")
            name = f"{name} ({seen_names[name]})"
        else:
            seen_names[name] = 1

        result.sources.append(
            ParsedSource(
                name=name[:512],
                html_url=html_url,
                pdf_url=pdf_url,
                adapter_tag=adapter_tag_for(html_url or pdf_url),
                typ=values.get("typ") or None,
                sparte=values.get("sparte") or None,
                thema=values.get("thema") or None,
                publisher=values.get("publisher") or None,
                hierarchie=values.get("hierarchie") or None,
                update_frequency=values.get("update_frequency") or None,
                comment=values.get("comment") or None,
            )
        )
    return result
