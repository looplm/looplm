"use client";

import { useState } from "react";
import Link from "next/link";
import type { FailureModesResponse, FailureModeCase } from "@/lib/api";

interface FailureModesTabProps {
  result: FailureModesResponse | null;
  loading: boolean;
  running: boolean;
  triggering: boolean;
  onAnalyze: () => void;
}

// Fixed RAG failure taxonomy — keep in sync with FAILURE_CATEGORIES in
// feedback_failure_modes_worker.py. Unknown (LLM-coined) categories fall back
// to a neutral slate style via `categoryMeta`.
const CATEGORY_META: Record<string, { label: string; badge: string; dot: string }> = {
  retrieval: {
    label: "Retrieval miss",
    badge: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
    dot: "bg-amber-500",
  },
  generation: {
    label: "Generation error",
    badge: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
    dot: "bg-red-500",
  },
  long_context: {
    label: "Lost in the middle",
    badge: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
    dot: "bg-orange-500",
  },
  query: {
    label: "User prompt",
    badge: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    dot: "bg-blue-500",
  },
  knowledge_gap: {
    label: "Knowledge gap",
    badge: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
    dot: "bg-purple-500",
  },
  refusal: {
    label: "Refusal / format",
    badge: "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300",
    dot: "bg-teal-500",
  },
  other: {
    label: "Other",
    badge: "bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300",
    dot: "bg-gray-400",
  },
};

function categoryMeta(category: string) {
  return (
    CATEGORY_META[category] ?? {
      label: category.replace(/_/g, " "),
      badge: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
      dot: "bg-slate-400",
    }
  );
}

function CategoryBadge({ category }: { category: string }) {
  const meta = categoryMeta(category);
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${meta.badge}`}>
      {meta.label}
    </span>
  );
}

/** Overall distribution of diagnosed root-cause categories across all traces. */
function CategoryDistribution({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  if (total === 0) return null;

  return (
    <div className="mb-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-3">
        Root-cause distribution ({total} traces)
      </p>
      <div className="flex h-2.5 rounded-full overflow-hidden mb-3">
        {entries.map(([cat, n]) => (
          <div
            key={cat}
            className={categoryMeta(cat).dot}
            style={{ width: `${(n / total) * 100}%` }}
            title={`${categoryMeta(cat).label}: ${n}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {entries.map(([cat, n]) => (
          <span key={cat} className="inline-flex items-center gap-1.5 text-xs text-gray-600 dark:text-slate-300">
            <span className={`w-2 h-2 rounded-full ${categoryMeta(cat).dot}`} />
            {categoryMeta(cat).label}
            <span className="text-gray-400 dark:text-slate-500">{n}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function CaseRow({ c }: { c: FailureModeCase }) {
  return (
    <li className="flex items-start gap-2 text-xs">
      <span className={`flex-shrink-0 mt-1 w-2 h-2 rounded-full ${categoryMeta(c.category ?? "other").dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <CategoryBadge category={c.category ?? "other"} />
          {typeof c.confidence === "number" && (
            <span className="text-gray-400 dark:text-slate-500">{Math.round(c.confidence * 100)}% confident</span>
          )}
        </div>
        {c.question && (
          <p className="mt-1 font-medium text-gray-800 dark:text-slate-100">{c.question}</p>
        )}
        {c.explanation && (
          <p className="mt-0.5 text-gray-600 dark:text-slate-300">{c.explanation}</p>
        )}
        {c.comment && (
          <p className="mt-0.5 text-gray-400 dark:text-slate-500 italic">User said: {c.comment}</p>
        )}
      </div>
      {c.trace_id && (
        <Link
          href={`/traces/${c.trace_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-shrink-0 inline-flex items-center gap-0.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 hover:underline whitespace-nowrap"
        >
          View trace
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
          </svg>
        </Link>
      )}
    </li>
  );
}

export function FailureModesTab({
  result,
  loading,
  running,
  triggering,
  onAnalyze,
}: FailureModesTabProps) {
  const clusters = result?.clusters ?? [];
  const hasResults = result?.status === "completed" && clusters.length > 0;
  const [expandedRanks, setExpandedRanks] = useState<Set<number>>(new Set());

  const toggleExpand = (rank: number) => {
    setExpandedRanks((prev) => {
      const next = new Set(prev);
      if (next.has(rank)) next.delete(rank);
      else next.add(rank);
      return next;
    });
  };

  return (
    <div>
      {/* Progress indicator */}
      {running && result && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-200 dark:border-indigo-900/50">
          <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span className="text-sm text-indigo-700 dark:text-indigo-300">
            {result.status === "pending"
              ? "Starting analysis..."
              : `Diagnosing traces... ${result.processed_traces} of ${result.total_traces}`}
          </span>
          {result.total_traces > 0 && (
            <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                style={{ width: `${Math.round((result.processed_traces / result.total_traces) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {result?.status === "failed" && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-900/50 text-sm text-red-700 dark:text-red-300">
          Analysis failed: {result.error || "Unknown error"}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : !hasResults && !running ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center">
          <p className="text-gray-500 dark:text-slate-400 mb-4">
            Diagnose why your negative-feedback traces failed — retrieval, generation, long context,
            the user prompt, or a knowledge gap — and cluster them into recurring failure modes.
          </p>
          <button
            onClick={onAnalyze}
            disabled={triggering}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
          >
            {triggering ? "Starting..." : "Analyze Failure Modes"}
          </button>
        </div>
      ) : hasResults ? (
        <div>
          {result?.completed_at && (
            <p className="text-xs text-gray-400 dark:text-slate-500 mb-4">
              Last analyzed: {new Date(result.completed_at).toLocaleString("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
              {" "}({result.total_traces} traces analyzed)
            </p>
          )}

          <CategoryDistribution counts={result?.category_counts ?? {}} />

          <div className="space-y-3">
            {clusters.map((cluster) => {
              const isExpanded = expandedRanks.has(cluster.rank);
              const cases = cluster.cases ?? [];

              return (
                <div
                  key={cluster.rank}
                  className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800"
                >
                  <button
                    type="button"
                    onClick={() => toggleExpand(cluster.rank)}
                    className="w-full p-4 text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                        <span className="text-sm font-bold text-indigo-600 dark:text-indigo-400">
                          {cluster.rank}
                        </span>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-2 flex-wrap">
                          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                            {cluster.label}
                          </h3>
                          <CategoryBadge category={cluster.category} />
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
                            {cluster.count} case{cluster.count === 1 ? "" : "s"}
                          </span>
                        </div>

                        {cluster.description && (
                          <p className="text-xs text-gray-600 dark:text-slate-300">
                            {cluster.description}
                          </p>
                        )}
                        {cluster.recommendation && (
                          <p className="mt-2 text-xs text-emerald-700 dark:text-emerald-300 pl-3 border-l-2 border-emerald-300 dark:border-emerald-700">
                            Fix: {cluster.recommendation}
                          </p>
                        )}
                      </div>

                      <svg
                        className={`w-5 h-5 text-gray-400 dark:text-slate-500 flex-shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={1.5}
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
                      </svg>
                    </div>
                  </button>

                  {isExpanded && cases.length > 0 && (
                    <div className="px-4 pb-4 pt-0 ml-12">
                      <div className="border-t border-gray-100 dark:border-slate-800 pt-3">
                        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-2">
                          Cases ({cases.length})
                        </p>
                        <ul className="space-y-3">
                          {cases.map((c, i) => (
                            <CaseRow key={i} c={c} />
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
