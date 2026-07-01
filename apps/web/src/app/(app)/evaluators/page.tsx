"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import {
  getEvaluators,
  type EvaluatorItem,
  type EvaluatorListResponse,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { ConfirmModal } from "@/components/confirm-modal";
import { EvaluatorModal, type EvaluatorFormData } from "./evaluator-modal";
import { EvaluatorTableBody, type SortKey, type SortDir, type SortEntry } from "./evaluator-table";
import { useEvaluatorActions } from "./evaluator-actions";
import Tooltip from "@/components/tooltip";
import { usePermissions } from "@/components/permissions-context";

const RELEVANCE_ORDER: Record<string, number> = { core: 0, important: 1, minor: 2 };

const READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export default function EvaluatorsPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("evaluators");
  const searchParams = useSearchParams();
  const highlightName = searchParams.get("highlight") || undefined;
  const [resp, setResp] = useState<EvaluatorListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingEvaluator, setEditingEvaluator] = useState<EvaluatorItem | null>(null);
  const [importing, setImporting] = useState(false);
  const [sorts, setSorts] = useState<SortEntry[]>([
    { key: "relevance", dir: "asc" },
    { key: "source", dir: "asc" },
    { key: "type", dir: "asc" },
    { key: "affects_pass", dir: "asc" },
  ]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[] } | null>(null);

  const evaluators = resp?.data || [];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEvaluators();
      setResp(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const {
    fileInputRef,
    handleImportFile,
    handleExport,
    handleSave,
    handleConfirmDelete,
    handleToggleEnabled,
  } = useEvaluatorActions({
    evaluators,
    editingEvaluator,
    setError,
    setImporting,
    setShowModal,
    setEditingEvaluator,
    load,
  });

  function handleSort(key: SortKey, shiftKey: boolean) {
    setSorts((prev) => {
      if (shiftKey) {
        const idx = prev.findIndex((s) => s.key === key);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = { key, dir: prev[idx].dir === "asc" ? "desc" : "asc" };
          return updated;
        }
        return [...prev, { key, dir: "asc" }];
      }
      if (prev.length === 1 && prev[0].key === key) {
        return [{ key, dir: prev[0].dir === "asc" ? "desc" : "asc" }];
      }
      return [{ key, dir: "asc" }];
    });
  }

  // Clear selection when data changes
  useEffect(() => { setSelectedIds(new Set()); }, [resp]);

  function handleDeleteClick(id: string) {
    setDeleteConfirm({ ids: [id] });
  }

  function handleBulkDelete() {
    if (selectedIds.size === 0) return;
    setDeleteConfirm({ ids: Array.from(selectedIds) });
  }

  async function handleConfirmDeleteAndClose() {
    if (!deleteConfirm) return;
    const { ids } = deleteConfirm;
    setDeleteConfirm(null);
    await handleConfirmDelete(ids);
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === evaluators.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(evaluators.map((e) => e.id)));
    }
  }

  const activeCount = evaluators.filter((e) => e.enabled).length;
  const avgPassRate =
    evaluators.filter((e) => e.pass_rate != null).length > 0
      ? evaluators.filter((e) => e.pass_rate != null).reduce((sum, e) => sum + (e.pass_rate || 0), 0) /
        evaluators.filter((e) => e.pass_rate != null).length
      : null;
  const allSelected = evaluators.length > 0 && selectedIds.size === evaluators.length;

  const sortedEvaluators = useMemo(() => {
    function compareByKey(a: EvaluatorItem, b: EvaluatorItem, key: SortKey): number {
      switch (key) {
        case "name":
          return (a.display_name || a.name).localeCompare(b.display_name || b.name);
        case "source":
          return (a.source || "").localeCompare(b.source || "");
        case "type":
          return a.type.localeCompare(b.type);
        case "relevance":
          return (RELEVANCE_ORDER[a.relevance] ?? 9) - (RELEVANCE_ORDER[b.relevance] ?? 9);
        case "affects_pass":
          return (a.affects_pass ? 0 : 1) - (b.affects_pass ? 0 : 1);
        case "total_evaluations":
          return a.total_evaluations - b.total_evaluations;
        case "pass_rate":
          return (a.pass_rate ?? -1) - (b.pass_rate ?? -1);
        case "last_seen_at": {
          const ta = a.last_seen_at ? new Date(a.last_seen_at).getTime() : 0;
          const tb = b.last_seen_at ? new Date(b.last_seen_at).getTime() : 0;
          return ta - tb;
        }
        case "enabled":
          return (a.enabled ? 0 : 1) - (b.enabled ? 0 : 1);
      }
    }

    return [...evaluators].sort((a, b) => {
      for (const { key, dir } of sorts) {
        const cmp = compareByKey(a, b, key);
        if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
      }
      return 0;
    });
  }, [evaluators, sorts]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Evaluators</h1>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            onChange={handleImportFile}
            className="hidden"
          />
          <Tooltip content="Export evaluators as JSON">
            <button
              onClick={handleExport}
              disabled={evaluators.length === 0}
              className="p-2 rounded-lg bg-gray-600 text-white hover:bg-gray-500 disabled:opacity-50 transition-colors"
              aria-label="Export JSON"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" /></svg>
            </button>
          </Tooltip>
          <Tooltip content={canEdit ? "Import evaluators from JSON file" : READ_ONLY_TITLE}>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing || !canEdit}
              className="p-2 rounded-lg bg-gray-600 text-white hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              aria-label="Import JSON"
            >
              {importing ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M6.34 6.34L3.51 3.51" /></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clipRule="evenodd" /></svg>
              )}
            </button>
          </Tooltip>
          <Tooltip content={canEdit ? "Create a new evaluator" : READ_ONLY_TITLE}>
            <button
              onClick={() => {
                setEditingEvaluator(null);
                setShowModal(true);
              }}
              disabled={!canEdit}
              className="p-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              aria-label="New Evaluator"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" /></svg>
            </button>
          </Tooltip>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm flex items-start justify-between gap-2">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 dark:hover:text-red-200 shrink-0">&times;</button>
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Evaluators" value={evaluators.length} />
        <StatCard label="Active" value={activeCount} sub={`${evaluators.length - activeCount} disabled`} />
        <StatCard
          label="Avg Pass Rate"
          value={avgPassRate != null ? `${(avgPassRate * 100).toFixed(1)}%` : "-"}
          sub="across evaluators with data"
        />
      </div>

      {/* Floating action bar */}
      {selectedIds.size > 0 && (
        <div className="mb-4 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800">
          <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkDelete}
            disabled={!canEdit}
            title={!canEdit ? READ_ONLY_TITLE : undefined}
            className="px-3 py-1 rounded-lg bg-red-600 text-white text-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Delete
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="px-3 py-1 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            Clear
          </button>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : evaluators.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          <p className="mb-2">No evaluators defined yet.</p>
          <p className="text-sm">Create one with the + button, or import evaluators from a JSON file.</p>
        </div>
      ) : (
        <EvaluatorTableBody
          sortedEvaluators={sortedEvaluators}
          selectedIds={selectedIds}
          allSelected={allSelected}
          sorts={sorts}
          highlightName={highlightName}
          toggleSelect={toggleSelect}
          toggleSelectAll={toggleSelectAll}
          handleSort={handleSort}
          handleToggleEnabled={handleToggleEnabled}
          handleDeleteClick={handleDeleteClick}
          onEdit={(ev) => {
            setEditingEvaluator(ev);
            setShowModal(true);
          }}
        />
      )}

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <ConfirmModal
          title="Delete Evaluator"
          message={
            deleteConfirm.ids.length === 1
              ? "Delete this evaluator? This action cannot be undone."
              : `Delete ${deleteConfirm.ids.length} evaluators? This action cannot be undone.`
          }
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleConfirmDeleteAndClose}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <EvaluatorModal
          editingEvaluator={editingEvaluator}
          onClose={() => {
            setShowModal(false);
            setEditingEvaluator(null);
          }}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
