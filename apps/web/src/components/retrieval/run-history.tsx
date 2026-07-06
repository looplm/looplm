"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  bulkDeleteRetrievalRuns,
  deleteRetrievalRun,
  getRetrievalRun,
  listRetrievalRuns,
  type RetrievalRunRecord,
  type RetrievalRunSummary,
} from "@/lib/api";
import { pct, dec } from "@/components/retrieval/constants";
import { ConfirmModal } from "@/components/confirm-modal";
import { RunMetadataEditor } from "@/components/retrieval/run-metadata-editor";
import { RunCompare } from "@/components/retrieval/run-compare";

// Durable history of saved retrieval runs: annotate, prune, and compare. Auto-refetches when the
// panel snapshots a new run (via refreshKey).
export function RunHistory({
  refreshKey,
  canEdit,
  selectedRunId,
  onSelectRun,
}: {
  refreshKey: number;
  canEdit: boolean;
  // The run currently displayed in the metrics panel (highlighted here).
  selectedRunId?: string | null;
  // Change which run the panel displays (also used to default to the latest / recover after delete).
  onSelectRun?: (id: string | null) => void;
}) {
  const [runs, setRuns] = useState<RetrievalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [compareRuns, setCompareRuns] = useState<RetrievalRunRecord[] | null>(null);
  const [comparing, setComparing] = useState(false);

  // Refs so load() stays stable (no refetch on every selection change).
  const selectedRunIdRef = useRef(selectedRunId);
  selectedRunIdRef.current = selectedRunId;
  const onSelectRunRef = useRef(onSelectRun);
  onSelectRunRef.current = onSelectRun;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listRetrievalRuns();
      setRuns(res.data);
      setSelected((prev) => new Set([...prev].filter((id) => res.data.some((r) => r.id === id))));
      // Keep the panel's displayed run valid: default to the latest when nothing is selected, and
      // recover to the latest if the selected run was just deleted.
      const cur = selectedRunIdRef.current;
      if (onSelectRunRef.current && (!cur || !res.data.some((r) => r.id === cur))) {
        onSelectRunRef.current(res.data[0]?.id ?? null);
      }
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allSelected = runs.length > 0 && selected.size === runs.length;
  const someSelected = selected.size > 0 && !allSelected;
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(runs.map((r) => r.id)));

  const compare = async () => {
    setComparing(true);
    try {
      const ids = runs.filter((r) => selected.has(r.id)).map((r) => r.id);
      const details = await Promise.all(ids.map((id) => getRetrievalRun(id)));
      setCompareRuns(details);
    } finally {
      setComparing(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteId) return;
    const id = deleteId;
    setDeleteId(null);
    await deleteRetrievalRun(id);
    setCompareRuns((prev) => prev?.filter((r) => r.id !== id) ?? null);
    await load();
  };

  const confirmBulkDelete = async () => {
    const ids = runs.filter((r) => selected.has(r.id)).map((r) => r.id);
    setBulkDeleteOpen(false);
    if (!ids.length) return;
    await bulkDeleteRetrievalRuns(ids);
    const removed = new Set(ids);
    setCompareRuns((prev) => prev?.filter((r) => !removed.has(r.id)) ?? null);
    setSelected(new Set());
    await load();
  };

  if (loading && !runs.length) {
    return <div className="text-sm text-gray-500 dark:text-slate-400">Loading saved runs…</div>;
  }
  if (!runs.length) {
    return (
      <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 text-center text-sm text-gray-500 dark:text-slate-400">
        No saved runs yet. Compute Human-labels metrics above and each run is saved here
        automatically — annotate it with your pipeline and index version, then compare over time.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 dark:text-slate-500">
          {runs.length} run{runs.length === 1 ? "" : "s"} · {selected.size} selected
        </span>
        <div className="flex items-center gap-2">
          {canEdit && selected.size > 0 && (
            <button
              onClick={() => setBulkDeleteOpen(true)}
              className="text-xs font-medium rounded-lg px-3 py-1.5 bg-red-600 text-white hover:bg-red-700"
            >
              Delete selected ({selected.size})
            </button>
          )}
          <button
            onClick={compare}
            disabled={selected.size < 2 || comparing}
            className="text-xs font-medium rounded-lg px-3 py-1.5 bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {comparing ? "Loading…" : `Compare (${selected.size})`}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
              <th className="px-3 py-2.5 w-8">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected;
                  }}
                  onChange={toggleAll}
                  aria-label={allSelected ? "Deselect all runs" : "Select all runs"}
                  className="rounded border-gray-300 dark:border-slate-600"
                />
              </th>
              <th className="px-3 py-2.5 font-medium">Run</th>
              <th className="px-3 py-2.5 font-medium">Pipeline / index</th>
              <th className="px-3 py-2.5 font-medium text-right">Recall@k</th>
              <th className="px-3 py-2.5 font-medium text-right">nDCG@k</th>
              <th className="px-3 py-2.5 font-medium text-right">MRR</th>
              <th className="px-3 py-2.5 font-medium text-right">Cases</th>
              <th className="px-3 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <RunRow
                key={r.id}
                run={r}
                checked={selected.has(r.id)}
                editing={editingId === r.id}
                viewing={selectedRunId === r.id}
                canEdit={canEdit}
                onToggle={() => toggle(r.id)}
                onView={() => onSelectRun?.(r.id)}
                onEdit={() => setEditingId((cur) => (cur === r.id ? null : r.id))}
                onDelete={() => setDeleteId(r.id)}
                onSaved={(u) => {
                  setRuns((prev) => prev.map((x) => (x.id === u.id ? u : x)));
                  setEditingId(null);
                }}
              />
            ))}
          </tbody>
        </table>
      </div>

      {compareRuns && compareRuns.length >= 2 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Comparison</h3>
            <button
              onClick={() => setCompareRuns(null)}
              className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-slate-300"
            >
              Close
            </button>
          </div>
          <RunCompare runs={compareRuns} />
        </div>
      )}

      {deleteId && (
        <ConfirmModal
          title="Delete this run?"
          message="This permanently removes the saved snapshot and its metadata. This cannot be undone."
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={confirmDelete}
          onCancel={() => setDeleteId(null)}
        />
      )}

      {bulkDeleteOpen && (
        <ConfirmModal
          title={`Delete ${selected.size} run${selected.size === 1 ? "" : "s"}?`}
          message="This permanently removes the selected snapshots and their metadata. This cannot be undone."
          confirmLabel={`Delete ${selected.size}`}
          confirmVariant="danger"
          onConfirm={confirmBulkDelete}
          onCancel={() => setBulkDeleteOpen(false)}
        />
      )}
    </div>
  );
}

