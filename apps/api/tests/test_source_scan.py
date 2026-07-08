"""Tests for the resilient bulk source-scan runner (Data Sources 'Source review')."""

from __future__ import annotations

import httpx
import pytest

from app.index_providers.base import BaseIndexProvider, CorpusDoc
from app.index_providers.source_gaps import page_id_for
from app.services.source_chunks import SourceChunkInput
from app.services.source_scan import ScanItemOutcome, scan_retryable, scan_sources

_URL_A = "https://www.gesetze-im-internet.de/bgb/BJNR001950896.html"
_URL_B = "https://www.gesetze-im-internet.de/hgb/BJNR002190897.html"


class _FakeProvider(BaseIndexProvider):
    """Resolves A and B by URL hash; listing B's chunks raises (a hard failure)."""

    async def test_connection(self):  # pragma: no cover - unused
        return 1

    async def list_partition_keys(self):  # pragma: no cover - unused
        return []

    async def get_partition_distribution(self, key, filters=None):  # pragma: no cover
        return []

    async def sample_documents(self, key, value, n, filters=None):  # pragma: no cover
        return []

    async def lookup_ids(self, key, values):
        hits = {page_id_for(_URL_A): 4, page_id_for(_URL_B): 9}
        return {v: hits[v] for v in values if v in hits}

    async def search_files(self, query, limit):
        return []

    async def list_file_chunks(self, key, value, kind, limit, *, include_text=True):
        if value == page_id_for(_URL_B):
            raise ValueError("index blew up for B")
        return [
            CorpusDoc(id=f"{value}_{o}", ordinal=o) for o in (0, 1, 2, 4)  # gap at 3
        ]


def test_scan_retryable_classifies_throttling():
    assert scan_retryable(httpx.ConnectTimeout("t")) is True
    assert scan_retryable(ValueError("nope")) is False

    class _Throttled(Exception):
        status_code = 429

    class _Busy(Exception):
        status_code = 503

    assert scan_retryable(_Throttled()) is True
    assert scan_retryable(_Busy()) is True


@pytest.mark.asyncio
async def test_scan_sources_collects_ok_and_dlq():
    sources = [
        SourceChunkInput(id="a", name="BGB", html_url=_URL_A),
        SourceChunkInput(id="b", name="HGB", html_url=_URL_B),
        SourceChunkInput(id="c", name="Unknown", html_url="https://nowhere.example/x.html"),
    ]
    outcomes: dict[str, ScanItemOutcome] = {}
    progress: list[tuple[int, int]] = []

    async def on_result(o: ScanItemOutcome) -> None:
        outcomes[o.expectation_id] = o

    async def on_progress(processed: int, failed: int) -> None:
        progress.append((processed, failed))

    await scan_sources(
        _FakeProvider(), sources, concurrency=2, on_result=on_result, on_progress=on_progress
    )

    # A resolves and reports the ordinal gap (missing #3).
    assert outcomes["a"].execution_status == "ok"
    assert outcomes["a"].verdict.resolved is True
    assert outcomes["a"].verdict.missing_chunk_count == 1
    # B errors after (non-retryable) failure → the dead-letter set, not an abort.
    assert outcomes["b"].execution_status == "error"
    assert "B" in (outcomes["b"].error or "")
    # C has no index match — that is a clean verdict, not an error.
    assert outcomes["c"].execution_status == "ok"
    assert outcomes["c"].verdict.resolved is False

    # Progress reached all three with exactly one failure.
    assert progress[-1] == (3, 1)
