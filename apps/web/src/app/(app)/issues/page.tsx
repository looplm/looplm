"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getIssues, detectIssues, type IssueListItem } from "@/lib/api";
import {
  SEVERITY_BADGE,
  STATUS_BADGE,
  SIGNAL_LABEL,
  formatRelative,
} from "./issue-format";

const STATUS_FILTERS = [
  { value: "open", label: "Open" },
  { value: "recurring", label: "Recurring" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
  { value: "", label: "All" },
] as const;

const DETECT_WINDOWS = [7, 14, 30] as const;

export default function IssuesPage() {
  const [issues, setIssues] = useState<IssueListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [detectDays, setDetectDays] = useState<number>(7);
  const [detecting, setDetecting] = useState(false);
  const [detectMsg, setDetectMsg] = useState<string | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [showErrorDetail, setShowErrorDetail] = useState(false);

  const load = useCallback(() => {
    setError(null);
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    getIssues(params)
      .then(setIssues)
      .catch((e) => setError(e.message));
  }, [statusFilter]);

  useEffect(() => {
    setIssues(null);
    load();
  }, [load]);

  async function runDetect() {
    setDetecting(true);
    setDetectMsg(null);
    setDetectError(null);
    setShowErrorDetail(false);
    try {
      const r = await detectIssues(detectDays);
      const parts = [
        `${r.signals} signal${r.signals === 1 ? "" : "s"}`,
        `${r.issues_created} new`,
        `${r.issues_updated} updated`,
      ];
      if (r.issues_diagnosed > 0) parts.push(`${r.issues_diagnosed} diagnosed`);
      setDetectMsg(`${parts.join(" · ")}${r.used_llm ? "" : " (rule-based)"}`);
      load();
    } catch (e) {
      setDetectError(e instanceof Error ? e.message : "Detection failed");
    } finally {
      setDetecting(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold">Issues</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
            Production failure signals, clustered into trackable issues.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={detectDays}
            onChange={(e) => setDetectDays(Number(e.target.value))}
            className="px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-gray-700 dark:text-slate-200"
          >
            {DETECT_WINDOWS.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
          <button
            onClick={runDetect}
            disabled={detecting}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
          >
            {detecting ? "Detecting…" : "Detect now"}
          </button>
        </div>
      </div>

      {detectMsg && (
        <div className="mb-4 text-sm text-gray-600 dark:text-slate-300 bg-gray-100 dark:bg-slate-800 rounded-lg px-4 py-2">
          {detectMsg}
        </div>
      )}

      {detectError && (
        <div className="mb-4 rounded-lg border border-red-200 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-red-700 dark:text-red-300">
              Detection failed.
            </span>
            <button
              onClick={() => setShowErrorDetail((v) => !v)}
              className="text-xs text-red-700 dark:text-red-300 underline hover:no-underline shrink-0"
            >
              {showErrorDetail ? "Hide details" : "Show details"}
            </button>
          </div>
          {showErrorDetail && (
            <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-red-800 dark:text-red-200/90 font-mono">
              {detectError}
            </pre>
          )}
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value || "all"}
            onClick={() => setStatusFilter(f.value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === f.value
                ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300"
                : "text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
          <p>Unable to load issues.</p>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{error}</p>
        </div>
      ) : issues === null ? (
        <p className="text-gray-500 dark:text-slate-400">Loading…</p>
      ) : issues.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
          <p>No issues here.</p>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">
            Run detection to cluster recent failure signals into issues.
          </p>
        </div>
      ) : (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 divide-y divide-gray-100 dark:divide-slate-800">
          {issues.map((issue) => (
            <Link
              key={issue.id}
              href={`/issues/${issue.id}`}
              className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors"
            >
              <span
                className={`px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${SEVERITY_BADGE[issue.severity] || SEVERITY_BADGE.low}`}
              >
                {issue.severity}
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate">{issue.title}</p>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1">
                  {issue.signal_types.map((s) => (
                    <span
                      key={s}
                      className="text-[11px] text-gray-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 rounded px-1.5 py-0.5"
                    >
                      {SIGNAL_LABEL[s] || s}
                    </span>
                  ))}
                  {issue.category && (
                    <span className="text-[11px] text-gray-400 dark:text-slate-500">
                      {issue.category}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm font-medium">
                  {issue.trace_count} trace{issue.trace_count === 1 ? "" : "s"}
                  {issue.affected_pct != null && (
                    <span className="text-gray-400 dark:text-slate-500">
                      {" "}
                      ({(issue.affected_pct * 100).toFixed(1)}%)
                    </span>
                  )}
                </p>
                <p className="text-xs text-gray-400 dark:text-slate-500">
                  {formatRelative(issue.last_seen_at)}
                </p>
              </div>
              <span
                className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ${STATUS_BADGE[issue.status] || STATUS_BADGE.open}`}
              >
                {issue.status}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
