"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  getEvalRuns,
  deleteEvalRun,
  bulkDeleteEvalRuns,
  generateMultiRunReport,
  type EvalRunListResponse,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { ConfirmModal } from "@/components/confirm-modal";
import { RelevanceFilterDropdown } from "@/components/relevance-filter-dropdown";
import { CompareRunsModal } from "@/components/compare-runs-modal";
import { usePermissions } from "@/components/permissions-context";

export default function EvaluationsPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("evaluations");
  const readOnlyTitle = "Read-only access. Ask an admin to grant write permission.";
  const [resp, setResp] = useState<EvalRunListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[] } | null>(null);
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [nameFilter, setNameFilter] = useState("");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEvalRuns({ page: String(page), per_page: "50" });
      setResp(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

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
        await deleteEvalRun(ids[0]);
        toast.success("Evaluation run deleted");
      } else {
        await bulkDeleteEvalRuns(ids);
        toast.success(`${ids.length} evaluation runs deleted`);
      }
      setSelectedIds(new Set());
      await loadRuns();
    } catch {
      toast.error("Failed to delete evaluation run(s)");
    }
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
    if (selectedIds.size === filteredRuns.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredRuns.map((r) => r.id)));
    }
  }

  async function handleGenerateReport(relevanceFilter?: string[]) {
    if (selectedIds.size === 0) return;
    setReportLoading(true);
    try {
      const result = await generateMultiRunReport(Array.from(selectedIds), relevanceFilter);
      setReportMarkdown(result.markdown);
      setShowReportModal(true);
    } catch (err: any) {
      toast.error("Failed to generate report", { description: err.message });
    } finally {
      setReportLoading(false);
    }
  }

  function handleCopyMarkdown() {
    if (!reportMarkdown) return;
    navigator.clipboard.writeText(reportMarkdown);
    toast.success("Markdown copied to clipboard");
  }

  function handleDownloadMarkdown() {
    if (!reportMarkdown) return;
    const blob = new Blob([reportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `eval-report-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Report downloaded");
  }

  const runs = resp?.data || [];
  const filteredRuns = nameFilter
    ? runs.filter((r) => r.name.toLowerCase().includes(nameFilter.toLowerCase()))
    : runs;
  const totalRuns = resp?.pagination.total || 0;
  const totalTests = filteredRuns.reduce((sum, r) => sum + r.passed + r.failed, 0);
  const latestPassRate = filteredRuns.length > 0 ? filteredRuns[0].pass_rate : 0;
  const allSelected = filteredRuns.length > 0 && selectedIds.size === filteredRuns.length;

  return (
    <div>
      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Runs" value={totalRuns} />
        <StatCard
          label="Latest Pass Rate"
          value={`${(latestPassRate * 100).toFixed(1)}%`}
          sub={runs.length > 0 ? runs[0].name : undefined}
        />
        <StatCard label="Total Test Cases" value={totalTests} sub="across loaded runs" />
      </div>

      {/* Name filter */}
      <div className="relative mb-4">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          value={nameFilter}
          onChange={(e) => setNameFilter(e.target.value)}
          placeholder="Filter by name..."
          className="w-full sm:w-72 pl-9 pr-8 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-gray-900 dark:text-slate-100 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        {nameFilter && (
          <button
            onClick={() => setNameFilter("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      {/* Floating action bar */}
      {selectedIds.size > 0 && (
        <div className="mb-4 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800">
          <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">
            {selectedIds.size} selected
          </span>
          <RelevanceFilterDropdown
            onGenerate={handleGenerateReport}
            loading={reportLoading}
            disabled={!canEdit}
            disabledTitle={readOnlyTitle}
            buttonClassName="px-3 py-1 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
          />
          {selectedIds.size >= 2 && (
            <button
              onClick={() => setShowCompareModal(true)}
              className="px-3 py-1 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 transition-colors"
            >
              Compare
            </button>
          )}
          <button
            onClick={handleBulkDelete}
            disabled={!canEdit}
            title={!canEdit ? readOnlyTitle : undefined}
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
      ) : filteredRuns.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          {nameFilter ? "No runs match your filter." : "No evaluation runs yet. Import a JSON result file to get started."}
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
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium text-center">Total</th>
                  <th className="px-4 py-3 font-medium text-center">Passed</th>
                  <th className="px-4 py-3 font-medium text-center">Failed</th>
                  <th className="px-4 py-3 font-medium">Pass Rate</th>
                  <th className="px-4 py-3 font-medium w-24"></th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.map((run) => (
                  <tr key={run.id} className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(run.id)}
                        onChange={() => toggleSelect(run.id)}
                        className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/evaluations/${run.id}`}
                        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                      >
                        {run.name}
                      </Link>
                      {run.source && (
                        <span className="ml-2 text-xs text-gray-400 dark:text-slate-500">
                          {run.source}
                        </span>
                      )}
                      {run.tags.length > 0 && (
                        <div className="flex gap-1 mt-1">
                          {run.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {new Date(run.created_at).toLocaleString("de-DE", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3 text-center">{run.total}</td>
                    <td className="px-4 py-3 text-center text-green-600 dark:text-green-400">{run.passed}</td>
                    <td className="px-4 py-3 text-center text-red-600 dark:text-red-400">{run.failed}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden max-w-[100px]">
                          <div
                            className={`h-full rounded-full ${
                              run.pass_rate >= 0.8
                                ? "bg-green-500"
                                : run.pass_rate >= 0.5
                                ? "bg-yellow-500"
                                : "bg-red-500"
                            }`}
                            style={{ width: `${run.pass_rate * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500 dark:text-slate-400 w-10">
                          {(run.pass_rate * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleDeleteClick(run.id)}
                        disabled={!canEdit}
                        className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        title={canEdit ? "Delete" : readOnlyTitle}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
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
      {/* Report modal */}
      {showReportModal && reportMarkdown && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col mx-4">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Evaluation Report</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyMarkdown}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                >
                  Copy Markdown
                </button>
                <button
                  onClick={handleDownloadMarkdown}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                >
                  Download
                </button>
                <button
                  onClick={() => setShowReportModal(false)}
                  className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <pre className="text-sm text-gray-800 dark:text-slate-200 whitespace-pre-wrap font-mono leading-relaxed">{reportMarkdown}</pre>
            </div>
          </div>
        </div>
      )}
      {/* Compare modal */}
      {showCompareModal && (
        <CompareRunsModal
          runs={filteredRuns.filter((r) => selectedIds.has(r.id))}
          onClose={() => setShowCompareModal(false)}
        />
      )}
      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <ConfirmModal
          title="Delete Evaluation Run"
          message={
            deleteConfirm.ids.length === 1
              ? "Delete this evaluation run and all its results? This action cannot be undone."
              : `Delete ${deleteConfirm.ids.length} evaluation runs and all their results? This action cannot be undone.`
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
