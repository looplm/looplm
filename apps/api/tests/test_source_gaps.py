"""Tests for the wanted-status gap engine and the source-list CSV parser."""

from __future__ import annotations

import pytest

from app.index_providers.base import BaseIndexProvider, CorpusDoc
from app.index_providers.source_gaps import (
    ExpectationInput,
    canonicalize_url,
    classify_shared_urls,
    page_id_for,
    run_gap_analysis,
    title_overlap,
)
from app.services.source_csv import adapter_tag_for, parse_source_csv


# ── URL canonicalization / page_id contract ──────────────────────────────────

def test_page_id_matches_indexer_contract():
    # Verified against the live prod index (2026-06-11): the RDE indexer stores
    # page_id = sha1(canonical_url)[:16]. If this test breaks, the indexer's
    # url-canonicalizer.ts and source_gaps.py have drifted apart.
    url = "https://www.gesetze-im-internet.de/bgb/BJNR001950896.html"
    assert page_id_for(url) == "85f71a1e883bae4b"


def test_canonicalize_strips_fragment_and_ebics_jwt():
    assert (
        canonicalize_url("https://example.de/page.html#anchor")
        == "https://example.de/page.html"
    )
    assert (
        canonicalize_url("https://www.ebics.de/securedl/sdl-abc123xyz/spec.pdf")
        == "https://www.ebics.de/securedl/spec.pdf"
    )


def test_fragment_only_difference_yields_same_page_id():
    a = page_id_for("https://www.gesetze-im-internet.de/bgb/BJNR001950896.html")
    b = page_id_for(
        "https://www.gesetze-im-internet.de/bgb/BJNR001950896.html#BJNG023401377"
    )
    assert a == b


# ── Title matching ───────────────────────────────────────────────────────────

def test_title_overlap_handles_umlauts_and_stopwords():
    name = "Anwendungshilfe für die Marktkommunikation"
    title = "BDEW Anwendungshilfe Marktkommunikation 2026 (PDF)"
    assert title_overlap(name, title) == 1.0


def test_title_overlap_zero_for_unrelated():
    assert title_overlap("Stromsteuergesetz", "Kapazitätsreserveverordnung") == 0.0


# ── Shared-URL (platform entry point) classification ─────────────────────────

def test_shared_urls_detected_across_rows():
    expectations = [
        ExpectationInput(id=str(i), name=f"Doc {i}", html_url="https://platform.de/documents")
        for i in range(3)
    ] + [ExpectationInput(id="x", name="Direct", pdf_url="https://site.de/direct.pdf")]
    shared = classify_shared_urls(expectations)
    assert "https://platform.de/documents" in shared
    assert "https://site.de/direct.pdf" not in shared


# ── End-to-end engine with a fake provider ───────────────────────────────────

class _FakeProvider(BaseIndexProvider):
    """Indexes one direct URL and one platform-published title."""

    def __init__(self):
        self.indexed_url = "https://www.gesetze-im-internet.de/bgb/BJNR001950896.html"

    async def test_connection(self):  # pragma: no cover - unused
        return 1

    async def list_partition_keys(self):  # pragma: no cover - unused
        return []

    async def get_partition_distribution(self, key, filters=None):  # pragma: no cover
        return []

    async def sample_documents(self, key, value, n, filters=None):  # pragma: no cover
        return []

    async def lookup_ids(self, key, values):
        target = page_id_for(self.indexed_url)
        return {target: 42} if target in values else {}

    async def search_documents(self, query, n, filters=None):
        if "utilmd" in query.lower():
            return [
                CorpusDoc(
                    id="abc", title="UTILMD AHB Strom 2.1 Fehlerkorrektur", url="https://x"
                )
            ]
        return []


