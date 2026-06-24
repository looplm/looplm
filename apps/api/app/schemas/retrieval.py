"""Pydantic schemas for the Retrieval section — the aggregate pipeline flow chart.

The pipeline view paints a *fixed* canonical retrieval topology (query → expansion →
embeddings → hybrid search → rerank → filter → context → generation → judge) and
annotates each node with stats rolled up across many traces. The topology is fixed so
the chart stays legible and comparable across projects; whether a given stage is actually
observable in the traces is carried per-node via ``status``.
"""

from __future__ import annotations

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


# --- Chunk-level human relevance labeling ----------------------------------------


class ChunkForLabeling(BaseModel):
    """A retrieved chunk presented to a human for a relevant/not judgment."""

    chunk_id: str | None = None
    title: str | None = None
    url: str | None = None
    content_preview: str | None = None
    score: float | None = None
    rank: int
    # Current label, or None when this chunk has not been judged yet.
    relevant: bool | None = None


class LabelingCase(BaseModel):
    test_id: str
    input: str | None = None
    chunks: list[ChunkForLabeling] = Field(default_factory=list)
    labeled_count: int = 0
    relevant_count: int = 0


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


class ChunkLabelUpsert(BaseModel):
    test_id: str
    chunk_id: str
    relevant: bool
    content_preview: str | None = None
    url: str | None = None
    title: str | None = None


class ChunkLabelBatch(BaseModel):
    labels: list[ChunkLabelUpsert] = Field(default_factory=list)


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
    cases: list[RetrievalCaseMetrics] = Field(default_factory=list)
