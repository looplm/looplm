"use client";

import { useMemo, useState } from "react";

import { StatCard } from "@/components/eval-shared";
import {
  BALANCE_LABEL,
  BALANCE_PILL,
  BAND_ACCENT,
  chunkCoverageBand,
  testBalance,
} from "@/components/coverage/coverage-bands";
import type {
  CoverageResults,
  PartitionAcknowledgement,
  PartitionIssue,
  PartitionIssueSeverity,
} from "@/lib/api";

const SEVERITY_BADGE: Record<PartitionIssueSeverity, string> = {
  high: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  medium: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  low: "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400",
};

export function CoverageResultsView({
  results,
  acknowledgements,
  canEdit,
  onAcknowledge,
  onUndoAcknowledge,
}: {
  results: CoverageResults;
  acknowledgements: PartitionAcknowledgement[];
  canEdit: boolean;
  onAcknowledge: (value: string, note: string) => void;
  onUndoAcknowledge: (id: string) => void;
}) {
  const maxCount = results.rows.reduce((m, r) => Math.max(m, r.indexed_count), 0) || 1;
  const totalDocs = results.total_docs || 0;
  const totalCases = results.rows.reduce((s, r) => s + r.covering_cases, 0);
  const chunkBand = chunkCoverageBand(results.doc_coverage_pct);
  const [noteFor, setNoteFor] = useState<PartitionIssue | null>(null);

  const issueByValue = useMemo(() => {
    const m = new Map<string, PartitionIssue>();
    (results.issues || []).forEach((i) => m.set(i.value, i));
    return m;
  }, [results.issues]);

  const ackByValue = useMemo(() => {
    const m = new Map<string, PartitionAcknowledgement>();
    acknowledgements.forEach((a) => m.set(a.partition_value, a));
    return m;
  }, [acknowledgements]);

  const openIssues = (results.issues || []).filter((i) => !ackByValue.has(i.value));

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard
          label="Values covered"
          value={`${results.covered_values}/${results.total_values}`}
          accent={results.covered_values === results.total_values ? "green" : "amber"}
        />
        <StatCard label="Value coverage" value={`${results.value_coverage_pct}%`} />
        <StatCard
          label="Chunk coverage"
          value={`${results.doc_coverage_pct}%`}
          sub="share of indexed chunks in covered values"
          accent={BAND_ACCENT[chunkBand]}
        />
        <StatCard
          label="Gaps"
          value={results.total_values - results.covered_values}
          accent={results.total_values - results.covered_values > 0 ? "red" : "green"}
        />
      </div>

      {openIssues.length > 0 && (
        <div className="mb-4 p-3 rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10 text-sm text-amber-800 dark:text-amber-300">
          ⚠ {openIssues.length} potential index-quality issue
          {openIssues.length === 1 ? "" : "s"} — values that look mislabeled, duplicated, or empty.
          Review below; mark any that are intentional so they stop being flagged.
        </div>
      )}

      <div className="rounded-xl border border-gray-100 dark:border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-xs text-gray-500 dark:text-slate-400">
              <th className="px-4 py-2 font-medium">{results.partition_key}</th>
              <th className="px-4 py-2 font-medium text-right">Indexed (chunks)</th>
              <th className="px-4 py-2 font-medium text-right">Test cases</th>
              <th className="px-4 py-2 font-medium text-center">Covered</th>
            </tr>
          </thead>
          <tbody>
            {results.rows.map((r) => {
              const issue = issueByValue.get(r.value);
              const ack = ackByValue.get(r.value);
              const share = totalDocs > 0 ? (r.indexed_count / totalDocs) * 100 : 0;
              const shareLabel = share >= 1 ? `${Math.round(share)}%` : `${share.toFixed(1)}%`;
              const testShare = totalCases > 0 ? (r.covering_cases / totalCases) * 100 : 0;
              const balance = testBalance({
                indexedCount: r.indexed_count,
                coveringCases: r.covering_cases,
                totalDocs,
                totalCases,
              });
              const balanceTitle = `${shareLabel} of content vs ${
                testShare >= 1 ? Math.round(testShare) : testShare.toFixed(1)
              }% of tests`;
              return (
                <tr
                  key={r.value}
                  className={`border-b border-gray-50 dark:border-slate-800/50 ${
                    r.covered ? "" : "bg-red-50/40 dark:bg-red-900/10"
                  }`}
                >
                  <td className="px-4 py-2">
                    <div className="font-medium truncate max-w-[320px]" title={r.value}>
                      {r.value || <span className="italic text-gray-400">(empty)</span>}
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden max-w-[320px]">
                      <div
                        className={`h-full rounded-full ${r.covered ? "bg-indigo-500" : "bg-red-400"}`}
                        style={{ width: `${Math.round((r.indexed_count / maxCount) * 100)}%` }}
                      />
                    </div>
                    {issue && ack && (
                      <div className="mt-1.5 flex items-center gap-2 text-xs text-gray-400 dark:text-slate-500">
                        <span>✓ Acknowledged{ack.note ? `: “${ack.note}”` : ""}</span>
                        {canEdit && (
                          <button
                            onClick={() => onUndoAcknowledge(ack.id)}
                            className="underline hover:text-gray-600 dark:hover:text-slate-300"
                          >
                            Undo
                          </button>
                        )}
                      </div>
                    )}
                    {issue && !ack && (
                      <div className="mt-1.5 flex items-center flex-wrap gap-2">
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium ${SEVERITY_BADGE[issue.severity]}`}
                          title={issue.message}
                        >
                          ⚠ {issue.message}
                        </span>
                        {canEdit && (
                          <button
                            onClick={() => setNoteFor(issue)}
                            className="text-[11px] underline text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                          >
                            Mark as intentional
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {r.indexed_count.toLocaleString()}
                    <div className="text-[11px] text-gray-400 dark:text-slate-500">
                      {shareLabel} of index
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <div className="tabular-nums">{r.covering_cases}</div>
                    {balance.status !== "none" && balance.status !== "balanced" && (
                      <div className="mt-0.5 flex flex-col items-end gap-0.5" title={balanceTitle}>
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium ${BALANCE_PILL[balance.status]}`}
                        >
                          {BALANCE_LABEL[balance.status]}
                        </span>
                        <span className="text-[11px] text-gray-400 dark:text-slate-500">
                          fair share ≈ {Math.round(balance.expected)}
                        </span>
                      </div>
                    )}
                    {balance.status === "balanced" && (
                      <div
                        className="mt-0.5 text-[11px] text-green-600 dark:text-green-400"
                        title={balanceTitle}
                      >
                        balanced
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-center">{r.covered ? "✅" : "❌"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400 dark:text-slate-500">
        Counts are per indexed chunk, not distinct documents.
      </p>

      {noteFor && (
        <AcknowledgeModal
          issue={noteFor}
          onClose={() => setNoteFor(null)}
          onConfirm={(note) => {
            onAcknowledge(noteFor.value, note);
            setNoteFor(null);
          }}
        />
      )}
    </div>
  );
}

function AcknowledgeModal({
  issue,
  onClose,
  onConfirm,
}: {
  issue: PartitionIssue;
  onClose: () => void;
  onConfirm: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-lg">
          <div className="p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">Mark as intentional</h2>
          </div>
          <div className="p-4 space-y-3">
            <p className="text-sm text-gray-600 dark:text-slate-400">
              <span className="font-medium text-gray-800 dark:text-slate-200">{issue.value}</span> will
              stop being flagged on future runs. Optionally note why it&apos;s intentional.
            </p>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              autoFocus
              placeholder="e.g. Separate Altsystem team, kept on purpose"
              className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
            />
          </div>
          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={() => onConfirm(note.trim())}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white"
            >
              Mark intentional
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
