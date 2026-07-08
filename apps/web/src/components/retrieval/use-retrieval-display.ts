import { useMemo } from "react";
import { type ByStageMetricsResponse, type RetrievalRunMetrics, type RetrievalTargets } from "@/lib/api";
import { METRICS, RETRIEVERS, statusOf, type MetricDef } from "@/components/retrieval/constants";
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
  const hasAgentStage = !!byStage?.stages.some((s) => s.stage === "agent");
  const retrieverOptions = useMemo(
    () => RETRIEVERS.filter((r) => r.value !== "agent" || hasAgentStage),
    [hasAgentStage],
  );
  // Prefer the stage's own (per-project) label from the response; fall back to the static one.
  const retrieverLabel =
    byStage?.stages.find((s) => s.stage === selectedRetriever)?.label ??
    RETRIEVERS.find((r) => r.value === selectedRetriever)?.label;
  // The rerankerScore threshold sweep, present only when the Agentic + rerank stage is selected.
  const rerankSweep =
    selectedRetriever === "agentic_rerank"
      ? byStage?.stages.find((s) => s.stage === "agentic_rerank")?.threshold_sweep
      : undefined;

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
    availableKs,
    activeK,
    metCount,
  };
}
