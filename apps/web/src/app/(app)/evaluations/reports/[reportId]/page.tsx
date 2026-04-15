"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { getEvalReportById, deleteEvalReport } from "@/lib/api";
import type { EvalReportDetail } from "@/lib/api-types";
import { ConfirmModal } from "@/components/confirm-modal";

export default function ReportDetailPage() {
  const params = useParams();
  const router = useRouter();
  const reportId = params.reportId as string;

  const [report, setReport] = useState<EvalReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const data = await getEvalReportById(reportId);
        setReport(data);
      } catch {
        toast.error("Failed to load report");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [reportId]);

  function handleCopyMarkdown() {
    if (!report) return;
    navigator.clipboard.writeText(report.markdown);
    toast.success("Markdown copied to clipboard");
  }

  function handleDownloadMarkdown() {
    if (!report) return;
    const blob = new Blob([report.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.title.replace(/[^a-zA-Z0-9-_ ]/g, "")}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Report downloaded");
  }

  async function handleConfirmDelete() {
    setDeleteConfirm(false);
    try {
      await deleteEvalReport(reportId);
      toast.success("Report deleted");
      router.push("/evaluations/reports");
    } catch {
      toast.error("Failed to delete report");
    }
  }

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  }

  if (!report) {
    return <p className="text-gray-500 dark:text-slate-400">Report not found.</p>;
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <button
            onClick={() => router.push("/evaluations/reports")}
            className="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 mb-1"
          >
            &larr; Back to Reports
          </button>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{report.title}</h2>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
            {new Date(report.created_at).toLocaleString("de-DE", {
              day: "2-digit",
              month: "2-digit",
              year: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}
            {" · "}
            {report.run_count} run{report.run_count !== 1 ? "s" : ""}
            {" · "}
            {report.total_tests} tests
          </p>
        </div>
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
            onClick={() => setDeleteConfirm(true)}
            className="px-3 py-1.5 rounded-lg bg-red-50 dark:bg-red-900/20 text-sm text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Report content */}
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
        <pre className="text-sm text-gray-800 dark:text-slate-200 whitespace-pre-wrap font-mono leading-relaxed">
          {report.markdown}
        </pre>
      </div>

      {/* Delete confirmation */}
      {deleteConfirm && (
        <ConfirmModal
          title="Delete Report"
          message="Delete this report? This action cannot be undone."
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteConfirm(false)}
        />
      )}
    </div>
  );
}
