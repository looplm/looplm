import { useMemo } from "react";
import { type ByStageMetricsResponse, type RetrievalRunMetrics, type RetrievalTargets } from "@/lib/api";
import { COHERE_RETRIEVERS, METRICS, RETRIEVERS, statusOf, type MetricDef } from "@/components/retrieval/constants";
import { type GoldSource, type MinGrade } from "@/components/retrieval/gold-controls";

type Source = "urls" | "labels";

export interface RetrievalDisplay {
  // What's on screen: a fresh compute (applied) or a saved run (savedRun); null → empty prompt.
  displaySource: Source | null;
  displayGold: GoldSource;
  displayMinGrade: MinGrade;
  showByStage: boolean;
  computedAt: string | null | undefined;
  // "best"/URLs use the live-probe overall; a pipeline stage uses that stage's by-stage metrics.
  useBest: boolean;
  displayMetrics: RetrievalRunMetrics | null;
  displayLoading: boolean;
  retrieverOptions: { value: string; label: string }[];
  retrieverLabel: string | undefined;
  rerankSweep: ByStageMetricsResponse["stages"][number]["threshold_sweep"] | undefined;
  // Top of the selected reranker's score scale (4 = Azure rerankerScore, 1 = Cohere), null when
  // no sweep is shown. The slider needs it: the two scales are not interchangeable.
  rerankScaleMax: number | null;
  availableKs: number[];
  activeK: number;
  metCount: number;
}

/**
 * Derive everything the Retrieval panel renders from the current state — which source/gold is
 * displayed, the selected retriever's metrics, the available cutoffs and the targets-met count.
 * Pulled out of the panel to keep it lean; pure over its inputs (no side effects).
 */
export function useRetrievalDisplay(args: {
  applied: { source: Source; goldSource: GoldSource; minGrade: MinGrade } | null;
  savedRun: { gold_source?: string | null; min_grade?: number | null } | null;
  overall: RetrievalRunMetrics | null;
  byStage: ByStageMetricsResponse | null;
  selectedRetriever: string;
  loading: boolean;
  byStageLoading: boolean;
  selectedK: number | null;
  targets: RetrievalTargets | null;
}): RetrievalDisplay {
  const { applied, savedRun, overall, byStage, selectedRetriever, loading, byStageLoading, selectedK, targets } = args;

  const displaySource: Source | null = applied?.source ?? (savedRun ? "labels" : null);
  const displayGold: GoldSource = applied?.goldSource ?? (savedRun?.gold_source as GoldSource) ?? "human";
  const displayMinGrade: MinGrade = applied?.minGrade ?? (savedRun?.min_grade as MinGrade) ?? 1;
  const showByStage = displaySource === "labels";
  const computedAt = overall?.computed_at ?? byStage?.computed_at;

  const useBest = displaySource !== "labels" || selectedRetriever === "best";
  const displayMetrics: RetrievalRunMetrics | null = useBest
    ? overall
    : byStage?.stages.find((s) => s.stage === selectedRetriever)?.metrics ?? null;
  const displayLoading = useBest ? loading : byStageLoading;

  // The custom-agent retriever only exists when a project configured an agent endpoint AND it
  // returned a ranking (backend appends the "agent" stage then), so hide the option otherwise.
  // Same for the Cohere stages, which the backend omits unless a reranker is configured.
  const hasAgentStage = !!byStage?.stages.some((s) => s.stage === "agent");
  const stageValues = byStage?.stages.map((s) => s.stage);
  const hasCohereStages = !!stageValues?.some((s) => COHERE_RETRIEVERS.includes(s));
  const retrieverOptions = useMemo(
    () =>
      RETRIEVERS.filter(
        (r) =>
          (r.value !== "agent" || hasAgentStage) &&
          (!COHERE_RETRIEVERS.includes(r.value) || hasCohereStages),
      ),
    [hasAgentStage, hasCohereStages],
  );
  // Prefer the stage's own (per-project) label from the response; fall back to the static one.
  const retrieverLabel =
    byStage?.stages.find((s) => s.stage === selectedRetriever)?.label ??
    RETRIEVERS.find((r) => r.value === selectedRetriever)?.label;
  // The score-threshold sweep of whichever rerank stage is selected (Azure's agentic rerank or
  // either Cohere pass). Positional stages have no sweep, so the slider stays hidden for them.
  const selectedStage = byStage?.stages.find((s) => s.stage === selectedRetriever);
  const rerankSweep = selectedStage?.threshold_sweep?.length
    ? selectedStage.threshold_sweep
    : undefined;
  const rerankScaleMax = rerankSweep ? selectedStage?.threshold_scale_max ?? null : null;

  // Cutoffs for the displayed retriever; the selected k falls back to the deepest when unset or
  // absent. Default to @10 (the depth typically fed to the model): precision@50 is pool-capped noise.
  const availableKs = displayMetrics?.ks ?? overall?.ks ?? byStage?.ks ?? [];
  const maxK = availableKs.length ? Math.max(...availableKs) : 10;
  const defaultK = availableKs.includes(10) ? 10 : maxK;
  const activeK = selectedK != null && availableKs.includes(selectedK) ? selectedK : defaultK;
  const lk = String(activeK);
  const cardValue = (m: MetricDef): number | null | undefined =>
    displayMetrics ? m.value(displayMetrics, lk) : undefined;
  const metCount = useMemo(
    () =>
      displayMetrics && targets
        ? METRICS.filter((m) => statusOf(cardValue(m), targets[m.key]) === "good").length
        : 0,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [displayMetrics, targets, lk],
  );

  return {
    displaySource,
    displayGold,
    displayMinGrade,
    showByStage,
    computedAt,
    useBest,
    displayMetrics,
    displayLoading,
    retrieverOptions,
    retrieverLabel,
    rerankSweep,
    rerankScaleMax,
    availableKs,
    activeK,
    metCount,
  };
}
