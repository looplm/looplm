"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { getEvalReports, deleteEvalReport } from "@/lib/api";
import type { EvalReportListResponse } from "@/lib/api-types";
import { StatCard } from "@/components/eval-shared";
import { ConfirmModal } from "@/components/confirm-modal";

export default function ReportsPage() {
  const [resp, setResp] = useState<EvalReportListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEvalReports({ page: String(page), per_page: "50" });
      setResp(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  async function handleConfirmDelete() {
    if (!deleteConfirm) return;
    const id = deleteConfirm;
    setDeleteConfirm(null);
    try {
      await deleteEvalReport(id);
      toast.success("Report deleted");
      await loadReports();
    } catch {
      toast.error("Failed to delete report");
    }
  }

  const reports = resp?.data || [];
  const totalReports = resp?.pagination.total || 0;

  return (
    <div>
      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Reports" value={totalReports} />
        <StatCard
          label="Latest Report"
          value={reports.length > 0 ? reports[0].title : "—"}
          sub={reports.length > 0 ? new Date(reports[0].created_at).toLocaleDateString("de-DE") : undefined}
        />
        <StatCard
          label="Total Runs Analyzed"
          value={reports.reduce((sum, r) => sum + r.run_count, 0)}
          sub="across loaded reports"
        />
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : reports.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No reports yet. Generate a report from the Runs tab by selecting runs and clicking &quot;Generate Report&quot;.
        </div>
      ) : (
        <>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-3 font-medium">Title</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium text-center">Runs</th>
                  <th className="px-4 py-3 font-medium text-center">Tests</th>
                  <th className="px-4 py-3 font-medium w-24"></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr key={report.id} className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3">
                      <Link
                        href={`/evaluations/reports/${report.id}`}
                        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                      >
                        {report.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
                        {report.report_type === "multi_run" ? "Multi-run" : "Single run"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {new Date(report.created_at).toLocaleString("de-DE", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3 text-center">{report.run_count}</td>
                    <td className="px-4 py-3 text-center">{report.total_tests}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setDeleteConfirm(report.id)}
                        className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                        title="Delete"
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

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <ConfirmModal
          title="Delete Report"
          message="Delete this report? This action cannot be undone."
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}
    </div>
  );
}
