"use client";

import { type ByStageMetricsResponse, type RetrievalRunMetrics, type RetrievalTargets } from "@/lib/api";
import { RETRIEVER_NOTES } from "@/components/retrieval/constants";
import { OverallSection } from "@/components/retrieval/overall-section";
import { RecommendationsPanel } from "@/components/retrieval/recommendations-panel";
import { ByStageComparison } from "@/components/retrieval/by-stage-table";
import { RerankThreshold } from "@/components/retrieval/rerank-threshold";
import { type GoldSource, type MinGrade } from "@/components/retrieval/gold-controls";
import { ErrorNotice } from "@/components/error-notice";

type Source = "urls" | "labels";

/**
 * The computed-results body of the Retrieval panel: recommendations, the optional rerank-threshold
 * explorer, the Overall block for the selected retriever, and the By-stage comparison. Split out of
 * the panel (which owns fetching + controls) to keep each file focused and under the size budget.
 */
export function RetrievalResultsBody({
  displayMetrics,
  byStage,
  showByStage,
  targets,
  activeK,
  displaySource,
  rerankSweep,
  displayLoading,
  retrieverLabel,
  selectedRetriever,
  displayGold,
  displayMinGrade,
  useBest,
  overall,
  byStageLoading,
  byStageError,
}: {
  displayMetrics: RetrievalRunMetrics | null;
  byStage: ByStageMetricsResponse | null;
  showByStage: boolean;
  targets: RetrievalTargets | null;
  activeK: number;
  displaySource: Source;
  rerankSweep: ByStageMetricsResponse["stages"][number]["threshold_sweep"] | undefined;
  displayLoading: boolean;
  retrieverLabel?: string;
  selectedRetriever: string;
  displayGold: GoldSource;
  displayMinGrade: MinGrade;
  useBest: boolean;
  overall: RetrievalRunMetrics | null;
  byStageLoading: boolean;
  byStageError: unknown;
}) {
  return (
    <>
      {/* What to improve — rule-based findings over the computed metrics, most-severe first. */}
      <RecommendationsPanel
        overall={displayMetrics}
        byStage={showByStage ? byStage : null}
        targets={targets}
        k={activeK}
        source={displaySource}
      />

      {/* Score-threshold cutoff explorer — Agentic + rerank only. */}
      {showByStage && rerankSweep && rerankSweep.length > 0 && (
        <RerankThreshold sweep={rerankSweep} precisionTarget={targets?.precision ?? null} />
      )}

      {/* Overall — the selected retriever, in detail. */}
      <OverallSection
        metrics={displayMetrics}
        loading={displayLoading}
        source={displaySource}
        activeK={activeK}
        targets={targets}
        retrieverLabel={retrieverLabel}
        retrieverNote={RETRIEVER_NOTES[selectedRetriever]}
        retriever={selectedRetriever}
        goldSource={displayGold}
        minGrade={displayMinGrade}
        perRetriever={!useBest}
        bestAvailable={!!overall?.available}
      />

      {/* By stage — each retrieval method scored separately (labels path only). */}
      {showByStage && (
        <div id="retrieval-by-stage" className="mt-10">
          <h3 className="text-base font-semibold mb-3">By stage</h3>
          {byStageError ? <ErrorNotice error={byStageError} className="mb-3" /> : null}
          <ByStageComparison
            data={byStage}
            loading={byStageLoading}
            goldSource={displayGold}
            selectedK={activeK}
          />
        </div>
      )}
    </>
  );
}
