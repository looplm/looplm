"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  getDatasets,
  deleteDataset,
  bulkDeleteDatasets,
  exportDataset,
  importDataset,
  type TestDatasetListResponse,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { ConfirmModal } from "@/components/confirm-modal";
import Tooltip from "@/components/tooltip";
import { usePermissions } from "@/components/permissions-context";

const READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export default function DatasetsPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("datasets");
  const [resp, setResp] = useState<TestDatasetListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [importing, setImporting] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[] } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getDatasets({ page: String(page), per_page: "50" });
      setResp(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  // Clear selection when data changes
  useEffect(() => { setSelectedIds(new Set()); }, [resp]);

  function handleDeleteClick(id: string) {
    setDeleteConfirm({ ids: [id] });
  }

  function handleBulkDelete() {
    if (selectedIds.size === 0) return;
    setDeleteConfirm({ ids: Array.from(selectedIds) });
  }

  async function handleConfirmDelete() {
    if (!deleteConfirm) return;
    const { ids } = deleteConfirm;
    setDeleteConfirm(null);
    try {
      if (ids.length === 1) {
        await deleteDataset(ids[0]);
      } else {
        await bulkDeleteDatasets(ids);
      }
      await load();
    } catch {
      // ignore
    }
  }

  async function handleExport(id: string, name: string) {
    try {
      const data = await exportDataset(id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${name.toLowerCase().replace(/\s+/g, "-")}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const count = files.length;
    setImporting(count === 1 ? "Importing..." : `Importing ${count} files...`);
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const text = await file.text();
        const json = JSON.parse(text);
        // Support both legacy test-case files and the native LoopLM export format
        const testCases = json.testCases || json;
        const name = json.name || file.name.replace(/\.json$/, "");
        await importDataset({ name, description: json.description, testCases: Array.isArray(testCases) ? testCases : [], filename: file.name });
      } catch {
        errors.push(file.name);
      }
    }
    setImporting(null);
    await load();
    if (errors.length > 0) {
      alert(`Failed to import: ${errors.join(", ")}`);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
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
    if (selectedIds.size === datasets.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(datasets.map((d) => d.id)));
    }
  }

  const datasets = resp?.data || [];
  const totalDatasets = resp?.pagination.total || 0;
  const totalCases = datasets.reduce((sum, d) => sum + d.test_count, 0);
  const allSelected = datasets.length > 0 && selectedIds.size === datasets.length;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Test Datasets</h1>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            multiple
            className="hidden"
            onChange={handleImport}
          />
          <Tooltip content={canEdit ? "Import dataset from JSON file" : READ_ONLY_TITLE}>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={!!importing || !canEdit}
              className="p-2 rounded-lg bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Import JSON"
            >
              {importing ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M6.34 6.34L3.51 3.51" /></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clipRule="evenodd" /></svg>
              )}
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Datasets" value={totalDatasets} />
        <StatCard label="Total Test Cases" value={totalCases} sub="across all datasets" />
        <StatCard label="Avg Cases / Dataset" value={totalDatasets > 0 ? Math.round(totalCases / totalDatasets) : 0} />
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
      ) : datasets.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No datasets yet. Import a JSON file to get started.
        </div>
      ) : (
        <>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                    />
                  </th>
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium text-center">Test Cases</th>
                  <th className="px-4 py-3 font-medium">Tags</th>
                  <th className="px-4 py-3 font-medium">Updated</th>
                  <th className="px-4 py-3 font-medium w-20"></th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((ds) => (
                  <tr key={ds.id} className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(ds.id)}
                        onChange={() => toggleSelect(ds.id)}
                        className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/datasets/${ds.id}`}
                        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                      >
                        {ds.name}
                      </Link>
                      {ds.description && (
                        <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5 truncate max-w-xs">
                          {ds.description}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">{ds.test_count}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 flex-wrap">
                        {ds.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {new Date(ds.updated_at).toLocaleString("de-DE", {
                        day: "2-digit", month: "2-digit", year: "2-digit",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => handleExport(ds.id, ds.name)}
                          className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                          title="Download JSON"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" y1="15" x2="12" y2="3" />
                          </svg>
                        </button>
                        <button
                          onClick={() => handleDeleteClick(ds.id)}
                          disabled={!canEdit}
                          className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          title={canEdit ? "Delete" : READ_ONLY_TITLE}
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {resp && resp.pagination.total_pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500 dark:text-slate-400">
                Page {resp.pagination.page} of {resp.pagination.total_pages} ({resp.pagination.total} total)
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 disabled:opacity-40"
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(resp!.pagination.total_pages, p + 1))}
                  disabled={page >= resp.pagination.total_pages}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <ConfirmModal
          title="Delete Dataset"
          message={
            deleteConfirm.ids.length === 1
              ? "Delete this dataset and all its test cases? This action cannot be undone."
              : `Delete ${deleteConfirm.ids.length} datasets and all their test cases? This action cannot be undone.`
          }
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}
    </div>
  );
}
