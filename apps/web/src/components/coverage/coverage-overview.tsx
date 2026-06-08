"use client";

import { useState } from "react";

import { ConfirmModal } from "@/components/confirm-modal";
import {
  BAND_LABEL,
  BAND_PILL,
  chunkCoverageBand,
} from "@/components/coverage/coverage-bands";
import type { CoverageCategoryOverview } from "@/lib/api";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function TrendDelta({ delta }: { delta?: number | null }) {
  if (delta == null) {
    return <span className="text-xs text-gray-400 dark:text-slate-600">—</span>;
  }
  if (delta > 0) {
    return <span className="text-xs text-green-600 dark:text-green-400">▲ +{delta}</span>;
  }
  if (delta < 0) {
    return <span className="text-xs text-red-600 dark:text-red-400">▼ {delta}</span>;
  }
  return <span className="text-xs text-gray-400 dark:text-slate-500">±0</span>;
}

export function CoverageOverview({
  categories,
  canEdit,
  onView,
  onRerun,
}: {
  categories: CoverageCategoryOverview[];
  canEdit: boolean;
  onView: (runId: string) => void;
  onRerun: (partitionKey: string) => void;
}) {
  const [confirmRerun, setConfirmRerun] = useState<string | null>(null);

  if (categories.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center text-sm text-gray-500 dark:text-slate-400">
        No analyses yet. Switch to <span className="font-medium">Analyze</span> to run your first
        coverage analysis.
      </div>
    );
  }

  return (
    <>
      <div className="rounded-xl border border-gray-100 dark:border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-xs text-gray-500 dark:text-slate-400">
            <th className="px-4 py-2 font-medium">Category</th>
            <th className="px-4 py-2 font-medium">Value coverage</th>
            <th className="px-4 py-2 font-medium">Chunk coverage</th>
            <th className="px-4 py-2 font-medium text-right">Gaps</th>
            <th className="px-4 py-2 font-medium text-right">Issues</th>
            <th className="px-4 py-2 font-medium">Last run</th>
            <th className="px-4 py-2 font-medium text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((c) => {
            const pct = c.latest.value_coverage_pct ?? 0;
            const chunkPct = c.latest.doc_coverage_pct ?? 0;
            const band = chunkCoverageBand(c.latest.doc_coverage_pct);
            return (
              <tr key={c.partition_key} className="border-b border-gray-50 dark:border-slate-800/50">
                <td className="px-4 py-3 font-medium">{c.partition_key}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-indigo-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="tabular-nums">{pct}%</span>
                    <TrendDelta delta={c.value_coverage_delta} />
                  </div>
                  <div className="text-[11px] text-gray-400 dark:text-slate-500 mt-0.5">
                    {c.latest.covered_values}/{c.latest.total_values} values
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="tabular-nums">{chunkPct}%</span>
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium ${BAND_PILL[band]}`}
                    >
                      {BAND_LABEL[band]}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  {c.latest.gaps > 0 ? (
                    <span className="text-red-600 dark:text-red-400">{c.latest.gaps}</span>
                  ) : (
                    0
                  )}
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  {c.latest.issue_count > 0 ? (
                    <span className="text-amber-600 dark:text-amber-400">{c.latest.issue_count}</span>
                  ) : (
                    0
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500 dark:text-slate-400">
                  {timeAgo(c.latest.created_at)}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button
                    onClick={() => onView(c.latest.id)}
                    className="px-2.5 py-1 rounded-lg text-xs bg-indigo-600 text-white hover:bg-indigo-500"
                  >
                    View
                  </button>
                  {canEdit && (
                    <button
                      onClick={() => setConfirmRerun(c.partition_key)}
                      className="ml-2 px-2.5 py-1 rounded-lg text-xs bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
                    >
                      Re-run
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>

      {confirmRerun && (
        <ConfirmModal
          title="Re-run analysis?"
          message={`This starts a fresh coverage analysis for "${confirmRerun}" — it makes new API/LLM calls and adds a new run to the history. Continue?`}
          confirmLabel="Re-run"
          onConfirm={() => {
            onRerun(confirmRerun);
            setConfirmRerun(null);
          }}
          onCancel={() => setConfirmRerun(null)}
        />
      )}
    </>
  );
}
