"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  classifyEvalFailures,
  getEvalRun,
  getEvalResult,
  generateMultiRunReport,
  rerunEval,
  type RerunScope,
  type EvalResultItem,
  type EvalResultSummary,
} from "@/lib/api";
import { formatScoreValue, formatScoreLabel } from "./eval-utils";
import { EvalResultsTable } from "./eval-results-table";
import { TestResultModal } from "./test-result-modal";
import { CodeSuggestionsTab } from "./code-suggestions-tab";
import { toast } from "sonner";
import { RelevanceFilterDropdown } from "@/components/relevance-filter-dropdown";
import { usePermissions } from "@/components/permissions-context";
import { useEvalRun } from "./hooks/use-eval-run";
import { useGraderToggle } from "./hooks/use-grader-toggle";
import { useEvalFilters } from "./hooks/use-eval-filters";
import { GraderTogglePanel } from "@/components/eval/grader-toggle-panel";
import { StatsCards } from "@/components/eval/stats-cards";
import { FailureClassificationSection } from "@/components/eval/failure-classification-section";
import { ResultsFilterBar } from "@/components/eval/results-filter-bar";
import { ReportModal } from "@/components/eval/report-modal";

type Tab = "results" | "suggestions";

export default function EvalRunDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const { canWrite } = usePermissions();
  const canEdit = canWrite("evaluations");

  const { run, setRun, loading, evaluatorMap, allGraderNames } = useEvalRun(id);
  const { disabledGraders, toggleGrader, computedResults } = useGraderToggle(run);
  const {
    filter,
    setFilter,
    patternFilter,
    setPatternFilter,
    patternMode,
    setPatternMode,
    rootCauseFilter,
    setRootCauseFilter,
    testIdFilter,
    setTestIdFilter,
    filteredResults,
    computedStats,
    subsetFilterActive,
    visibleFailingTestIds,
    failurePatternSummary,
    rootCauseSummary,
  } = useEvalFilters(run, computedResults);

  const [selectedResult, setSelectedResult] = useState<EvalResultItem | null>(null);
  const [loadingResultId, setLoadingResultId] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<Tab>("results");
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [rerunningScope, setRerunningScope] = useState<string | null>(null);
  const [selectedTestIds, setSelectedTestIds] = useState<Set<string>>(new Set());
  const [classifying, setClassifying] = useState(false);

  const handleSelectResult = useCallback(
    async (summary: EvalResultSummary) => {
      setLoadingResultId(summary.id);
      try {
        const full = await getEvalResult(id, summary.id);
        setSelectedResult(full);
      } catch (err: any) {
        toast.error("Failed to load test result", { description: err?.message });
      } finally {
        setLoadingResultId(null);
      }
    },
    [id],
  );

  async function handleRerun(scope?: RerunScope, testIds?: string[]) {
    setRerunningScope(scope ?? "all");
    try {
      const res = await rerunEval(id, scope ? { scope, testIds } : undefined);
      router.push(`/evaluations/jobs?highlight=${res.job_id}`);
    } catch (err: any) {
      toast.error("Failed to start rerun", { description: err?.message });
      setRerunningScope(null);
    }
  }

  const toggleSelectTestId = useCallback((testId: string) => {
    setSelectedTestIds((prev) => {
      const next = new Set(prev);
      if (next.has(testId)) next.delete(testId);
      else next.add(testId);
      return next;
    });
  }, []);

  const toggleSelectAllTestIds = useCallback(() => {
    setSelectedTestIds((prev) => {
      if (prev.size === filteredResults.length) return new Set<string>();
      return new Set(filteredResults.map((r) => r.test_id));
    });
  }, [filteredResults]);

  async function handleClassifyFailures() {
    setClassifying(true);
    try {
      await classifyEvalFailures(id);
      const refreshed = await getEvalRun(id);
      setRun(refreshed);
      toast.success("Failures classified");
    } catch (err: any) {
      toast.error("Failed to classify failures", { description: err?.message });
    } finally {
      setClassifying(false);
    }
  }

  async function handleGenerateReport(relevanceFilter?: string[]) {
    setReportLoading(true);
    try {
      const result = await generateMultiRunReport([id], relevanceFilter);
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
    a.download = `eval-report-${id}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Report downloaded");
  }

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  }

  if (!run) {
    return <p className="text-red-500">Evaluation run not found.</p>;
  }

  return (
    <div>
      <div className="mb-6">
        <button
          onClick={() => router.back()}
          className="text-sm text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 mb-1"
        >
          &larr; Back to Evaluations
        </button>
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">{run.name}</h2>
          {run.source && (
            <span className="text-sm text-gray-400 dark:text-slate-500 px-2 py-0.5 rounded-md bg-gray-100 dark:bg-slate-800">
              {run.source}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {run.failed > 0 && (
              <button
                onClick={handleClassifyFailures}
                disabled={classifying}
                title="Classify each failure by which grader failed (and detect when the assistant asked a clarifying question)"
                className="px-4 py-2 rounded-lg text-sm font-medium border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {classifying
                  ? "Classifying..."
                  : failurePatternSummary
                    ? "Reclassify failures"
                    : "Classify failures"}
              </button>
            )}
            {run.source === "triggered" && canEdit && run.failed > 0 && (
              <button
                onClick={() => handleRerun("failed")}
                disabled={rerunningScope !== null}
                title="Rerun all failed test cases as a new linked run. Uses stored results — ignores grader toggles."
                className="px-4 py-2 rounded-lg text-sm font-medium border border-red-400 dark:border-red-500/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-600/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {rerunningScope === "failed" ? "Starting..." : `Rerun failed (${run.failed})`}
              </button>
            )}
            {run.source === "triggered" && canEdit && (
              <button
                onClick={() => handleRerun()}
                disabled={rerunningScope !== null}
                className="px-4 py-2 rounded-lg text-sm font-medium border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {rerunningScope === "all" ? "Starting..." : "Rerun"}
              </button>
            )}
            <RelevanceFilterDropdown
              onGenerate={handleGenerateReport}
              loading={reportLoading}
            />
          </div>
        </div>
        {(run.rerun_of || (run.reruns?.length ?? 0) > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            {run.rerun_of && (
              <Link
                href={`/evaluations/${run.rerun_of.id}`}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 dark:bg-indigo-600/10 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-500/30 hover:bg-indigo-100 dark:hover:bg-indigo-600/20 transition-colors"
                title={`Original run: ${run.rerun_of.passed}/${run.rerun_of.total} passed`}
              >
                ↩ Rerun of: {run.rerun_of.name}
              </Link>
            )}
            {(run.reruns?.length ?? 0) > 0 && (
              <span className="inline-flex flex-wrap items-center gap-1.5 text-gray-500 dark:text-slate-400">
                Reruns:
                {(run.reruns ?? []).map((r) => (
                  <Link
                    key={r.id}
                    href={`/evaluations/${r.id}`}
                    className="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                    title={r.name}
                  >
                    {new Date(r.created_at).toLocaleString()} · {r.passed}/{r.total} passed
                  </Link>
                ))}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Dead-letter queue: results that didn't run representatively */}
      {(() => {
        const counts = (run.metadata as Record<string, unknown> | undefined)
          ?.execution_counts as { degraded?: number; error?: number } | undefined;
        const degraded = counts?.degraded ?? 0;
        const errored = counts?.error ?? 0;
        const dlq = degraded + errored;
        if (dlq === 0) return null;
        const parts = [
          degraded ? `${degraded} degraded` : null,
          errored ? `${errored} errored` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return (
          <div className="mb-6 rounded-xl border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-900/15 px-4 py-3 flex items-center gap-3">
            <span className="text-sm text-amber-800 dark:text-amber-300">
              <span className="font-semibold">
                {dlq} result{dlq === 1 ? "" : "s"} did not run representatively
              </span>{" "}
              ({parts}), so they are excluded from the pass rate. Degraded means the target fell
              back to keyword-only retrieval (embeddings throttled); errored means the call failed
              after retries.
            </span>
            {run.source === "triggered" && canEdit && (
              <button
                onClick={() => handleRerun("dlq")}
                disabled={rerunningScope !== null}
                title="Rerun only the degraded/errored results as a new linked run"
                className="ml-auto shrink-0 px-4 py-2 rounded-lg text-sm font-medium border border-amber-400 dark:border-amber-500/60 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-600/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {rerunningScope === "dlq" ? "Starting..." : `Retry ${dlq} not run`}
              </button>
            )}
          </div>
        );
      })()}

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 mb-6 border-b border-gray-200 dark:border-slate-700">
        {(["results", "suggestions"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 hover:border-gray-300 dark:hover:border-slate-600"
            }`}
          >
            {tab === "results" ? "Results" : "Code Suggestions"}
          </button>
        ))}
      </div>

      {activeTab === "suggestions" && <CodeSuggestionsTab evalRunId={id} />}

      {activeTab === "results" && (<>
      {/* Grader Toggle Panel */}
          <GraderTogglePanel
            allGraderNames={allGraderNames}
            run={run}
            evaluatorMap={evaluatorMap}
            disabledGraders={disabledGraders}
            onToggleGrader={toggleGrader}
          />

          {/* Stat Cards */}
          <StatsCards run={run} computedStats={computedStats} disabledGraders={disabledGraders} />

          {/* Failure classification (root cause + failure pattern) */}
          <FailureClassificationSection
            rootCauseSummary={rootCauseSummary}
            rootCauseFilter={rootCauseFilter}
            setRootCauseFilter={setRootCauseFilter}
            failurePatternSummary={failurePatternSummary}
            patternFilter={patternFilter}
            setPatternFilter={setPatternFilter}
            patternMode={patternMode}
            setPatternMode={setPatternMode}
          />

          {/* Filter + bulk selection */}
          <ResultsFilterBar
            run={run}
            canEdit={canEdit}
            filter={filter}
            setFilter={setFilter}
            computedStats={computedStats}
            testIdFilter={testIdFilter}
            setTestIdFilter={setTestIdFilter}
            subsetFilterActive={subsetFilterActive}
            visibleFailingTestIds={visibleFailingTestIds}
            rerunningScope={rerunningScope}
            onRerun={handleRerun}
            selectedTestIds={selectedTestIds}
            setSelectedTestIds={setSelectedTestIds}
          />

          {/* Results Table */}
          <EvalResultsTable
            filteredResults={filteredResults}
            disabledGraders={disabledGraders}
            evaluatorMap={evaluatorMap}
            onSelectResult={handleSelectResult}
            loadingResultId={loadingResultId}
            selectable={run.source === "triggered" && canEdit}
            selectedTestIds={selectedTestIds}
            onToggleSelect={toggleSelectTestId}
            onToggleSelectAll={toggleSelectAllTestIds}
          />

          {selectedResult && (
            <TestResultModal
              result={selectedResult}
              disabledGraders={disabledGraders}
              evaluatorMap={evaluatorMap}
              runMetadata={run.metadata}
              onClose={() => setSelectedResult(null)}
            />
          )}

          {/* Score Summary */}
          {Object.keys(run.score_summary || {}).length > 0 && (
            <div className="mt-8">
              <h2 className="text-lg font-semibold mb-4">Score Summary</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(run.score_summary).map(([name, s]) => (
                  <div key={name} className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
                    <p className="text-sm text-gray-500 dark:text-slate-400 mb-1" title={name}>
                      Average {formatScoreLabel(name).toLowerCase()}
                    </p>
                    <p className="text-xl font-bold">{formatScoreValue(name, s.avg)}</p>
                    <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                      min {formatScoreValue(name, s.min)} / max {formatScoreValue(name, s.max)} ({s.count} samples)
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

      </>)}

          {/* Report Modal */}
          {showReportModal && reportMarkdown && (
            <ReportModal
              reportMarkdown={reportMarkdown}
              onCopy={handleCopyMarkdown}
              onDownload={handleDownloadMarkdown}
              onClose={() => setShowReportModal(false)}
            />
          )}
    </div>
  );
}