function RunRow({
  run,
  checked,
  editing,
  viewing,
  canEdit,
  onToggle,
  onView,
  onEdit,
  onDelete,
  onSaved,
}: {
  run: RetrievalRunSummary;
  checked: boolean;
  editing: boolean;
  viewing: boolean;
  canEdit: boolean;
  onToggle: () => void;
  onView: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onSaved: (u: RetrievalRunRecord) => void;
}) {
  const k = run.max_k ?? "";
  return (
    <>
      <tr
        onClick={onView}
        title="Show this run in the metrics panel above"
        className={`border-b border-gray-100/50 dark:border-slate-800/50 align-top cursor-pointer ${
          viewing
            ? "bg-indigo-50/70 dark:bg-indigo-500/10"
            : "hover:bg-gray-50/70 dark:hover:bg-slate-800/30"
        }`}
      >
        <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            className="rounded border-gray-300 dark:border-slate-600"
          />
        </td>
        <td className="px-3 py-2.5">
          <div className="font-medium text-gray-900 dark:text-white">
            {run.name || <span className="text-gray-400 dark:text-slate-500">Unnamed run</span>}
          </div>
          <div className="text-[11px] text-gray-400 dark:text-slate-500">
            {new Date(run.created_at).toLocaleString()} ·{" "}
            {run.dataset_names.length === 1
              ? run.dataset_names[0]
              : `${run.dataset_names.length} datasets`}{" "}
            · {run.gold_source === "ai" ? "AI" : run.gold_source} gold
            {(run.min_grade ?? 1) > 1 && (
              <span title="Strict binarization: only chunks labeled at or above this grade counted as relevant">
                {" "}
                · grade {run.min_grade}+
              </span>
            )}
          </div>
          {run.notes && (
            <div className="text-[11px] text-gray-500 dark:text-slate-400 mt-0.5 max-w-xs truncate" title={run.notes}>
              {run.notes}
            </div>
          )}
        </td>
        <td className="px-3 py-2.5 text-[12px] text-gray-600 dark:text-slate-400">
          <div className="truncate max-w-[200px]">{run.pipeline_version || "—"}</div>
          <div className="truncate max-w-[200px] text-gray-400 dark:text-slate-500">
            {run.index_name ? `${run.index_name}${run.index_version ? ` · ${run.index_version}` : ""}` : "—"}
          </div>
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums">
          {pct(run.recall)}
          <span className="text-[10px] text-gray-400 ml-0.5">@{k}</span>
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums">{pct(run.ndcg)}</td>
        <td className="px-3 py-2.5 text-right tabular-nums">{dec(run.mrr)}</td>
        <td className="px-3 py-2.5 text-right tabular-nums text-gray-500 dark:text-slate-400">
          {run.evaluated_cases}/{run.total_cases}
        </td>
        <td className="px-3 py-2.5 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          {canEdit && (
            <>
              <button onClick={onEdit} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                {editing ? "Close" : "Edit"}
              </button>
              <button onClick={onDelete} className="text-xs text-red-500 hover:underline ml-3">
                Delete
              </button>
            </>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-gray-100/50 dark:border-slate-800/50">
          <td colSpan={8} className="px-3 pb-3 bg-gray-50/50 dark:bg-slate-800/20">
            <RunMetadataEditor run={run} canEdit={canEdit} onSaved={onSaved} />
          </td>
        </tr>
      )}
    </>
  );
}
