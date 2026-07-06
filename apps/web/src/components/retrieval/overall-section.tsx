"use client";

import { type RetrievalRunMetrics, type RetrievalTargets } from "@/lib/api";
import { OverallResults } from "@/components/retrieval/overall-results";

const empty =
  "rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400";

// The Overall block for the selected retriever: a loading placeholder, an empty/unavailable state,
// or the full metrics detail. Split out of the panel to keep it lean.
export function OverallSection({
  metrics,
  loading,
  source,
  activeK,
  targets,
  retrieverLabel,
  retrieverNote,
  retriever,
  goldSource,
  minGrade,
  perRetriever,
  bestAvailable,
}: {
  metrics: RetrievalRunMetrics | null;
  loading: boolean;
  source: "urls" | "labels";
  activeK: number;
  targets: RetrievalTargets | null;
  retrieverLabel?: string;
  retrieverNote?: string;
  // The selected retriever value + gold settings, threaded to the per-case diagnosis (labels path).
  retriever?: string;
  goldSource?: "human" | "ai" | "both";
  minGrade?: number;
  // A specific pipeline stage (not "best") is selected — used to tailor the unavailable message.
  perRetriever: boolean;
  // The live-probe overall is available, so "Best available" is a valid fallback.
  bestAvailable: boolean;
}) {
  if (loading && !metrics) {
    return <div className={empty}>Computing retrieval metrics...</div>;
  }
  if (!metrics || !metrics.available) {
    if (source !== "labels") {
      return (
        <div className={empty}>
          No labeled retrieval data for this run. Add expected source URLs to test cases and run an
          evaluation with a <span className="font-mono">contains_urls</span> check to measure recall.
        </div>
      );
    }
    if (perRetriever && bestAvailable) {
      return (
        <div className={empty}>
          Per-retriever detail isn&apos;t stored for this run — Recompute to populate it, or pick{" "}
          <span className="font-medium">Best available</span> above.
        </div>
      );
    }
    return (
      <div className={empty}>
        No chunk relevance labels for these datasets yet, or no index is connected to probe. Judge
        candidates on the Labeling page (and connect an index provider), then this measures the
        index&apos;s recall against those human labels.
      </div>
    );
  }
  return (
    <OverallResults
      overall={metrics}
      targets={targets}
      activeK={activeK}
      source={source}
      retrieverLabel={retrieverLabel}
      retrieverNote={retrieverNote}
      retriever={retriever}
      goldSource={goldSource}
      minGrade={minGrade}
    />
  );
}
