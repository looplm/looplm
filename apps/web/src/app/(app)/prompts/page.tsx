"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import {
  getIntegrations,
  getPrompts,
  syncPrompts,
  importPrompts,
  reviewPrompt,
  getPromptReviews,
  getPromptVersions,
  getProjectGithubInstallation,
  extractGithubPrompts,
  getGithubExtractionStatus,
  cancelGithubExtraction,
  recheckPrompt,
  type Integration,
  type PromptItem,
  type PromptReviewResult,
  type PromptExtractionStatus,
} from "@/lib/api";
import { PromptReviewTab, sortBySeverity } from "./prompt-review-tab";
import { usePermissions } from "@/components/permissions-context";

const PROMPTS_READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

const SOURCE_BADGES: Record<string, string> = {
  langfuse: "bg-purple-500/20 text-purple-700 dark:text-purple-300 border-purple-500/40",
  langsmith: "bg-blue-500/20 text-blue-700 dark:text-blue-300 border-blue-500/40",
  json_import: "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  json_file: "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  github: "bg-gray-800 text-white border-gray-800 dark:bg-slate-200 dark:text-slate-900 dark:border-slate-200",
};

const SOURCE_LABELS: Record<string, string> = {
  langfuse: "Langfuse",
  langsmith: "LangSmith",
  json_import: "JSON",
  json_file: "JSON",
  github: "GitHub",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "text-red-400",
  medium: "text-amber-400",
  low: "text-green-400",
};

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function simpleDiff(a: string, b: string): { left: string[]; right: string[] } {
  const linesA = a.split("\n");
  const linesB = b.split("\n");
  return { left: linesA, right: linesB };
}

