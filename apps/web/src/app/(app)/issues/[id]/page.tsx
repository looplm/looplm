"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getIssue,
  resolveIssue,
  dismissIssue,
  type IssueDetail,
} from "@/lib/api";
import {
  SEVERITY_BADGE,
  STATUS_BADGE,
  SIGNAL_LABEL,
  formatTimestamp,
} from "../issue-format";

export default function IssueDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [issue, setIssue] = useState<IssueDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  const load = useCallback(() => {
    setError(null);
    getIssue(id)
      .then(setIssue)
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    setIssue(null);
    load();
  }, [load]);

  async function act(fn: (id: string) => Promise<unknown>) {
    setActing(true);
    try {
      await fn(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setActing(false);
    }
  }

  if (error) {
    return (
      <div>
        <BackLink />
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
          <p>Unable to load issue.</p>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{error}</p>
        </div>
      </div>
    );
  }

  if (!issue) {
    return (
      <div>
        <BackLink />
        <p className="text-gray-500 dark:text-slate-400">Loading…</p>
      </div>
    );
  }

  const isClosed = issue.status === "resolved" || issue.status === "dismissed";

  return (
    <div className="max-w-4xl">
      <BackLink />

      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${SEVERITY_BADGE[issue.severity] || SEVERITY_BADGE.low}`}
            >
              {issue.severity}
            </span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_BADGE[issue.status] || STATUS_BADGE.open}`}
            >
              {issue.status}
            </span>
            {issue.category && (
              <span className="text-xs text-gray-400 dark:text-slate-500">
                {issue.category}
              </span>
            )}
          </div>
          <h1 className="text-2xl font-bold">{issue.title}</h1>
        </div>
        {!isClosed && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => act(resolveIssue)}
              disabled={acting}
              className="px-3 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-500 disabled:opacity-50 transition-colors"
            >
              Resolve
            </button>
            <button
              onClick={() => act(dismissIssue)}
              disabled={acting}
              className="px-3 py-2 rounded-lg bg-gray-200 dark:bg-slate-700 text-gray-700 dark:text-slate-200 text-sm font-medium hover:bg-gray-300 dark:hover:bg-slate-600 disabled:opacity-50 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <Stat label="Affected traces" value={String(issue.trace_count)} />
        <Stat
          label="Affected %"
          value={issue.affected_pct != null ? `${(issue.affected_pct * 100).toFixed(1)}%` : "—"}
        />
        <Stat label="First seen" value={formatTimestamp(issue.first_seen_at)} small />
        <Stat label="Last seen" value={formatTimestamp(issue.last_seen_at)} small />
      </div>

      {/* Signal types */}
      <div className="flex flex-wrap gap-2 mb-6">
        {issue.signal_types.map((s) => (
          <span
            key={s}
            className="text-xs text-gray-600 dark:text-slate-300 bg-gray-100 dark:bg-slate-800 rounded-md px-2 py-1"
          >
            {SIGNAL_LABEL[s] || s}
          </span>
        ))}
      </div>

      {/* Root cause */}
      <Section title="Root cause">
        {issue.root_cause ? (
          <p className="text-sm text-gray-700 dark:text-slate-200 whitespace-pre-wrap">
            {issue.root_cause}
          </p>
        ) : (
          <p className="text-sm text-gray-400 dark:text-slate-500">
            Not yet diagnosed.
          </p>
        )}
      </Section>

      {/* Suggested fix */}
      {issue.suggested_fix && (
        <Section title="Suggested fix">
          <p className="text-sm text-gray-700 dark:text-slate-200 whitespace-pre-wrap">
            {issue.suggested_fix}
          </p>
        </Section>
      )}

      {/* Evidence */}
      <Section title={`Evidence (${issue.evidence.length})`}>
        {issue.evidence.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-slate-500">No evidence.</p>
        ) : (
          <ul className="space-y-2">
            {issue.evidence.map((e, i) => (
              <li
                key={`${e.trace_id ?? "none"}-${e.signal_type}-${i}`}
                className="flex items-start justify-between gap-3 text-sm"
              >
                <div className="min-w-0">
                  <span className="text-xs text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-500/20 rounded px-1.5 py-0.5">
                    {SIGNAL_LABEL[e.signal_type] || e.signal_type}
                  </span>
                  {e.detail && (
                    <span className="ml-2 text-gray-600 dark:text-slate-300">
                      {e.detail}
                    </span>
                  )}
                </div>
                {e.trace_id && (
                  <Link
                    href={`/traces/${e.trace_id}`}
                    className="shrink-0 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                  >
                    View trace →
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Timeline */}
      <Section title="Timeline">
        {issue.events.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-slate-500">No events.</p>
        ) : (
          <ul className="space-y-2">
            {issue.events.map((ev, i) => (
              <li key={i} className="flex items-center justify-between text-sm">
                <span className="capitalize text-gray-700 dark:text-slate-200">
                  {ev.event_type.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-gray-400 dark:text-slate-500">
                  {formatTimestamp(ev.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );

  function BackLink() {
    return (
      <button
        onClick={() => router.push("/issues")}
        className="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white mb-4 transition-colors"
      >
        ← Back to issues
      </button>
    );
  }
}

function Stat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">{label}</p>
      <p className={`font-bold ${small ? "text-sm" : "text-2xl"}`}>{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-6">
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      {children}
    </div>
  );
}
