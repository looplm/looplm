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
    precision_at_k: dict[str, float] = Field(default_factory=dict)
    hit_rate_at_k: dict[str, float] = Field(default_factory=dict)
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
    # Current graded relevance label 0..3, or None when this chunk has not been judged yet.
    relevance: int | None = None
    # Display name of who made the current label, when known.
    labeled_by: str | None = None
    # The AI judge's graded relevance 0..3 for this chunk, when it has judged it. Read-only;
    # shown alongside the human grade as a second opinion, not merged into ``relevance``.
    ai_relevance: int | None = None


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


class LabelingDatasetOption(BaseModel):
    """A dataset the labeling page can switch to (for the picker)."""

    id: str
    name: str
    test_count: int = 0


class LabelingRunResponse(BaseModel):
    """A dataset's test cases, grouped per case, ready for labeling.

    Cases come from the selected dataset's test cases (not eval runs); the chunks to judge
    are pooled live from the connected index per case. ``available`` is False when the
    project has no dataset with test cases. ``datasets`` lists every dataset for the picker;
    ``dataset_id`` / ``dataset_name`` identify the one these cases belong to.
    """

    available: bool = False
    dataset_id: str | None = None
    dataset_name: str | None = None
    datasets: list[LabelingDatasetOption] = Field(default_factory=list)
    total_cases: int = 0
    labelable_cases: int = 0
    cases: list[LabelingCase] = Field(default_factory=list)


class PooledChunkForLabeling(BaseModel):
    """A pooled candidate chunk — surfaced by one or more retrieval heads, ready to judge.

    Unlike :class:`ChunkForLabeling` (which mirrors a single ranked retrieval) this carries
    ``provenance`` — the heads that found it (``trace``, ``keyword``, ``vector``, ``hybrid``) —
    so the labeler sees *why* a chunk is in the pool, and ``ranks`` — the 1-indexed rank the
    chunk held in each of those heads — so they see *where* each method ranked it. ``score`` is
    a best-effort backend score and is not comparable across heads.
    """

    chunk_id: str
    title: str | None = None
    url: str | None = None
    content_preview: str | None = None
    score: float | None = None
    provenance: list[str] = Field(default_factory=list)
    # head -> 1-indexed rank in that head's results (e.g. {"vector": 3, "hybrid": 2}). The
    # pseudo-head "agentic" holds the best rank any planned sub-query gave the chunk.
    ranks: dict[str, int] = Field(default_factory=dict)
    # Agentic sub-queries (from the LLM planner) that surfaced this chunk, when any did.
    agentic_queries: list[str] = Field(default_factory=list)
    # Current graded relevance label 0..3, or None when not yet judged.
    relevance: int | None = None
    labeled_by: str | None = None
    # The AI judge's graded relevance 0..3 for this chunk, when it has judged it (read-only).
    ai_relevance: int | None = None


class LabelingQueries(BaseModel):
    """The queries run to build a case's pool: the base question + any agentic sub-queries.

    ``base`` is the case's own question (what the keyword/vector/hybrid heads ran on); ``agentic``
    is the LLM planner's decomposition (empty until the planner has been run for the case). Shown
    in the labeling UI so a reviewer sees exactly what was sent to the index.
    """

    base: list[str] = Field(default_factory=list)
    agentic: list[str] = Field(default_factory=list)


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
    # ISO timestamp of when this pool was assembled against the index. Reflects the cached
    # build time, so the UI can show "pooled 2h ago" and offer an explicit recompute.
    computed_at: str | None = None
    # The queries this pool was built from (base question + any agentic sub-queries).
    queries: LabelingQueries | None = None


class ChunkLabelUpsert(BaseModel):
    test_id: str
    chunk_id: str
    # Graded relevance 0..3 (validated against the scale in the router).
    relevance: int
    content_preview: str | None = None
    url: str | None = None
    title: str | None = None


class ChunkLabelBatch(BaseModel):
    labels: list[ChunkLabelUpsert] = Field(default_factory=list)


class AiJudgeRequest(BaseModel):
    test_id: str
    # Dataset the case belongs to; defaults to the most recently updated dataset.
    dataset_id: str | None = None
    # Optional override of the default grading rubric (system prompt) for this run.
    instructions: str | None = None


class AiJudgeResponse(BaseModel):
    test_id: str
    # chunk_id -> AI-assigned graded relevance 0..3.
    grades: dict[str, int] = Field(default_factory=dict)
    judged: int = 0


class AiJudgePromptBatch(BaseModel):
    """One LLM call's user message: the full, untruncated chunk text for that batch."""

    user_prompt: str
    chunk_count: int = 0


class AiJudgePreviewResponse(BaseModel):
    """The exact prompt(s) the AI judge would send for a case — no LLM call, no grading.

    Rendered server-side from the same pool, rubric and batching the judge uses, so the reviewer
    sees the full chunk text (never truncated) and how the pool splits across calls before
    spending a judge call. The system prompt is shared by every batch.
    """

    test_id: str
    system_prompt: str
    batches: list[AiJudgePromptBatch] = Field(default_factory=list)
    chunk_count: int = 0


class PlanQueriesRequest(BaseModel):
    test_id: str
    # Dataset the case belongs to; defaults to the most recently updated dataset.
    dataset_id: str | None = None
    # Optional override of the default planner rubric (system prompt) for this run.
    instructions: str | None = None
    # Optional cap on how many sub-queries to plan (server clamps to a sane range).
    max_queries: int | None = None


class PlanQueriesResponse(BaseModel):
    """The planned agentic queries for a case, persisted so later pools fold them in."""

    test_id: str
    base: list[str] = Field(default_factory=list)
    agentic: list[str] = Field(default_factory=list)


