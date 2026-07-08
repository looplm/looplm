"use client";

import { useMemo, useState } from "react";
import { type ByStageMetricsResponse } from "@/lib/api";
import { pct, dec } from "@/components/retrieval/constants";

// Side-by-side deterministic retrieval metrics for each pipeline stage (sparse/dense/RRF/reranked/
// agentic), scored against the chunk-label gold, plus a per-case drilldown. Presentational: the
// parent panel owns fetching (gated behind Compute), this just renders the result.
export function ByStageComparison({
  data,
  loading,
  goldSource,
  selectedK,
}: {
  data: ByStageMetricsResponse | null;
  loading: boolean;
  goldSource: "human" | "ai" | "both";
  selectedK?: number | null;
}) {
  const [drillMetric, setDrillMetric] = useState<"recall" | "ndcg">("recall");
  const [showCases, setShowCases] = useState(false);

  // Deepest cutoff (the k the per-case drilldown is collapsed to server-side) and the selected one
  // the comparison table shows. They differ only when the user picks a shallower cutoff.
  const maxK = useMemo(() => (data?.ks.length ? Math.max(...data.ks) : 10), [data]);
  const k = selectedK != null && data?.ks.includes(selectedK) ? String(selectedK) : String(maxK);

  if (loading) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
        Scoring each stage…
      </div>
    );
  }
  if (!data || !data.available) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
        No chunk-relevance gold for this dataset{goldSource === "ai" ? " from the AI judge" : ""} yet,
        or no index is connected to probe. Judge candidates on the Labeling page (and connect an
        index), then each stage is scored against those labels.
      </div>
    );
  }

  const cols: { key: string; label: string; fmt: (v: number | null | undefined) => string }[] = [
    { key: "recall", label: `Recall@${k}`, fmt: pct },
    { key: "ndcg", label: `nDCG@${k}`, fmt: pct },
    { key: "mrr", label: "MRR", fmt: dec },
    { key: "hit", label: `Hit@${k}`, fmt: pct },
    { key: "precision", label: `Prec@${k}`, fmt: pct },
  ];
  const cellValue = (s: ByStageMetricsResponse["stages"][number], key: string): number | null | undefined => {
    switch (key) {
      case "recall":
        return s.recall_at_k[k];
      case "ndcg":
        return s.ndcg_at_k[k];
      case "mrr":
        return s.mrr;
      case "hit":
        return s.hit_rate_at_k[k];
      case "precision":
        return s.precision_at_k[k];
    }
  };
  // Best (max) value per column, to highlight the winning stage.
  const bestByCol = new Map<string, number>();
  for (const c of cols) {
    let best = -Infinity;
    for (const s of data.stages) {
      const v = cellValue(s, c.key);
      if (typeof v === "number" && v > best) best = v;
    }
    bestByCol.set(c.key, best);
  }

  const drillBy = (r: ByStageMetricsResponse["cases"][number]) =>
    drillMetric === "recall" ? r.recall_by_stage : r.ndcg_by_stage;

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-400 dark:text-slate-500">
        {data.evaluated_cases} case{data.evaluated_cases === 1 ? "" : "s"} with gold · each stage&apos;s
        own ranking scored against the chunk-label gold ({goldSource === "ai" ? "AI judge" : goldSource})
      </p>

      <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
              <th className="px-4 py-3 font-medium">Stage</th>
              {cols.map((c) => (
                <th key={c.key} className="px-4 py-3 font-medium text-right tabular-nums">
                  {c.label}
                </th>
              ))}
              <th className="px-4 py-3 font-medium text-right">Cases</th>
            </tr>
          </thead>
          <tbody>
            {data.stages.map((s) => (
              <tr key={s.stage} className="border-b border-gray-100/50 dark:border-slate-800/50">
                <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">{s.label}</td>
                {cols.map((c) => {
                  const v = cellValue(s, c.key);
                  const isBest = typeof v === "number" && v === bestByCol.get(c.key) && data.stages.length > 1;
                  return (
                    <td
                      key={c.key}
                      className={`px-4 py-3 text-right tabular-nums ${
                        isBest
                          ? "font-semibold text-emerald-600 dark:text-emerald-400"
                          : "text-gray-700 dark:text-slate-300"
                      }`}
                    >
                      {c.fmt(v)}
                    </td>
                  );
                })}
                <td className="px-4 py-3 text-right text-gray-400 dark:text-slate-500 tabular-nums">
                  {s.evaluated_cases}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Per-case drilldown */}
      <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="w-full flex items-center justify-between gap-2 px-4 py-2.5">
          <button
            onClick={() => setShowCases((v) => !v)}
            className="flex items-center text-[13px] font-medium text-gray-600 dark:text-slate-300 hover:text-gray-800 dark:hover:text-slate-100"
          >
            <span className="mr-1.5">{showCases ? "▾" : "▸"}</span>
            Per-case breakdown ({data.cases.length})
            {showCases && (
              <span className="ml-1.5 text-gray-400 dark:text-slate-500 font-normal">at @{maxK}</span>
            )}
          </button>
          {showCases && (
            <span className="flex items-center gap-1 text-xs">
              {(["recall", "ndcg"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setDrillMetric(m)}
                  className={`px-2 py-0.5 rounded ${
                    drillMetric === m
                      ? "bg-indigo-600 text-white"
                      : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                  }`}
                >
                  {m === "recall" ? `Recall@${maxK}` : `nDCG@${maxK}`}
                </button>
              ))}
            </span>
          )}
        </div>
        {showCases && (
          <div className="overflow-x-auto border-t border-gray-100 dark:border-slate-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-2.5 font-medium">Question</th>
                  {data.stages.map((s) => (
                    <th key={s.stage} className="px-3 py-2.5 font-medium text-right tabular-nums">
                      {s.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.cases.map((r) => {
                  const vals = drillBy(r);
                  const best = Math.max(
                    ...data.stages.map((s) => (typeof vals[s.stage] === "number" ? (vals[s.stage] as number) : -1)),
                  );
                  return (
                    <tr key={r.test_id} className="border-b border-gray-100/50 dark:border-slate-800/50">
                      <td className="px-4 py-2.5 text-gray-700 dark:text-slate-300 max-w-md truncate" title={r.input ?? r.test_id}>
                        {r.input || r.test_id}
                      </td>
                      {data.stages.map((s) => {
                        const v = vals[s.stage];
                        const isBest = typeof v === "number" && v === best && best >= 0;
                        return (
                          <td
                            key={s.stage}
                            className={`px-3 py-2.5 text-right tabular-nums ${
                              isBest
                                ? "font-semibold text-emerald-600 dark:text-emerald-400"
                                : "text-gray-600 dark:text-slate-400"
                            }`}
                          >
                            {pct(v)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
