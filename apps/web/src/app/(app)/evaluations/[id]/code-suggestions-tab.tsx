"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  triggerCodeAgentAnalysis,
  cancelCodeAgentAnalysis,
  getCodeAgentAnalysis,
  updateCodeSuggestionStatus,
  type OpenCodeAnalysisResponse,
  type CodeSuggestionItem,
} from "@/lib/api";
import { toast } from "sonner";

const TYPE_LABELS: Record<string, string> = {
  prompt_change: "Prompt",
  code_fix: "Code Fix",
  config_change: "Config",
  architecture_change: "Architecture",
};

const TYPE_COLORS: Record<string, string> = {
  prompt_change: "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400",
  code_fix: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
  config_change: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  architecture_change: "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400",
};

const IMPACT_COLORS: Record<string, string> = {
  high: "text-red-600 dark:text-red-400",
  medium: "text-amber-600 dark:text-amber-400",
  low: "text-gray-500 dark:text-slate-400",
};

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <div className="w-16 h-1.5 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
        <div
          className="h-full rounded-full bg-indigo-500"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="text-gray-500 dark:text-slate-400 text-xs">
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}

function SuggestionCard({
  suggestion,
  onStatusChange,
}: {
  suggestion: CodeSuggestionItem;
  onStatusChange: (id: string, status: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isDismissed = suggestion.status === "dismissed";
  const isApplied = suggestion.status === "applied";

  return (
    <div
      className={`rounded-xl border p-4 transition-colors ${
        isDismissed
          ? "opacity-50 border-gray-200 dark:border-slate-800"
          : isApplied
            ? "border-green-300 dark:border-green-800 bg-green-50/50 dark:bg-green-900/10"
            : "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`text-xs font-medium px-2 py-0.5 rounded ${TYPE_COLORS[suggestion.type] || "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400"}`}>
              {TYPE_LABELS[suggestion.type] || suggestion.type}
            </span>
            {suggestion.impact && (
              <span className={`text-xs font-medium ${IMPACT_COLORS[suggestion.impact] || ""}`}>
                {suggestion.impact} impact
              </span>
            )}
            {suggestion.confidence != null && (
              <ConfidenceBar value={suggestion.confidence} />
            )}
            {isApplied && (
              <span className="text-xs font-medium text-green-600 dark:text-green-400">Applied</span>
            )}
            {isDismissed && (
              <span className="text-xs font-medium text-gray-400 dark:text-slate-500">Dismissed</span>
            )}
          </div>
          <h4 className="text-base font-semibold text-gray-900 dark:text-white">
            {suggestion.title}
          </h4>
          {suggestion.file_path && (
            <p className="text-sm text-gray-500 dark:text-slate-400 font-mono mt-0.5">
              {suggestion.file_path}
              {suggestion.line_start && `:${suggestion.line_start}`}
              {suggestion.line_end && suggestion.line_end !== suggestion.line_start && `-${suggestion.line_end}`}
            </p>
          )}
          {suggestion.description && (
            <p className="text-sm text-gray-600 dark:text-slate-300 mt-2">
              {suggestion.description}
            </p>
          )}
        </div>

        {suggestion.status === "pending" && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => onStatusChange(suggestion.id, "applied")}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/40 transition-colors border border-green-200 dark:border-green-800"
            >
              Apply
            </button>
            <button
              onClick={() => onStatusChange(suggestion.id, "dismissed")}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors border border-gray-200 dark:border-slate-700"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Expandable sections */}
      {(suggestion.diff || suggestion.reasoning || (suggestion.related_test_ids?.length > 0)) && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-3 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {expanded ? "Show less" : "Show details"}
        </button>
      )}

      {expanded && (
        <div className="mt-3 space-y-3">
          {suggestion.diff && (
            <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
              <div className="px-3 py-1.5 bg-gray-50 dark:bg-slate-800 text-xs font-medium text-gray-500 dark:text-slate-400">
                Suggested Change
              </div>
              <div className="p-3 space-y-2">
                {suggestion.diff.before && (
                  <div>
                    <p className="text-xs text-red-500 dark:text-red-400 font-medium mb-1">Before:</p>
                    <pre className="text-xs font-mono bg-red-50 dark:bg-red-900/10 text-red-800 dark:text-red-300 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                      {suggestion.diff.before}
                    </pre>
                  </div>
                )}
                {suggestion.diff.after && (
                  <div>
                    <p className="text-xs text-green-500 dark:text-green-400 font-medium mb-1">After:</p>
                    <pre className="text-xs font-mono bg-green-50 dark:bg-green-900/10 text-green-800 dark:text-green-300 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                      {suggestion.diff.after}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}

          {suggestion.reasoning && (
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Reasoning</p>
              <p className="text-sm text-gray-600 dark:text-slate-300">{suggestion.reasoning}</p>
            </div>
          )}

          {suggestion.related_test_ids?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Related Tests</p>
              <div className="flex flex-wrap gap-1">
                {suggestion.related_test_ids.map((tid) => (
                  <span
                    key={tid}
                    className="text-xs font-mono px-2 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400"
                  >
                    {tid}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function useElapsedTime(startedAt: string | null, isRunning: boolean) {
  const [elapsed, setElapsed] = useState(0);
  // Use a ref to remember when we first saw isRunning=true,
  // as a fallback when started_at hasn't arrived from the backend yet.
  const fallbackStart = useRef<number | null>(null);

  useEffect(() => {
    if (!isRunning) {
      fallbackStart.current = null;
      setElapsed(0);
      return;
    }
    // Compute start time: prefer backend started_at, fall back to client-side timestamp
    const start = startedAt
      ? new Date(startedAt).getTime()
      : (fallbackStart.current ??= Date.now());

    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [startedAt, isRunning]);

  if (elapsed < 60) return `${elapsed}s`;
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}m ${secs}s`;
}

export function CodeSuggestionsTab({ evalRunId }: { evalRunId: string }) {
  const [analysis, setAnalysis] = useState<OpenCodeAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [polling, setPolling] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const isInProgress = analysis != null && ["pending", "running"].includes(analysis.status);
  const elapsedTime = useElapsedTime(analysis?.started_at ?? null, isInProgress);

  const fetchAnalysis = useCallback(async () => {
    try {
      const data = await getCodeAgentAnalysis(evalRunId);
      setAnalysis(data);
      return data;
    } catch {
      setAnalysis(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [evalRunId]);

  useEffect(() => {
    fetchAnalysis();
  }, [fetchAnalysis]);

  // Poll while analysis is pending/running
  useEffect(() => {
    if (!analysis || !["pending", "running"].includes(analysis.status)) {
      setPolling(false);
      return;
    }
    setPolling(true);
    const interval = setInterval(async () => {
      const updated = await fetchAnalysis();
      if (updated && !["pending", "running"].includes(updated.status)) {
        clearInterval(interval);
        setPolling(false);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [analysis?.status, fetchAnalysis]);

  async function handleTrigger(mode: "quick" | "detailed" = "detailed") {
    setTriggering(true);
    try {
      await triggerCodeAgentAnalysis(evalRunId, "", undefined, mode);
      toast.success(`${mode === "quick" ? "Quick" : "Deep"} analysis started`);
      await fetchAnalysis();
    } catch (err: any) {
      toast.error("Failed to start analysis", { description: err.message });
    } finally {
      setTriggering(false);
    }
  }

  async function handleCancel() {
    setCancelling(true);
    try {
      await cancelCodeAgentAnalysis(evalRunId);
      toast.success("Analysis cancelled");
      await fetchAnalysis();
    } catch (err: any) {
      toast.error("Failed to cancel analysis", { description: err.message });
    } finally {
      setCancelling(false);
    }
  }

  async function handleStatusChange(suggestionId: string, status: string) {
    try {
      await updateCodeSuggestionStatus(suggestionId, status);
      // Refresh
      await fetchAnalysis();
      toast.success(`Suggestion ${status}`);
    } catch (err: any) {
      toast.error("Failed to update suggestion", { description: err.message });
    }
  }

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400 py-8">Loading...</p>;
  }

  // No analysis yet — show trigger buttons
  if (!analysis) {
    return (
      <div className="py-12 text-center">
        <p className="text-gray-500 dark:text-slate-400 mb-4">
          Analyze evaluation failures and get actionable code suggestions powered by Claude.
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => handleTrigger("quick")}
            disabled={triggering}
            className="px-5 py-3 rounded-xl text-sm font-semibold border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {triggering ? "Starting..." : "Quick Analysis"}
          </button>
          <button
            onClick={() => handleTrigger("detailed")}
            disabled={triggering}
            className="px-5 py-3 rounded-xl text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {triggering ? "Starting..." : "Deep Analysis"}
          </button>
        </div>
        <div className="mt-3 space-y-1">
          <p className="text-xs text-gray-400 dark:text-slate-500">
            <strong>Quick:</strong> Fast summary with top suggestions. <strong>Deep:</strong> Thorough codebase exploration with detailed diffs.
          </p>
          <p className="text-xs text-gray-400 dark:text-slate-500">
            Works with or without a connected repository. Connect a repo in Settings for file-level suggestions.
          </p>
        </div>
      </div>
    );
  }

  // Analysis in progress
  if (["pending", "running"].includes(analysis.status)) {
    const log = analysis.progress_log || [];
    return (
      <div className="py-10">
        <div className="max-w-lg mx-auto rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6">
          {/* Spinner + status */}
          <div className="flex items-center gap-3 mb-4">
            <svg className="animate-spin h-5 w-5 text-indigo-500 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span className="text-sm text-gray-700 dark:text-slate-300">
              {analysis.progress_message || (analysis.status === "pending" ? "Starting analysis..." : "Agent is analyzing your failures...")}
            </span>
          </div>

          {/* Stats row */}
          <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-slate-400 mb-4">
            <span title="Elapsed time">{elapsedTime}</span>
            {analysis.num_turns != null && analysis.num_turns > 0 && (
              <span>{analysis.num_turns} turn{analysis.num_turns !== 1 ? "s" : ""}</span>
            )}
            {analysis.total_cost_usd != null && (
              <span>${analysis.total_cost_usd.toFixed(4)}</span>
            )}
            {analysis.analysis_mode && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 font-medium">
                {analysis.analysis_mode === "quick" ? "Quick" : "Deep"}
              </span>
            )}
          </div>

          {/* Activity log */}
          {log.length > 0 && (
            <div className="mb-4 max-h-40 overflow-y-auto rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-100 dark:border-slate-700/50">
              <div className="p-2 space-y-0.5">
                {log.map((entry, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs font-mono">
                    <span className="text-gray-400 dark:text-slate-500 shrink-0 tabular-nums">
                      {new Date(entry.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                    <span className="text-gray-600 dark:text-slate-400">{entry.msg}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Cancel button */}
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="w-full px-4 py-2 rounded-lg text-sm font-medium border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
          >
            {cancelling ? "Cancelling..." : "Stop Analysis"}
          </button>
        </div>
      </div>
    );
  }

  // Analysis cancelled
  if (analysis.status === "cancelled") {
    return (
      <div className="py-8">
        <div className="rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-900/10 p-4">
          <p className="text-amber-700 dark:text-amber-400 font-medium">Analysis cancelled</p>
          {analysis.total_cost_usd != null && (
            <p className="text-sm text-amber-600 dark:text-amber-300 mt-1">
              Cost incurred: ${analysis.total_cost_usd.toFixed(4)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={() => handleTrigger("quick")}
            disabled={triggering || polling}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 transition-colors disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Quick Analysis"}
          </button>
          <button
            onClick={() => handleTrigger("detailed")}
            disabled={triggering || polling}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Deep Analysis"}
          </button>
        </div>
      </div>
    );
  }

  // Analysis failed
  if (analysis.status === "failed") {
    return (
      <div className="py-8">
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/10 p-4">
          <p className="text-red-700 dark:text-red-400 font-medium">Analysis failed</p>
          {analysis.error && (
            <p className="text-sm text-red-600 dark:text-red-300 mt-1">{analysis.error}</p>
          )}
          {analysis.total_cost_usd != null && (
            <p className="text-sm text-red-600 dark:text-red-300 mt-1">
              Cost incurred: ${analysis.total_cost_usd.toFixed(4)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={() => handleTrigger("quick")}
            disabled={triggering}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 transition-colors disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Quick Retry"}
          </button>
          <button
            onClick={() => handleTrigger("detailed")}
            disabled={triggering}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Deep Retry"}
          </button>
        </div>
      </div>
    );
  }

  // Analysis completed
  const pendingSuggestions = analysis.suggestions.filter((s) => s.status === "pending");
  const resolvedSuggestions = analysis.suggestions.filter((s) => s.status !== "pending");

  // Group suggestions by file path
  const groupedByFile = new Map<string, CodeSuggestionItem[]>();
  for (const s of analysis.suggestions) {
    const key = s.file_path || "__general__";
    if (!groupedByFile.has(key)) groupedByFile.set(key, []);
    groupedByFile.get(key)!.push(s);
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      {analysis.failure_summary && (
        <div className="rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Failure Summary</h3>
          <p className="text-sm text-gray-600 dark:text-slate-300 whitespace-pre-wrap">{analysis.failure_summary}</p>
        </div>
      )}

      {/* Stats bar */}
      <div className="flex items-center justify-between text-sm text-gray-500 dark:text-slate-400">
        <div className="flex items-center gap-4">
          <span>{analysis.suggestion_count} suggestion{analysis.suggestion_count !== 1 ? "s" : ""}</span>
          {analysis.files_analyzed.length > 0 && (
            <span>{analysis.files_analyzed.length} file{analysis.files_analyzed.length !== 1 ? "s" : ""} analyzed</span>
          )}
          {analysis.num_turns != null && <span>{analysis.num_turns} agent turns</span>}
          {analysis.total_cost_usd != null && <span>${analysis.total_cost_usd.toFixed(4)}</span>}
          {analysis.analysis_mode && (
            <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-xs font-medium">
              {analysis.analysis_mode === "quick" ? "Quick" : "Deep"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleTrigger("quick")}
            disabled={triggering || polling}
            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Quick"}
          </button>
          <span className="text-gray-300 dark:text-slate-600">|</span>
          <button
            onClick={() => handleTrigger("detailed")}
            disabled={triggering || polling}
            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-50"
          >
            {triggering ? "Starting..." : "Deep re-analyze"}
          </button>
        </div>
      </div>

      {/* Suggestions */}
      {analysis.suggestions.length === 0 ? (
        <p className="text-gray-500 dark:text-slate-400 text-center py-8">
          No suggestions generated. The agent found no actionable improvements for the current failures.
        </p>
      ) : (
        <div className="space-y-6">
          {Array.from(groupedByFile.entries()).map(([filePath, suggestions]) => (
            <div key={filePath}>
              {filePath !== "__general__" && (
                <h3 className="text-sm font-mono font-medium text-gray-600 dark:text-slate-400 mb-2">
                  {filePath}
                </h3>
              )}
              {filePath === "__general__" && suggestions.length > 0 && (
                <h3 className="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">
                  General Suggestions
                </h3>
              )}
              <div className="space-y-3">
                {suggestions.map((suggestion) => (
                  <SuggestionCard
                    key={suggestion.id}
                    suggestion={suggestion}
                    onStatusChange={handleStatusChange}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