class LabelingPromptDefaults(BaseModel):
    """Default rubrics the UI shows (and lets a reviewer edit before running)."""

    ai_judge: str
    query_planner: str


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
    # Graded relevance 0..3 this annotator assigned.
    relevance: int


class Disagreement(BaseModel):
    test_id: str
    chunk_id: str
    title: str | None = None
    votes: list[VoteEntry] = Field(default_factory=list)
    # Current adjudicated gold grade 0..3, or null if not yet resolved.
    gold: int | None = None


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
    # Adjudicated graded relevance 0..3 (validated against the scale in the router).
    relevance: int


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
    # ISO-8601 UTC time the metrics were computed (set when cached). None for a fresh, uncached
    # response and for the eval-run snapshot path.
    computed_at: str | None = None


class StageMetrics(BaseModel):
    """Deterministic retrieval metrics for one pipeline stage, macro-averaged across cases."""

    stage: str  # keyword | vector | hybrid | semantic | agentic
    label: str  # display label (Sparse / Dense / RRF / Reranked / Agentic)
    evaluated_cases: int = 0
    recall_at_k: dict[str, float] = Field(default_factory=dict)
    precision_at_k: dict[str, float] = Field(default_factory=dict)
    hit_rate_at_k: dict[str, float] = Field(default_factory=dict)
    ndcg_at_k: dict[str, float] = Field(default_factory=dict)
    mrr: float | None = None
    # Full per-stage metrics (per-case rows, bpref, condensed nDCG, slices, recall curve) so the
    # Overall block can render any one retriever in detail, not just the summary row above.
    metrics: RetrievalRunMetrics | None = None


class ByStageCaseMetrics(BaseModel):
    """One test case's per-stage score (at the largest k) for the drilldown grid."""

    test_id: str
    input: str | None = None
    # stage -> recall@largest_k / nDCG@largest_k (None when that stage returned nothing for the case)
    recall_by_stage: dict[str, float | None] = Field(default_factory=dict)
    ndcg_by_stage: dict[str, float | None] = Field(default_factory=dict)


class ByStageMetricsResponse(BaseModel):
    """Per-stage retrieval-quality comparison over a dataset's cases, vs. chunk-label gold."""

    available: bool = False
    dataset_id: str | None = None
    dataset_name: str | None = None
    gold_source: str = "human"
    ks: list[int] = Field(default_factory=list)
    total_cases: int = 0
    evaluated_cases: int = 0
    stages: list[StageMetrics] = Field(default_factory=list)
    cases: list[ByStageCaseMetrics] = Field(default_factory=list)
    # ISO-8601 UTC time the metrics were computed (set when cached).
    computed_at: str | None = None


# --- Saved retrieval runs (durable, annotatable, comparable history) ---


class RetrievalRunCreate(BaseModel):
    """Request to snapshot the current labels-path metrics as a saved run."""

    dataset_ids: list[str] = Field(default_factory=list)
    gold_source: str = "human"
    name: str | None = None


class RetrievalRunMetadataUpdate(BaseModel):
    """Editable metadata on a saved run. Unset fields are left unchanged."""

    name: str | None = None
    pipeline_version: str | None = None
    index_name: str | None = None
    index_version: str | None = None
    notes: str | None = None


class RetrievalRunSummary(BaseModel):
    """List-item view of a saved run: metadata + headline metrics (at the run's own max k)."""

    id: str
    created_at: str
    gold_source: str = "human"
    dataset_ids: list[str] = Field(default_factory=list)
    dataset_names: list[str] = Field(default_factory=list)
    ks: list[int] = Field(default_factory=list)
    total_cases: int = 0
    evaluated_cases: int = 0
    has_by_stage: bool = False
    # Metadata.
    name: str | None = None
    pipeline_version: str | None = None
    index_name: str | None = None
    index_version: str | None = None
    notes: str | None = None
    # Headline metrics at max(ks): recall / ndcg / precision / hit-rate, plus mrr and bpref.
    max_k: int | None = None
    recall: float | None = None
    ndcg: float | None = None
    precision: float | None = None
    hit_rate: float | None = None
    mrr: float | None = None
    bpref: float | None = None


class RetrievalRunRecord(RetrievalRunSummary):
    """Full detail of a saved run, including the metric blobs for charts/compare."""

    metrics: RetrievalRunMetrics
    by_stage: ByStageMetricsResponse | None = None


class RetrievalRunListResponse(BaseModel):
    data: list[RetrievalRunSummary] = Field(default_factory=list)


class RetrievalRunBulkDelete(BaseModel):
    """Request to prune several saved runs at once."""

    run_ids: list[str] = Field(default_factory=list)


class RetrievalComputeStart(BaseModel):
    """Request to start a detached labels-path metrics compute."""

    dataset_ids: list[str] = Field(default_factory=list)
    gold_source: str = "human"
    view: str = "overall"  # overall | byStage
    # Recompute forces a fresh live probe + embed; a plain Compute may reuse a warm cache.
    refresh: bool = False


class RetrievalComputeJob(BaseModel):
    """Status of a detached metrics compute; the panel polls this until it settles.

    ``trace`` is only populated on failure in debug builds (mirrors the sanitized 500 handler), so
    the panel can offer a copy-the-stack affordance.
    """

    id: str
    status: str  # pending | running | completed | failed
    view: str = "overall"
    gold_source: str = "human"
    dataset_ids: list[str] = Field(default_factory=list)
    progress_current: int | None = None
    progress_total: int | None = None
    error: str | None = None
    trace: str | None = None