@pytest.mark.asyncio
async def test_run_gap_analysis_three_strategies():
    expectations = [
        # 1. direct URL → covered_url with chunk count
        ExpectationInput(
            id="1",
            name="BGB",
            html_url="https://www.gesetze-im-internet.de/bgb/BJNR001950896.html",
        ),
        # 2. platform rows sharing one URL → title matching
        ExpectationInput(
            id="2",
            name="UTILMD AHB Strom",
            html_url="https://www.bdew-mako.de/documents",
            adapter_tag="bdew-mako",
        ),
        ExpectationInput(
            id="3",
            name="Vollkommen unbekanntes Dokument XYZQ",
            html_url="https://www.bdew-mako.de/documents",
        ),
        ExpectationInput(
            id="4",
            name="Drittes Plattformdokument ABCD",
            html_url="https://www.bdew-mako.de/documents",
        ),
        # 5. acknowledged gap stays muted
        ExpectationInput(
            id="5",
            name="Bekannte Lücke QWERTZ",
            pdf_url="https://nowhere.example/missing.pdf",
            ack_note="XSD schema, not parseable",
        ),
    ]
    report = await run_gap_analysis(_FakeProvider(), expectations)
    by_id = {r.expectation_id: r for r in report.rows}

    assert by_id["1"].status == "covered_url"
    assert by_id["1"].chunk_count == 42
    assert by_id["2"].status == "covered_title"
    assert by_id["3"].status == "missing"
    assert by_id["4"].status == "missing"
    assert by_id["5"].status == "acked"

    summary = report.summary()
    assert summary["covered"] == 2
    assert summary["missing"] == 2
    assert summary["acked"] == 1


# ── CSV parsing ──────────────────────────────────────────────────────────────

_CSV = """;;;;;;;;;;;;
rde.klar | Scraping externer Quellen;;;;;;;;;;;;
;Notiz: Prio 1;;;;;;;;;;;
;;;;;;;;;;;;
Quelle;Typ;Veröffentlicht von;Sparte / Kategorie;Thema;Hierarchie / Beziehung;Veröffentlichung;Gültig bis;Update-Frequenz;Dateityp;Link (HTML);Link (PDF);Kommentar
Umsatzsteuergesetz (UStG);Gesetz;Deutscher Bundestag;Übergreifend;Steuern;Höchste Ebene;2024;offen;anlassbezogen;HTML, PDF;https://www.gesetze-im-internet.de/ustg_1980/BJNR119530979.html;https://www.gesetze-im-internet.de/ustg_1980/UStG.pdf;Kommentar hier
UTILMD AHB Strom;AHB;BDEW;Strom;MaKo;;2025;offen;;PDF;https://www.bdew-mako.de/documents;;
Zeile ohne Link;Gesetz;X;Y;Z;;;;;;kein-link;;
"""


def test_parse_source_csv():
    result = parse_source_csv(_CSV)
    assert len(result.sources) == 2
    assert result.skipped_rows == 1

    ustg = result.sources[0]
    assert ustg.name == "Umsatzsteuergesetz (UStG)"
    assert ustg.typ == "Gesetz"
    assert ustg.publisher == "Deutscher Bundestag"
    assert ustg.html_url and ustg.html_url.endswith("BJNR119530979.html")
    assert ustg.pdf_url and ustg.pdf_url.endswith("UStG.pdf")
    assert ustg.adapter_tag == "gesetze"
    assert ustg.comment == "Kommentar hier"

    ahb = result.sources[1]
    assert ahb.adapter_tag == "bdew-mako"


def test_parse_source_csv_duplicate_names_get_suffix():
    csv_text = (
        "Quelle;Link (HTML)\n"
        "Doppelt;https://a.de/1.html\n"
        "Doppelt;https://a.de/2.html\n"
    )
    result = parse_source_csv(csv_text)
    assert [s.name for s in result.sources] == ["Doppelt", "Doppelt (2)"]
    assert result.warnings


def test_adapter_tag_fallback():
    assert adapter_tag_for("https://www.siv.de/katalog.pdf") == "weitere-quellen"
    assert adapter_tag_for(None) is None