export default function PromptsPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("prompts");
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<PromptItem | null>(null);
  const [review, setReview] = useState<PromptReviewResult | null>(null);
  const [reviewHistory, setReviewHistory] = useState<PromptReviewResult[]>([]);
  const [versions, setVersions] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"review" | "history" | "versions">("review");
  const [compareA, setCompareA] = useState<number | null>(null);
  const [compareB, setCompareB] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [importing, setImporting] = useState(false);
  const [githubRepo, setGithubRepo] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<PromptExtractionStatus | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [rechecking, setRechecking] = useState(false);
  const [recheckMsg, setRecheckMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastCountRef = useRef(0);

  const extracting = extraction?.status === "pending" || extraction?.status === "running";
  const githubCount = prompts.filter((p) => p.source === "github").length;
  const lastRunIncomplete =
    extraction?.status === "failed" || extraction?.status === "cancelled";

  // Tick a 1s clock while extracting so the elapsed timers count up live.
  useEffect(() => {
    if (!extracting) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [extracting]);

  const loadPrompts = () => {
    setLoading(true);
    getPrompts()
      .then((r) => setPrompts(r.data ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  // Reload the list without flipping the loading state — used to surface
  // prompts as they're extracted one by one.
  const refreshPromptsQuietly = () => {
    getPrompts().then((r) => setPrompts(r.data ?? [])).catch(() => {});
  };

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await getGithubExtractionStatus();
        setExtraction(status);
        // Surface prompts as they land, one by one.
        if (status.extracted_count > lastCountRef.current) {
          lastCountRef.current = status.extracted_count;
          refreshPromptsQuietly();
        }
        if (["completed", "failed", "cancelled"].includes(status.status)) {
          stopPolling();
          lastCountRef.current = 0;
          if (status.status === "completed") loadPrompts();
          if (status.status === "failed" && status.error) setError(status.error);
        }
      } catch {
        stopPolling();
      }
    }, 2000);
  };

  useEffect(() => {
    getIntegrations().then((r) => setIntegrations(r.data)).catch((e) => setError(e.message));
    loadPrompts();
    getProjectGithubInstallation()
      .then((inst) => setGithubRepo(inst?.repo_full_name ?? null))
      .catch(() => setGithubRepo(null));
    // Resume polling if an extraction is already in flight (e.g. after a reload).
    getGithubExtractionStatus()
      .then((status) => {
        setExtraction(status);
        if (status.status === "pending" || status.status === "running") startPolling();
      })
      .catch(() => {});
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleExtractGithub = async () => {
    setError(null);
    lastCountRef.current = 0;
    try {
      await extractGithubPrompts();
      setExtraction({
        id: "",
        status: "pending",
        error: null,
        summary: null,
        files_analyzed: [],
        extracted_count: 0,
        total_cost_usd: null,
        num_turns: null,
        progress_message: "Starting…",
        progress_log: [],
        started_at: null,
        completed_at: null,
      });
      startPolling();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleCancelExtraction = async () => {
    try {
      await cancelGithubExtraction();
    } catch {
      /* ignore */
    } finally {
      stopPolling();
      setExtraction((prev) => (prev ? { ...prev, status: "cancelled", progress_message: null } : prev));
    }
  };

  const selectPrompt = async (p: PromptItem) => {
    setSelectedPrompt(p);
    setReview(null);
    setRecheckMsg(null);
    setActiveTab("review");
    setCompareA(null);
    setCompareB(null);
    try {
      const [reviewsRes, versionsRes] = await Promise.all([
        getPromptReviews(p.id),
        getPromptVersions(p.id),
      ]);
      setReviewHistory(reviewsRes.data ?? []);
      setVersions(versionsRes.data ?? []);
    } catch {
      setReviewHistory([]);
      setVersions([]);
    }
  };

  const handleSync = async (integrationId: string) => {
    setSyncing(true);
    setError(null);
    try {
      await syncPrompts(integrationId);
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleImportJson = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const prompts = Array.isArray(parsed) ? parsed : parsed.prompts;
      if (!Array.isArray(prompts)) throw new Error("Expected { \"prompts\": [...] } or a flat array");
      await importPrompts(prompts, file.name);
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleReview = async (promptId: string) => {
    setReviewing(true);
    setError(null);
    try {
      const result = await reviewPrompt(promptId);
      setReview(result);
      setReviewHistory((prev) => [result, ...prev]);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReviewing(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApply = async () => {
    // Stub: would call Langfuse API to update the prompt
    alert("Apply to Langfuse: This would update the prompt in your connected platform. (Stubbed)");
  };

  const handleRecheck = async (promptId: string) => {
    setRechecking(true);
    setRecheckMsg(null);
    setError(null);
    try {
      const res = await recheckPrompt(promptId);
      if (res.changed) {
        setSelectedPrompt(res.prompt);
        setRecheckMsg("Updated — the prompt changed in the codebase.");
        refreshPromptsQuietly();
      } else {
        setRecheckMsg("No changes since last extraction.");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRechecking(false);
    }
  };

  const versionA = useMemo(() => versions.find((v) => v.version === compareA), [versions, compareA]);
  const versionB = useMemo(() => versions.find((v) => v.version === compareB), [versions, compareB]);
  const diff = useMemo(() => {
    if (!versionA || !versionB) return null;
    return simpleDiff(versionA.template, versionB.template);
  }, [versionA, versionB]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Prompts</h1>
        <div className="flex gap-2">
          {integrations.filter((i) => i.type !== "json_file" && i.type !== "github").map((i) => (
            <button
              key={i.id}
              onClick={() => handleSync(i.id)}
              disabled={syncing || !canEdit}
              title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
              className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {syncing ? "Syncing..." : `Sync ${i.name}`}
            </button>
          ))}
          {githubRepo && (
            extracting ? (
              <button
                onClick={handleCancelExtraction}
                className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg"
              >
                Cancel extraction
              </button>
            ) : (
              <button
                onClick={handleExtractGithub}
                disabled={!canEdit}
                title={!canEdit ? PROMPTS_READ_ONLY_TITLE : `Extract prompts from ${githubRepo}`}
                className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {lastRunIncomplete && githubCount > 0
                  ? `Resume (${githubCount} saved)`
                  : "Extract from GitHub"}
              </button>
            )
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            onChange={handleImportJson}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importing || !canEdit}
            title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg"
          >
            {importing ? "Importing..." : "Import JSON"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {extracting && (() => {
        const log = extraction?.progress_log ?? [];
        const startTs = extraction?.started_at
          ? Date.parse(extraction.started_at)
          : (log[0] ? Date.parse(log[0].t) : now);
        const visible = log.slice(-6);
        const base = log.length - visible.length;
        return (
          <div className="mb-4 p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-lg text-sm">
            <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-300 font-medium">
              <span className="inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
              <span className="flex-1">
                Extracting prompts from {githubRepo}
                {extraction?.progress_message ? ` — ${extraction.progress_message}` : "…"}
              </span>
              <span className="tabular-nums text-xs text-indigo-500/80 dark:text-indigo-400/80">
                {fmtDuration(now - startTs)}
              </span>
            </div>
            {visible.length > 0 && (
              <ul className="mt-2 ml-5 space-y-0.5 font-mono text-[11px] text-gray-500 dark:text-slate-400">
                {visible.map((entry, i) => {
                  const fi = base + i;
                  const isLast = fi === log.length - 1;
                  const endTs = isLast ? now : Date.parse(log[fi + 1].t);
                  return (
                    <li
                      key={`${entry.t}-${fi}`}
                      className={`flex items-baseline gap-2 ${isLast ? "text-indigo-600 dark:text-indigo-300" : ""}`}
                    >
                      <span className="flex-1 truncate">
                        <span className="text-gray-400 dark:text-slate-600">›</span> {entry.msg}
                      </span>
                      <span className="tabular-nums text-gray-400 dark:text-slate-600 shrink-0">
                        {fmtDuration(endTs - Date.parse(entry.t))}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })()}
      {extraction?.status === "completed" && (
        <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-600 dark:text-emerald-300 text-sm">
          Extracted {extraction.extracted_count} prompt{extraction.extracted_count !== 1 ? "s" : ""} from {githubRepo}
          {extraction.started_at && extraction.completed_at
            ? ` in ${fmtDuration(Date.parse(extraction.completed_at) - Date.parse(extraction.started_at))}`
            : ""}
          .
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Prompt list */}
        <div className="lg:col-span-1 space-y-2 max-h-[calc(100vh-10rem)] overflow-y-auto pr-1">
          {loading ? (
            <div className="text-gray-500 dark:text-slate-400 text-sm p-4">Loading...</div>
          ) : prompts.length === 0 ? (
            <div className="text-gray-500 dark:text-slate-400 text-sm p-4">No prompts imported yet. Click Sync to import.</div>
          ) : (
            [...prompts].sort((a, b) => new Date(b.updated_at ?? b.created_at).getTime() - new Date(a.updated_at ?? a.created_at).getTime()).map((p) => (
              <button
                key={p.id}
                onClick={() => selectPrompt(p)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selectedPrompt?.id === p.id
                    ? "bg-indigo-50 dark:bg-indigo-600/20 border-indigo-500/30"
                    : "bg-white dark:bg-slate-900 border-gray-100 dark:border-slate-800 hover:border-gray-200 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate flex-1">{p.name}</span>
                  <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded border shrink-0 ${SOURCE_BADGES[p.source] ?? "bg-slate-500/20 text-slate-600 dark:text-slate-300 border-slate-500/40"}`}>
                    {SOURCE_LABELS[p.source] ?? p.source}
                  </span>
                </div>
                <div className="text-[10px] text-gray-400 dark:text-slate-500" title={p.updated_at ? new Date(p.updated_at).toLocaleString() : undefined}>
                  v{p.version} · {p.variables?.length ?? 0} vars{p.updated_at ? ` · updated ${timeAgo(p.updated_at)}` : ""}
                </div>
              </button>
            ))
          )}
        </div>

        {/* Detail panel */}
        <div className="lg:col-span-2">
          {selectedPrompt ? (
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-semibold">{selectedPrompt.name}</h2>
                  <span className="text-xs text-gray-400 dark:text-slate-500">
                    Version {selectedPrompt.version}
                    {selectedPrompt.updated_at ? ` · updated ${timeAgo(selectedPrompt.updated_at)}` : ""}
                  </span>
                </div>
                <div className="flex gap-2">
                  {selectedPrompt.source === "github" && githubRepo && (
                    <button
                      onClick={() => handleRecheck(selectedPrompt.id)}
                      disabled={rechecking || !canEdit}
                      title={!canEdit ? PROMPTS_READ_ONLY_TITLE : `Re-extract from ${githubRepo}`}
                      className="px-4 py-2 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm rounded-lg"
                    >
                      {rechecking ? "Checking…" : "Check for updates"}
                    </button>
                  )}
                  <button
                    onClick={() => handleReview(selectedPrompt.id)}
                    disabled={reviewing || !canEdit}
                    title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg"
                  >
                    {reviewing ? "Reviewing..." : "Review"}
                  </button>
                </div>
              </div>

              {recheckMsg && (
                <div className="mb-4 p-2 text-xs rounded-lg bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700">
                  {recheckMsg}
                </div>
              )}

              {(selectedPrompt.variables?.length ?? 0) > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Input Variables</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {(selectedPrompt.variables ?? []).map((v, i) => (
                      <span key={`${v}-${i}`} className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-slate-800 rounded text-gray-600 dark:text-slate-300 font-mono">
                        {`{${v}}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Template</h3>
                <pre className="p-4 bg-gray-50 dark:bg-slate-950 rounded-lg text-xs text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
                  {selectedPrompt.template}
                </pre>
              </div>

              {/* Tabs */}
              <div className="flex gap-1 mb-4 border-b border-gray-100 dark:border-slate-800">
                {(["review", "history", "versions"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                      activeTab === tab
                        ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                        : "border-transparent text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300"
                    }`}
                  >
                    {tab === "review" ? "Current Review" : tab === "history" ? `History (${reviewHistory.length})` : `Versions (${versions.length})`}
                  </button>
                ))}
              </div>

              {/* Current Review Tab */}
              {activeTab === "review" && (
                <PromptReviewTab
                  review={review}
                  reviewing={reviewing}
                  copied={copied}
                  onCopy={handleCopy}
                  onApply={handleApply}
                />
              )}

              {/* History Tab */}
              {activeTab === "history" && (
                <div className="space-y-3">
                  {reviewHistory.length === 0 ? (
                    <div className="text-sm text-gray-400 dark:text-slate-500 p-4 text-center">No reviews yet.</div>
                  ) : (
                    reviewHistory.map((r) => (
                      <div key={r.id} className="p-4 bg-gray-100/50 dark:bg-slate-800/50 rounded-lg border border-gray-100 dark:border-slate-800">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs text-gray-500 dark:text-slate-400">
                            {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString() : "Unknown"}
                          </span>
                          <span className="text-[10px] text-gray-300 dark:text-slate-600">{r.model}</span>
                        </div>
                        <div className="text-xs text-gray-600 dark:text-slate-300 mb-2">
                          {r.anti_patterns?.length ?? 0} anti-pattern{(r.anti_patterns?.length ?? 0) !== 1 ? "s" : ""} · {r.suggestions?.length ?? 0} suggestion{(r.suggestions?.length ?? 0) !== 1 ? "s" : ""}
                        </div>
                        {sortBySeverity(r.anti_patterns ?? []).map((ap, i) => (
                          <div key={i} className="text-[10px] text-gray-500 dark:text-slate-400 ml-2">
                            <span className={SEVERITY_COLORS[ap.severity] ?? ""}>{ap.severity}</span> {ap.pattern}: {ap.description}
                          </div>
                        ))}
                        {r.rewritten_prompt && (
                          <details className="mt-2">
                            <summary className="text-[10px] text-indigo-600 dark:text-indigo-400 cursor-pointer">Show rewritten prompt</summary>
                            <pre className="mt-1 p-2 bg-gray-50 dark:bg-slate-950 rounded text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap max-h-32 overflow-auto">
                              {r.rewritten_prompt}
                            </pre>
                          </details>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Versions Tab */}
              {activeTab === "versions" && (
                <div className="space-y-4">
                  {versions.length <= 1 ? (
                    <div className="text-sm text-gray-400 dark:text-slate-500 p-4 text-center">Only one version available.</div>
                  ) : (
                    <>
                      <div className="flex gap-4 items-center">
                        <div>
                          <label className="text-[10px] text-gray-400 dark:text-slate-500 block mb-1">Version A</label>
                          <select
                            value={compareA ?? ""}
                            onChange={(e) => setCompareA(e.target.value ? Number(e.target.value) : null)}
                            className="bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 text-xs rounded px-2 py-1"
                          >
                            <option value="">Select...</option>
                            {versions.map((v) => (
                              <option key={v.version} value={v.version}>v{v.version}</option>
                            ))}
                          </select>
                        </div>
                        <span className="text-gray-300 dark:text-slate-600 mt-4">↔</span>
                        <div>
                          <label className="text-[10px] text-gray-400 dark:text-slate-500 block mb-1">Version B</label>
                          <select
                            value={compareB ?? ""}
                            onChange={(e) => setCompareB(e.target.value ? Number(e.target.value) : null)}
                            className="bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 text-xs rounded px-2 py-1"
                          >
                            <option value="">Select...</option>
                            {versions.map((v) => (
                              <option key={v.version} value={v.version}>v{v.version}</option>
                            ))}
                          </select>
                        </div>
                      </div>

                      {diff && versionA && versionB && (
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-1">v{versionA.version}</div>
                            <pre className="p-3 bg-gray-50 dark:bg-slate-950 rounded-lg text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
                              {diff.left.map((line, i) => {
                                const otherLine = diff.right[i];
                                const changed = line !== otherLine;
                                return (
                                  <span key={i} className={changed ? "bg-red-900/30" : ""}>
                                    {line}{"\n"}
                                  </span>
                                );
                              })}
                            </pre>
                          </div>
                          <div>
                            <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-1">v{versionB.version}</div>
                            <pre className="p-3 bg-gray-50 dark:bg-slate-950 rounded-lg text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
                              {diff.right.map((line, i) => {
                                const otherLine = diff.left[i];
                                const changed = line !== otherLine;
                                return (
                                  <span key={i} className={changed ? "bg-green-900/30" : ""}>
                                    {line}{"\n"}
                                  </span>
                                );
                              })}
                            </pre>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-12 text-center text-gray-500 dark:text-slate-400">
              Select a prompt to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
