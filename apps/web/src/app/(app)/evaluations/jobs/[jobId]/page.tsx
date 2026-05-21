"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getEvalJob,
  getEvalJobLogs,
  getEvalResult,
  getEvalRun,
  getEvaluators,
  generateMultiRunReport,
  stopEvalJob,
  restartEvalJob,
  type EvalJob,
  type EvalRunDetail,
  type EvalResultItem,
  type EvalResultSummary,
  type EvaluatorItem,
} from "@/lib/api";
import { JobStatusBadge, JobProgressBar, StatCard, formatDuration } from "@/components/eval-shared";
import { EvalResultsTable } from "../../[id]/eval-results-table";
import { TestResultModal } from "../../[id]/test-result-modal";
import { toast } from "sonner";

export default function EvalJobDetailPage() {
  const params = useParams();
  const jobId = params.jobId as string;

  const [job, setJob] = useState<EvalJob | null>(null);
  const [log, setLog] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const logRef = useRef<HTMLPreElement>(null);

  // Intermediate results state
  const [run, setRun] = useState<EvalRunDetail | null>(null);
  const [evaluatorMap, setEvaluatorMap] = useState<Record<string, EvaluatorItem>>({});
  const [selectedResult, setSelectedResult] = useState<EvalResultItem | null>(null);
  const [loadingResultId, setLoadingResultId] = useState<string | null>(null);
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [stopping, setStopping] = useState(false);

  const loadJob = useCallback(async () => {
    try {
      const data = await getEvalJob(jobId);
      setJob(data);
      return data;
    } catch {
      // ignore
      return null;
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const loadLogs = useCallback(async () => {
    try {
      const data = await getEvalJobLogs(jobId);
      setLog(data.log);
    } catch {
      // ignore
    }
  }, [jobId]);

  const loadIntermediateResults = useCallback(async (runId: string) => {
    try {
      const [evalRun, evalResponse] = await Promise.all([
        getEvalRun(runId),
        evaluatorMap && Object.keys(evaluatorMap).length > 0
          ? Promise.resolve(null)
          : getEvaluators(),
      ]);
      setRun(evalRun);
      if (evalResponse) {
        const map: Record<string, EvaluatorItem> = {};
        for (const ev of evalResponse.data) {
          map[ev.name] = ev;
        }
        setEvaluatorMap(map);
      }
    } catch {
      // ignore — run may not have results yet
    }
  }, [evaluatorMap]);

  useEffect(() => {
    loadJob();
    loadLogs();
  }, [loadJob, loadLogs]);

  // Poll while active
  useEffect(() => {
    if (!job || (job.status !== "pending" && job.status !== "running" && job.status !== "batch_pending")) return;
    const pollMs = job.status === "batch_pending" ? 30000 : 3000;
    const interval = setInterval(async () => {
      const updatedJob = await loadJob();
      loadLogs();
      // Fetch intermediate results if run_id is available
      if (updatedJob?.run_id) {
        loadIntermediateResults(updatedJob.run_id);
      }
    }, pollMs);
    return () => clearInterval(interval);
  }, [job, loadJob, loadLogs, loadIntermediateResults]);

  // Load results once on mount if run_id already exists
  useEffect(() => {
    if (job?.run_id && !run) {
      loadIntermediateResults(job.run_id);
    }
  }, [job?.run_id, run, loadIntermediateResults]);

  // Auto-scroll logs
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const isActive = job?.status === "running" || job?.status === "pending" || job?.status === "batch_pending";

  const computedStats = useMemo(() => {
    if (!run?.results) return null;
    const total = run.results.length;
    const passed = run.results.filter((r) => r.pass).length;
    const failed = total - passed;
    return { total, passed, failed, passRate: total > 0 ? passed / total : 0 };
  }, [run?.results]);

  const handleSelectResult = useCallback(
    async (summary: EvalResultSummary) => {
      if (!job?.run_id) return;
      setLoadingResultId(summary.id);
      try {
        const full = await getEvalResult(job.run_id, summary.id);
        setSelectedResult(full);
      } catch (err: any) {
        toast.error("Failed to load test result", { description: err?.message });
      } finally {
        setLoadingResultId(null);
      }
    },
    [job?.run_id],
  );

  async function handleStop() {
    setStopping(true);
    try {
      await stopEvalJob(jobId);
      await loadJob();
      await loadLogs();
      toast.success("Job cancelled");
    } catch (err: any) {
      toast.error("Failed to stop job", { description: err.message });
    } finally {
      setStopping(false);
    }
  }

  async function handleRestart() {
    try {
      const result = await restartEvalJob(jobId);
      toast.success("Job restarted");
      window.location.href = `/evaluations/jobs/${result.job_id}`;
    } catch (err: any) {
      toast.error("Failed to restart job", { description: err.message });
    }
  }

  async function handleGenerateReport() {
    if (!job?.run_id) return;
    setReportLoading(true);
    try {
      const result = await generateMultiRunReport([job.run_id]);
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
    a.download = `eval-report-${job?.run_id || jobId}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Report downloaded");
  }

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  }

  if (!job) {
    return <p className="text-red-500">Job not found.</p>;
  }

  return (
    <div>
      {/* Back link */}
      <div className="mb-4">
        <Link
          href="/evaluations/jobs"
          className="text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 text-sm"
        >
          &larr; Back to Jobs
        </Link>
      </div>

      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <h2 className="text-2xl font-bold">{job.test_suite}</h2>
        <JobStatusBadge status={job.status} />
        {isActive && (
          <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
        )}
        <div className="ml-auto flex items-center gap-2">
          {isActive && (
            <button
              onClick={handleStop}
              disabled={stopping}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {stopping ? "Stopping..." : "Stop"}
            </button>
          )}
          {(job.status === "cancelled" || job.status === "failed") && (
            <button
              onClick={handleRestart}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
            >
              Restart
            </button>
          )}
          {job.run_id && computedStats && computedStats.total > 0 && (
            <button
              onClick={handleGenerateReport}
              disabled={reportLoading}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {reportLoading ? "Generating..." : isActive ? "Generate Interim Report" : "Generate Report"}
            </button>
          )}
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">Started</p>
          <p className="text-sm font-medium">
            {new Date(job.started_at).toLocaleString("de-DE", {
              day: "2-digit",
              month: "2-digit",
              year: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">Duration</p>
          <p className="text-sm font-medium">
            {formatDuration(job.started_at, job.completed_at)}
            {isActive && (
              <span className="text-blue-500 ml-0.5">...</span>
            )}
          </p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">Config</p>
          <p className="text-sm font-medium">
            {job.config?.filter_mode && job.config.filter_mode !== "as_configured"
              ? job.config.filter_mode
              : "filtered"}
            {job.config?.concurrency ? ` · ${job.config.concurrency}x` : ""}
            {job.config?.max_turns && job.config.max_turns > 1
              ? ` · ${job.config.max_turns} turns`
              : ""}
            {job.config?.use_batch && (
              <span className="ml-1 text-amber-600 dark:text-amber-400">· batch</span>
            )}
          </p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">Progress</p>
          {job.progress_current != null && job.progress_total != null && job.progress_total > 0 ? (
            <div>
              <p className="text-sm font-medium mb-1">
                {job.progress_current} / {job.progress_total}
              </p>
              <JobProgressBar job={job} />
            </div>
          ) : (
            <p className="text-sm font-medium text-gray-400 dark:text-slate-500">—</p>
          )}
        </div>
      </div>

      {/* Intermediate / Final Results */}
      {computedStats && computedStats.total > 0 && (
        <>
          {/* Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard label="Total" value={computedStats.total} />
            <StatCard label="Passed" value={computedStats.passed} accent={computedStats.passed > 0 ? "green" : undefined} />
            <StatCard label="Failed" value={computedStats.failed} accent={computedStats.failed > 0 ? "red" : undefined} />
            <StatCard
              label="Pass Rate"
              value={`${(computedStats.passRate * 100).toFixed(1)}%`}
              sub={isActive ? "in progress" : undefined}
              accent={computedStats.passRate === 1 ? "green" : computedStats.passRate === 0 && computedStats.total > 0 ? "red" : "amber"}
            />
          </div>

          {/* Results Table */}
          <div className="mb-6">
            <EvalResultsTable
              filteredResults={run?.results || []}
              disabledGraders={new Set()}
              evaluatorMap={evaluatorMap}
              onSelectResult={handleSelectResult}
              loadingResultId={loadingResultId}
            />
          </div>
        </>
      )}

      {/* View Full Results link (completed jobs) */}
      {job.status === "completed" && job.run_id && (
        <div className="mb-6">
          <Link
            href={`/evaluations/${job.run_id}`}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30 text-sm font-medium hover:bg-indigo-100 dark:hover:bg-indigo-600/30 transition-colors"
          >
            View Full Eval Results &rarr;
          </Link>
        </div>
      )}

      {/* Cancelled box */}
      {job.status === "cancelled" && (
        <div className="mb-6 p-4 rounded-xl bg-gray-50 dark:bg-gray-900/20 border border-gray-200 dark:border-gray-700">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Job was cancelled by user.</p>
        </div>
      )}

      {/* Error box */}
      {job.status === "failed" && job.error && (
        <div className="mb-6 p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
          <p className="text-sm font-medium text-red-700 dark:text-red-300 mb-1">Error</p>
          <pre className="text-sm text-red-600 dark:text-red-400 whitespace-pre-wrap break-words">
            {job.error}
          </pre>
        </div>
      )}

      {/* Log viewer */}
      <div>
        <p className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Logs</p>
        {log ? (
          <pre
            ref={logRef}
            className="p-4 rounded-xl bg-gray-50 dark:bg-slate-950 border border-gray-200 dark:border-slate-700 text-xs text-gray-700 dark:text-slate-300 font-mono overflow-auto max-h-[60vh] whitespace-pre-wrap"
          >
            {log}
          </pre>
        ) : (
          <div className="p-4 rounded-xl bg-gray-50 dark:bg-slate-950 border border-gray-200 dark:border-slate-700 text-xs text-gray-400 dark:text-slate-500">
            {isActive ? "Waiting for logs..." : "No logs available."}
          </div>
        )}
      </div>

      {/* Test Result Modal */}
      {selectedResult && (
        <TestResultModal
          result={selectedResult}
          disabledGraders={new Set()}
          evaluatorMap={evaluatorMap}
          onClose={() => setSelectedResult(null)}
        />
      )}

      {/* Report Modal */}
      {showReportModal && reportMarkdown && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col mx-4">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                {isActive ? "Interim Evaluation Report" : "Evaluation Report"}
              </h2>
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
    </div>
  );
}
