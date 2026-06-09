"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getIntegrations,
  triggerAdvisorAnalysis,
  getAdvisorSuggestions,
  getAdvisorRun,
  cancelAdvisorRun,
  getGithubStatus,
  getProjectGithubInstallation,
  type Integration,
  type Suggestion,
  type AdvisorResponse,
  type AdvisorRunResponse,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";

const CATEGORY_LABELS: Record<string, string> = {
  time_to_value: "⚡ Time to Value",
  output_quality: "✨ Output Quality",
  architecture: "🏗️ Architecture",
};

const IMPACT_COLORS: Record<string, string> = {
  high: "bg-red-500/20 text-red-300 border-red-500/30",
  medium: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  low: "bg-green-500/20 text-green-300 border-green-500/30",
};

function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-4">
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-medium text-sm">{suggestion.title}</h3>
        <span className={`text-[10px] px-2 py-0.5 rounded border shrink-0 ml-2 ${IMPACT_COLORS[suggestion.impact]}`}>
          {suggestion.impact}
        </span>
      </div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-3">{suggestion.description}</p>
      <div className="flex items-center gap-3 mb-2">
        <div className="flex items-center gap-1.5 flex-1">
          <span className="text-[10px] text-gray-400 dark:text-slate-500">Confidence</span>
          <div className="flex-1 h-1.5 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full"
              style={{ width: `${suggestion.confidence * 100}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-500 dark:text-slate-400">{(suggestion.confidence * 100).toFixed(0)}%</span>
        </div>
      </div>
      {suggestion.reasoning && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300"
        >
          {expanded ? "Hide reasoning ▴" : "Show reasoning ▾"}
        </button>
      )}
      {expanded && suggestion.reasoning && (
        <div className="mt-2 p-3 bg-gray-100/50 dark:bg-slate-800/50 rounded text-xs text-gray-600 dark:text-slate-300 leading-relaxed">
          {suggestion.reasoning}
        </div>
      )}
    </div>
  );
}

const IN_PROGRESS = ["pending", "running"];

export default function AdvisorPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("advisor");
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState("");
  const [advisorData, setAdvisorData] = useState<AdvisorResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Repo-aware (agentic) path
  const [includeRepo, setIncludeRepo] = useState(false);
  const [runData, setRunData] = useState<AdvisorRunResponse | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [githubEnabled, setGithubEnabled] = useState(false);
  const [repoConnected, setRepoConnected] = useState(false);

  const runInProgress = runData != null && IN_PROGRESS.includes(runData.status);

  useEffect(() => {
    getIntegrations().then((r) => {
      const filtered = r.data.filter((i) => i.type !== "json_file");
      setIntegrations(filtered);
      if (filtered.length > 0) setSelectedIntegration(filtered[0].id);
    }).catch((e) => setError(e.message));

    // Decide whether the "Include code repository" toggle can be enabled.
    getGithubStatus().then((s) => setGithubEnabled(s.enabled)).catch(() => setGithubEnabled(false));
    getProjectGithubInstallation()
      .then((inst) => setRepoConnected(!!inst?.repo_full_name))
      .catch(() => setRepoConnected(false));
  }, []);

  // Load latest completed suggestions + resume any in-flight repo run.
  useEffect(() => {
    if (!selectedIntegration) return;
    setLoading(true);
    setRunData(null);
    getAdvisorSuggestions(selectedIntegration)
      .then(setAdvisorData)
      .catch(() => setAdvisorData(null))
      .finally(() => setLoading(false));
    getAdvisorRun(selectedIntegration)
      .then((run) => {
        if (IN_PROGRESS.includes(run.status)) setRunData(run);
      })
      .catch(() => {});
  }, [selectedIntegration]);

  const fetchRun = useCallback(async () => {
    if (!selectedIntegration) return null;
    try {
      const run = await getAdvisorRun(selectedIntegration);
      setRunData(run);
      return run;
    } catch {
      return null;
    }
  }, [selectedIntegration]);

  // Poll while a repo run is pending/running.
  useEffect(() => {
    if (!runData || !IN_PROGRESS.includes(runData.status)) return;
    const interval = setInterval(async () => {
      const updated = await fetchRun();
      if (updated && !IN_PROGRESS.includes(updated.status)) {
        clearInterval(interval);
        if (updated.status === "completed") {
          setAdvisorData({
            integration_id: updated.integration_id,
            suggestions: updated.suggestions,
            analyzed_at: updated.analyzed_at ?? undefined,
          });
        }
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [runData?.status, fetchRun]);

  const handleAnalyze = async () => {
    if (!selectedIntegration) return;
    setAnalyzing(true);
    setError(null);
    try {
      if (includeRepo) {
        await triggerAdvisorAnalysis(selectedIntegration, "", true);
        await fetchRun(); // kick off polling via runData
      } else {
        const result = await triggerAdvisorAnalysis(selectedIntegration);
        setAdvisorData(result as AdvisorResponse);
        setRunData(null);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCancel = async () => {
    if (!selectedIntegration) return;
    setCancelling(true);
    try {
      await cancelAdvisorRun(selectedIntegration);
      await fetchRun();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCancelling(false);
    }
  };

  const grouped = (advisorData?.suggestions ?? []).reduce<Record<string, Suggestion[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {}) ?? {};

  const repoToggleReason = !githubEnabled
    ? "GitHub App is not configured for this deployment."
    : !repoConnected
    ? "Connect a GitHub repository in Settings to enable repo-aware analysis."
    : undefined;
  const repoToggleDisabled = !githubEnabled || !repoConnected || runInProgress;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Architecture Advisor</h1>
        <div className="flex items-center gap-4">
          <label
            className={`flex items-center gap-2 text-sm ${repoToggleDisabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            title={repoToggleReason}
          >
            <input
              type="checkbox"
              checked={includeRepo}
              disabled={repoToggleDisabled}
              onChange={(e) => setIncludeRepo(e.target.checked)}
              className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
            />
            Include code repository
          </label>
          <button
            onClick={handleAnalyze}
            disabled={analyzing || runInProgress || !selectedIntegration || !canEdit}
            title={!canEdit ? "Read-only access. Ask an admin to grant write permission." : undefined}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {analyzing || runInProgress ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-4 mb-6">
        <select
          value={selectedIntegration}
          onChange={(e) => setSelectedIntegration(e.target.value)}
          className="px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
        >
          <option value="">Select integration</option>
          {integrations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
        {advisorData?.analyzed_at && !runInProgress && (
          <span className="text-xs text-gray-400 dark:text-slate-500">
            Last analyzed: {new Date(advisorData.analyzed_at).toLocaleString()}
          </span>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {/* Repo run in progress */}
      {runInProgress ? (
        <div className="max-w-lg rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6">
          <div className="flex items-center gap-3 mb-4">
            <svg className="animate-spin h-5 w-5 text-indigo-500 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span className="text-sm text-gray-700 dark:text-slate-300">
              {runData?.progress_message || (runData?.status === "pending" ? "Starting analysis..." : "Exploring your repository...")}
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-slate-400 mb-4">
            {runData?.num_turns != null && runData.num_turns > 0 && (
              <span>{runData.num_turns} turn{runData.num_turns !== 1 ? "s" : ""}</span>
            )}
            {runData?.total_cost_usd != null && <span>${runData.total_cost_usd.toFixed(4)}</span>}
          </div>
          {(runData?.progress_log?.length ?? 0) > 0 && (
            <div className="mb-4 max-h-40 overflow-y-auto rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-100 dark:border-slate-700/50">
              <div className="p-2 space-y-0.5">
                {(runData?.progress_log ?? []).map((entry, i) => {
                  const e = entry as { t: string; msg: string };
                  return (
                  <div key={i} className="flex items-start gap-2 text-xs font-mono">
                    <span className="text-gray-400 dark:text-slate-500 shrink-0 tabular-nums">
                      {new Date(e.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                    <span className="text-gray-600 dark:text-slate-400">{e.msg}</span>
                  </div>
                  );
                })}
              </div>
            </div>
          )}
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="w-full px-4 py-2 rounded-lg text-sm font-medium border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
          >
            {cancelling ? "Cancelling..." : "Stop Analysis"}
          </button>
        </div>
      ) : runData?.status === "failed" ? (
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/10 p-4">
          <p className="text-red-700 dark:text-red-400 font-medium">Repository analysis failed</p>
          {runData.error && <p className="text-sm text-red-600 dark:text-red-300 mt-1">{runData.error}</p>}
        </div>
      ) : loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">Loading...</div>
      ) : !advisorData || (advisorData.suggestions?.length ?? 0) === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No suggestions yet. Click &quot;Run Analysis&quot; to get started.
        </div>
      ) : (
        <div className="space-y-8">
          {runData?.status === "completed" && (runData.files_analyzed?.length ?? 0) > 0 && (
            <p className="text-xs text-gray-400 dark:text-slate-500">
              Analyzed {runData.files_analyzed?.length ?? 0} file{(runData.files_analyzed?.length ?? 0) !== 1 ? "s" : ""} from the connected repository.
            </p>
          )}
          {Object.entries(grouped).map(([category, suggestions]) => (
            <div key={category}>
              <h2 className="text-lg font-semibold mb-4">
                {CATEGORY_LABELS[category] ?? category}
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {suggestions.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
