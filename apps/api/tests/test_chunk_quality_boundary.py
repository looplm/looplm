"""Unit tests for the boundary-quality family (pure, synthetic docs)."""

from app.index_providers.chunk_quality_boundary import (
    analyze_boundaries,
    boundary_flags,
)


def _doc(text, **extra):
    return {"chunk_text": text, "id": f"c{id(text) % 10000}", **extra}


# ── Per-chunk flags ──────────────────────────────────────────────────────────

def test_clean_chunk_has_no_flags():
    f = boundary_flags("A complete thought. It ends with punctuation.")
    assert f.issues() == []


def test_lowercase_start_is_bad_start():
    f = boundary_flags("und in diesem Fall halbiert sich die Dosis. Danach folgt mehr.")
    assert f.bad_start


def test_continuation_punctuation_is_bad_start():
    assert boundary_flags(", which continues the previous sentence. Fine end.").bad_start


def test_missing_terminal_punctuation_is_bad_end():
    f = boundary_flags("This chunk was cut right in the middle of a")
    assert f.bad_end


def test_closing_quote_after_terminal_is_fine():
    assert not boundary_flags('Er sagte: "Das ist alles."').bad_end


def test_table_row_at_edge_is_mid_table():
    assert boundary_flags("| Dose | 5 mg |\nSome explanation follows here.").mid_table
    assert boundary_flags("Some intro text here.\n| Dose | 5 mg |").mid_table


def test_numbered_start_above_one_is_mid_list():
    f = boundary_flags("3. Add the reagent to the flask.\n4. Stir for five minutes.")
    assert f.mid_list
    assert f.first_list_number == 3
    assert f.last_list_number == 4


def test_list_lines_are_not_bad_end():
    # A numbered/bulleted last line is judged by adjacency, not punctuation.
    assert not boundary_flags("Steps:\n1. Do the thing").bad_end
    assert not boundary_flags("Points:\n- an unpunctuated bullet").bad_end


def test_empty_text_has_no_flags():
    assert boundary_flags("").issues() == []


# ── Corpus analysis ──────────────────────────────────────────────────────────

def test_analyze_unavailable_without_text_field():
    metrics, findings = analyze_boundaries(
        [{"a": 1}], text_field=None, id_field=None, parent_field=None, ordinal_field=None
    )
    assert metrics == {"available": False}
    assert findings == []


def test_severed_steps_across_adjacent_chunks():
    docs = [
        {
            "id": "a", "page_id": "p1", "chunk_index": 0,
            "chunk_text": "Preparation.\n1. Clean the surface first.\n2. Apply the primer coat.",
        },
        {
            "id": "b", "page_id": "p1", "chunk_index": 1,
            "chunk_text": "3. Let it dry for an hour.\n4. Sand it down gently.",
        },
        {
            "id": "c", "page_id": "p2", "chunk_index": 0,
            "chunk_text": "A different page entirely. It has normal prose.",
        },
    ]
    metrics, findings = analyze_boundaries(
        docs, text_field="chunk_text", id_field="id",
        parent_field="page_id", ordinal_field="chunk_index",
    )
    assert metrics["severed_steps"] == 1
    assert metrics["adjacent_pairs_checked"] == 1
    assert metrics["mid_list"] == 1  # chunk b opens on step 3
    assert any(f.title == "Numbered steps severed across chunks" for f in findings)
    assert any(e["issue"] == "severed_steps" for e in metrics["examples"])


def test_bad_end_threshold_raises_warning():
    cut = [_doc("This sentence was chopped before its natural") for _ in range(4)]
    fine = [_doc("A complete sentence with a proper ending.") for _ in range(6)]
    metrics, findings = analyze_boundaries(
        cut + fine, text_field="chunk_text", id_field="id",
        parent_field=None, ordinal_field=None,
    )
    assert metrics["bad_end"] == 4
    assert metrics["bad_end_pct"] == 40.0
    assert any(f.title == "Chunks end mid-content" for f in findings)
    # Without parent/ordinal fields nothing adjacent can be checked.
    assert metrics["adjacent_pairs_checked"] == 0
    assert metrics["severed_steps"] == 0


def test_examples_carry_chunk_ids():
    docs = [{"id": "chunk-1", "chunk_text": "cut off mid sentence without an"}]
    metrics, _ = analyze_boundaries(
        docs, text_field="chunk_text", id_field="id", parent_field=None, ordinal_field=None
    )
    assert metrics["examples"][0]["chunk_id"] == "chunk-1"
