"""Pydantic schemas for the Retrieval section — the aggregate pipeline flow chart.

The pipeline view paints a *fixed* canonical retrieval topology (query → expansion →
embeddings → hybrid search → rerank → filter → context → generation → judge) and
annotates each node with stats rolled up across many traces. The topology is fixed so
the chart stays legible and comparable across projects; whether a given stage is actually
observable in the traces is carried per-node via ``status``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RetrievalMetric(BaseModel):
    """A single preformatted stat shown on a pipeline node.

    Formatting is done server-side so the chart component stays a thin renderer; ``tone``
    drives the colour accent (``good``/``warn``/``bad``/``muted``).
    """

    label: str
    value: str
    hint: str | None = None
    tone: str | None = None  # good | warn | bad | muted


class RetrievalPipelineNode(BaseModel):
    id: str
    label: str
    sublabel: str | None = None
    # Cluster key for visually grouping co-located stages (e.g. the keyword/vector/RRF
    # nodes that make up "hybrid search"). Used for tinting, not React Flow nesting.
    group: str | None = None
    # Provider the stage runs inside, when known — e.g. "Azure AI Search" for the hybrid
    # cluster *and* the reranker, which share one server-side call but are distinct stages.
    provider: str | None = None
    # active = observed in traces; no_data = canonical stage with no signal logged.
    status: str = "active"
    description: str | None = None
    metrics: list[RetrievalMetric] = Field(default_factory=list)


class RetrievalPipelineEdge(BaseModel):
    source: str
    target: str
    label: str | None = None
    kind: str = "main"  # main | fallback


class RetrievalPipelineResponse(BaseModel):
    """Aggregate retrieval pipeline derived from a window of traces.

    ``available`` is False when no RAG traces were found in the window, so the page can
    show an empty state instead of a chart of zeros.
    """

    available: bool = False
    traces_analyzed: int = 0
    rag_traces: int = 0
    nodes: list[RetrievalPipelineNode] = Field(default_factory=list)
    edges: list[RetrievalPipelineEdge] = Field(default_factory=list)
    span_names: dict[str, str] = Field(default_factory=dict)


# --- Quantitative retrieval-quality metrics (eval-run based) ---------------------


class RetrievalTargets(BaseModel):
    """Per-project pass/fail bars for the retrieval-quality metrics (fractions 0-1)."""

    recall: float = 0.80
    ndcg: float = 0.70
    mrr: float = 0.70
    hit_rate: float = 0.95
    precision: float = 0.50


class RetrievalCaseMetrics(BaseModel):
    """Per-test-case retrieval quality, for the drill-down table."""

    test_id: str
    input: str | None = None
    expected_count: int = 0
    retrieved_count: int = 0
    recall_at_k: dict[str, float] = Field(default_factory=dict)
    ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    mrr: float | None = None
    # 1-indexed rank of the first relevant doc retrieved, or null if it never surfaced.
    first_relevant_rank: int | None = None
    hit: bool = False
    missing_urls: list[str] = Field(default_factory=list)
    # Incomplete-judgment-safe metrics — populated only on the chunk-label path (they need
    # a judged-non-relevant set). Null/empty on the URL path, which assumes complete truth.
    bpref: float | None = None
    condensed_ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    # Risk slice (broad | safety | adversarial), when assigned to this test case.
    slice: str | None = None


class SliceMetrics(BaseModel):
    """Macro-averaged metrics for one risk slice within a run.

    A relevant chunk missed at deep rank only matters on the safety/adversarial slices, so
    aggregate scores are reported per slice rather than blended into one number.
    """

    slice: str
    case_count: int = 0
    recall_at_k: dict[str, float] = Field(default_factory=dict)
    ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    bpref: float | None = None


# --- Chunk-level human relevance labeling ----------------------------------------


class ChunkForLabeling(BaseModel):
    """A retrieved chunk presented to a human for a relevant/not judgment."""

    chunk_id: str | None = None
    title: str | None = None
    url: str | None = None
    # Full chunk text (the thing being judged) plus a short preview for the collapsed row.
    content: str | None = None
    content_preview: str | None = None
    # Where this passage sits in the source document.
    heading_context: str | None = None
    pdf_page_number: int | None = None
    score: float | None = None
    rank: int
    # Current label, or None when this chunk has not been judged yet.
    relevant: bool | None = None
    # Display name of who made the current label, when known.
    labeled_by: str | None = None


class LabelingCase(BaseModel):
    test_id: str
    input: str | None = None
    chunks: list[ChunkForLabeling] = Field(default_factory=list)
    labeled_count: int = 0
    relevant_count: int = 0
    # Manual "labeling complete" flag (human decision, not derived from counts).
    complete: bool = False
    # Risk slice (broad | safety | adversarial), when assigned.
    slice: str | None = None
    # Distinct people who have labeled chunks in this case.
    labelers: list[str] = Field(default_factory=list)


class LabelingRunResponse(BaseModel):
    """Retrieved chunks for an eval run, grouped by case, ready for labeling.

    ``available`` is False when no case in the run captured retrieved chunks (e.g. the
    target response carried no structured sources).
    """

    available: bool = False
    run_id: str | None = None
    run_name: str | None = None
    total_cases: int = 0
    labelable_cases: int = 0
    cases: list[LabelingCase] = Field(default_factory=list)


class PooledChunkForLabeling(BaseModel):
    """A pooled candidate chunk — surfaced by one or more retrieval heads, ready to judge.

    Unlike :class:`ChunkForLabeling` (which mirrors a single ranked retrieval) this carries
    ``provenance`` — the heads that found it (``trace``, ``keyword``, ``vector``, ``hybrid``) —
    so the labeler sees *why* a chunk is in the pool. ``score`` is a best-effort backend score
    and is not comparable across heads.
    """

    chunk_id: str
    title: str | None = None
    url: str | None = None
    content_preview: str | None = None
    score: float | None = None
    provenance: list[str] = Field(default_factory=list)
    relevant: bool | None = None
    labeled_by: str | None = None


class LabelingPoolResponse(BaseModel):
    """The deduped candidate pool for one test case, built from the index + trace captures.

    ``heads_ran`` lists the retrieval heads that contributed (``trace`` plus whichever index
    modes ran); ``heads_failed`` maps a head to why it produced nothing (e.g. the index has no
    vector field), so the UI can be honest about partial pools. ``provider_connected`` is False
    when the project has no index provider — then the pool is just the trace chunks.
    """

    test_id: str
    input: str | None = None
    provider_connected: bool = False
    pool_size: int = 0
    heads_ran: list[str] = Field(default_factory=list)
    heads_failed: dict[str, str] = Field(default_factory=dict)
    chunks: list[PooledChunkForLabeling] = Field(default_factory=list)


class ChunkLabelUpsert(BaseModel):
    test_id: str
    chunk_id: str
    relevant: bool
    content_preview: str | None = None
    url: str | None = None
    title: str | None = None


class ChunkLabelBatch(BaseModel):
    labels: list[ChunkLabelUpsert] = Field(default_factory=list)


class LabelingStatusUpdate(BaseModel):
    test_id: str
    complete: bool


class LabelingSliceUpdate(BaseModel):
    test_id: str
    # broad | safety | adversarial, or null to clear (back to the broad default).
    slice: str | None = None


# --- Inter-annotator agreement + adjudication ------------------------------------


class AnnotatorAgreement(BaseModel):
    name: str
    judged_count: int = 0


class PairwiseKappa(BaseModel):
    a: str
    b: str
    kappa: float
    n: int  # chunks both annotators judged


class VoteEntry(BaseModel):
    labeler: str
    relevant: bool


class Disagreement(BaseModel):
    test_id: str
    chunk_id: str
    title: str | None = None
    votes: list[VoteEntry] = Field(default_factory=list)
    # Current adjudicated gold verdict, or null if not yet resolved.
    gold: bool | None = None


class AgreementReport(BaseModel):
    """Inter-annotator agreement over the chunks judged by more than one person.

    ``available`` is False when fewer than two annotators have overlapping judgments — kappa
    needs a double-judged sample. ``average_kappa`` is the mean of the pairwise scores.
    """

    available: bool = False
    annotators: list[AnnotatorAgreement] = Field(default_factory=list)
    judged_items: int = 0
    overlap_count: int = 0
    double_judged_pct: float = 0.0
    pairwise: list[PairwiseKappa] = Field(default_factory=list)
    average_kappa: float | None = None
    disagreements: list[Disagreement] = Field(default_factory=list)


class GoldUpdate(BaseModel):
    test_id: str
    chunk_id: str
    relevant: bool


class ChunkMetadataResponse(BaseModel):
    """All index fields for a chunk, fetched live from the connected index provider."""

    provider_connected: bool = False
    available: bool = False
    fields: dict[str, Any] | None = None


class RetrievalRunMetrics(BaseModel):
    """Retrieval-quality metrics for an eval run, macro-averaged across cases.

    ``available`` is False when the run has no cases carrying both ground-truth URLs
    and captured retrieval — measuring recall needs labeled relevance. Macro (not micro)
    averaging so every query counts equally regardless of how many docs it expects.
    """

    available: bool = False
    run_id: str | None = None
    run_name: str | None = None
    total_cases: int = 0
    evaluated_cases: int = 0
    ks: list[int] = Field(default_factory=list)
    recall_at_k: dict[str, float] = Field(default_factory=dict)
    precision_at_k: dict[str, float] = Field(default_factory=dict)
    hit_rate_at_k: dict[str, float] = Field(default_factory=dict)
    ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    mrr: float | None = None
    # Incomplete-judgment-safe roll-ups (chunk-label path only); see RetrievalCaseMetrics.
    bpref: float | None = None
    condensed_ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    # Per-risk-slice breakdown (empty when no slices are assigned). Reported separately so a
    # deep-rank miss on the safety slice isn't averaged away by the broad slice.
    slices: list[SliceMetrics] = Field(default_factory=list)
    cases: list[RetrievalCaseMetrics] = Field(default_factory=list)
