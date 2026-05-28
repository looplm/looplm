"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  classifyEvalFailures,
  getEvalRun,
  getEvalResult,
  getEvaluators,
  generateMultiRunReport,
  rerunEval,
  type EvalRunDetail,
  type EvalResultItem,
  type EvalResultSummary,
  type EvaluatorItem,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { recomputePass, passRateTextColor, graderDisplayName, formatScoreValue, formatScoreLabel } from "./eval-utils";
import { EvalResultsTable } from "./eval-results-table";
import { TestResultModal } from "./test-result-modal";
import { CodeSuggestionsTab } from "./code-suggestions-tab";
import { toast } from "sonner";
import { RelevanceFilterDropdown } from "@/components/relevance-filter-dropdown";
import FilterComboBox from "@/components/filter-combo-box";

type Filter = "all" | "passed" | "failed";
type Tab = "results" | "suggestions";

export default function EvalRunDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [run, setRun] = useState<EvalRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedResult, setSelectedResult] = useState<EvalResultItem | null>(null);
  const [loadingResultId, setLoadingResultId] = useState<string | null>(null);
  const [disabledGraders, setDisabledGraders] = useState<Set<string>>(new Set());
  const [evaluatorMap, setEvaluatorMap] = useState<Record<string, EvaluatorItem>>({});

  const [activeTab, setActiveTab] = useState<Tab>("results");
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [patternFilter, setPatternFilter] = useState<string[]>([]);
  const [patternMode, setPatternMode] = useState<"include" | "exclude">("include");
  const [classifying, setClassifying] = useState(false);
  useEffect(() => {
    setLoading(true);
    Promise.all([getEvalRun(id), getEvaluators()])
      .then(([evalRun, evalResponse]) => {
        setRun(evalRun);
        const map: Record<string, EvaluatorItem> = {};
        for (const ev of evalResponse.data) {
          map[ev.name] = ev;
        }
        setEvaluatorMap(map);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const allGraderNames = useMemo(() => {
    if (!run) return [];
    const entries = Object.entries(run.grader_summary);
    const relevanceOrder: Record<string, number> = { core: 0, important: 1, minor: 2 };
    entries.sort(([nameA], [nameB]) => {
      const metaA = evaluatorMap[nameA];
      const metaB = evaluatorMap[nameB];
      const apA = metaA?.affects_pass ? 0 : 1;
      const apB = metaB?.affects_pass ? 0 : 1;
      if (apA !== apB) return apA - apB;
      // Then by source (custom first, then ragas, then others)
      const sourceOrder: Record<string, number> = { custom: 0, ragas: 1, langfuse: 2, discovered: 3 };
      const srcA = sourceOrder[metaA?.source ?? "custom"] ?? 99;
      const srcB = sourceOrder[metaB?.source ?? "custom"] ?? 99;
      if (srcA !== srcB) return srcA - srcB;
      const relA = relevanceOrder[metaA?.relevance ?? "minor"] ?? 2;
      const relB = relevanceOrder[metaB?.relevance ?? "minor"] ?? 2;
      if (relA !== relB) return relA - relB;
      return nameA.localeCompare(nameB);
    });
    return entries.map(([name]) => name);
  }, [run, evaluatorMap]);

  const toggleGrader = useCallback((name: string) => {
    setDisabledGraders((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const computedResults = useMemo(() => {
    if (!run) return [];
    if (disabledGraders.size === 0) return run.results;
    return run.results.map((r) => ({
      ...r,
      pass: recomputePass(r, disabledGraders),
    }));
  }, [run, disabledGraders]);

  const patternFiltered = useMemo(() => {
    if (patternFilter.length === 0) return computedResults;
    const set = new Set(patternFilter);
    if (patternMode === "include") {
      // Keep only failed results whose pattern matches.
      return computedResults.filter((r) => r.failure_pattern && set.has(r.failure_pattern));
    }
    // Exclude: drop failed results whose pattern matches; passed tests stay.
    return computedResults.filter((r) => !r.failure_pattern || !set.has(r.failure_pattern));
  }, [computedResults, patternFilter, patternMode]);

  const filteredResults = useMemo(() => {
    if (filter === "all") return patternFiltered;
    return patternFiltered.filter((r) =>
      filter === "passed" ? r.pass : !r.pass
    );
  }, [patternFiltered, filter]);

  const computedStats = useMemo(() => {
    const total = patternFiltered.length;
    const passed = patternFiltered.filter((r) => r.pass).length;
    const failed = total - passed;
    return { total, passed, failed, passRate: total > 0 ? passed / total : 0 };
  }, [patternFiltered]);

  const failurePatternSummary = useMemo(() => {
    const fromRun = run?.metadata?.failure_pattern_summary;
    if (fromRun && typeof fromRun === "object") {
      return fromRun as Record<string, number>;
    }
    return null;
  }, [run]);

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

  async function handleRerun() {
    setRerunning(true);
    try {
      const res = await rerunEval(id);
      router.push(`/evaluations/jobs?highlight=${res.job_id}`);
    } catch {
      setRerunning(false);
    }
  }

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
            {run.source === "triggered" && (
              <button
                onClick={handleRerun}
                disabled={rerunning}
                className="px-4 py-2 rounded-lg text-sm font-medium border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {rerunning ? "Starting..." : "Rerun"}
              </button>
            )}
            <RelevanceFilterDropdown
              onGenerate={handleGenerateReport}
              loading={reportLoading}
            />
          </div>
        </div>
      </div>

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
          {allGraderNames.length > 0 && (() => {
            const passFailGraders = allGraderNames.filter((n) => evaluatorMap[n]?.affects_pass);
            const qualityGraders = allGraderNames.filter((n) => !evaluatorMap[n]?.affects_pass);

            const renderToggle = (name: string) => {
              const summary = run.grader_summary[name];
              const enabled = !disabledGraders.has(name);
              const meta = evaluatorMap[name];
              return (
                <button
                  key={name}
                  onClick={() => toggleGrader(name)}
                  className={`px-3 py-1.5 rounded-lg text-base font-medium border transition-colors flex items-center gap-1.5 ${
                    enabled
                      ? "bg-white dark:bg-slate-900 text-gray-800 dark:text-slate-200 border-gray-200 dark:border-slate-700"
                      : "bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500 border-gray-200 dark:border-slate-700 line-through"
                  }`}
                >
                  {graderDisplayName(name, evaluatorMap)}
                  <span className={`text-sm font-semibold ${enabled ? passRateTextColor(summary.pass_rate) : ""}`}>
                    {(summary.pass_rate * 100).toFixed(0)}%
                  </span>
                  {meta && enabled && (
                    <span className={`text-sm font-medium px-1.5 py-0.5 rounded ${
                      meta.source === "ragas" ? "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400"
                      : meta.source === "langfuse" ? "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400"
                      : "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                    }`}>
                      {meta.source === "ragas" ? "RAGAS" : meta.source === "langfuse" ? "Langfuse" : "Custom"}
                    </span>
                  )}
                </button>
              );
            };

            return (
              <div className="mb-6 flex flex-col gap-4">
                {passFailGraders.length > 0 && (
                  <div>
                    <p className="text-sm font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
                      Pass / Fail Graders
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {passFailGraders.map(renderToggle)}
                    </div>
                  </div>
                )}
                {qualityGraders.length > 0 && (
                  <div>
                    <p className="text-sm font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
                      Additional Graders
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {qualityGraders.map(renderToggle)}
                    </div>
                  </div>
                )}
                {disabledGraders.size > 0 && (
                  <p className="text-sm text-gray-400 dark:text-slate-500">
                    {disabledGraders.size} grader{disabledGraders.size > 1 ? "s" : ""} disabled — stats recomputed
                  </p>
                )}
              </div>
            );
          })()}

          {/* Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard label="Total" value={computedStats.total} />
            <StatCard label="Passed" value={computedStats.passed} accent={computedStats.passed > 0 ? "green" : undefined} />
            <StatCard label="Failed" value={computedStats.failed} accent={computedStats.failed > 0 ? "red" : undefined} />
            <StatCard
              label="Pass Rate"
              value={`${(computedStats.passRate * 100).toFixed(1)}%`}
              sub={disabledGraders.size > 0 ? "recomputed" : undefined}
              accent={computedStats.passRate === 1 ? "green" : computedStats.passRate === 0 && computedStats.total > 0 ? "red" : "amber"}
            />
            {typeof run.metadata?.filter_mode === "string" && run.metadata.filter_mode !== "as_configured" && (
              <StatCard
                label="Filter Mode"
                value={run.metadata.filter_mode === "no_filters" ? "No Filters" : String(run.metadata.filter_mode)}
                accent="amber"
              />
            )}
            {typeof run.metadata?.avg_turns_to_pass === "number" && (
              <StatCard
                label="Avg Turns to Pass"
                value={`${(run.metadata.avg_turns_to_pass as number).toFixed(1)}`}
                sub={`${run.metadata.multi_turn_test_count ?? 0} multi-turn tests`}
                accent="amber"
              />
            )}
          </div>

          {/* Failure pattern filter (only when the run has been classified) */}
          {failurePatternSummary && Object.keys(failurePatternSummary).length > 0 && (
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <FilterComboBox
                label="Failure pattern"
                placeholder="Filter by failure pattern..."
                options={Object.entries(failurePatternSummary)
                  .sort(([, a], [, b]) => b - a)
                  .map(([name, count]) => `${name} (${count})`)
                  .concat()}
                selected={patternFilter.map((name) => {
                  const count = failurePatternSummary[name];
                  return count != null ? `${name} (${count})` : name;
                })}
                onSelectedChange={(values) => {
                  // Strip the trailing " (count)" suffix that we add for display.
                  setPatternFilter(values.map((v) => v.replace(/\s*\(\d+\)\s*$/, "")));
                }}
                mode={patternMode}
                onModeChange={setPatternMode}
                allowFreeText={false}
              />
              {patternFilter.length > 0 && (
                <button
                  onClick={() => setPatternFilter([])}
                  className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 underline mb-1"
                >
                  Clear
                </button>
              )}
            </div>
          )}

          {/* Filter */}
          <div className="flex items-center gap-2 mb-4">
            {(["all", "passed", "failed"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-4 py-2 rounded-lg text-base font-medium transition-colors ${
                  filter === f
                    ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
                    : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
                {f === "all" && ` (${computedStats.total})`}
                {f === "passed" && ` (${computedStats.passed})`}
                {f === "failed" && ` (${computedStats.failed})`}
              </button>
            ))}
          </div>

          {/* Results Table */}
          <EvalResultsTable
            filteredResults={filteredResults}
            disabledGraders={disabledGraders}
            evaluatorMap={evaluatorMap}
            onSelectResult={handleSelectResult}
            loadingResultId={loadingResultId}
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
                    <p className="text-sm text-gray-500 dark:text-slate-400 mb-1" title={name}>{formatScoreLabel(name)}</p>
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
    </div>
  );
}
