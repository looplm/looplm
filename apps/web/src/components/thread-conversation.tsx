"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { getTraces, getTrace } from "@/lib/api";
import type { TraceDetail } from "@/lib/api-types";
import SmartViewer from "@/components/smart-viewer";
import StatusBadge from "@/components/status-badge";

interface ThreadConversationProps {
  threadId: string;
  currentTraceId: string;
  currentTraceStartTime: string;
}

export default function ThreadConversation({
  threadId,
  currentTraceId,
  currentTraceStartTime,
}: ThreadConversationProps) {
  const [expanded, setExpanded] = useState(false);
  const [traces, setTraces] = useState<TraceDetail[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchThread = useCallback(async () => {
    if (traces) return; // already cached
    setLoading(true);
    setError(null);
    try {
      const list = await getTraces({ thread_id: threadId, per_page: "100" });
      const filtered = list.data.filter(
        (t) => new Date(t.start_time) <= new Date(currentTraceStartTime)
      );
      filtered.sort(
        (a, b) =>
          new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
      );
      const details = await Promise.all(
        filtered.map((t) => getTrace(t.id))
      );
      setTraces(details);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [threadId, currentTraceStartTime, traces]);

  const handleToggle = () => {
    if (!expanded) fetchThread();
    setExpanded(!expanded);
  };

  const messageCount = traces?.length;

  return (
    <div className="mb-8 rounded-xl border border-indigo-500/20 bg-indigo-500/5 overflow-hidden">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-indigo-500/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs text-indigo-400 dark:text-indigo-300">
            {expanded ? "▼" : "▶"}
          </span>
          <span className="text-sm font-medium text-indigo-400 dark:text-indigo-300">
            Thread Conversation
          </span>
          <span
            className="text-xs font-mono px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-700 dark:text-indigo-100 select-all cursor-text"
            onClick={(e) => e.stopPropagation()}
          >
            {threadId}
          </span>
          {messageCount != null && (
            <span className="text-xs text-gray-500 dark:text-slate-400">
              {messageCount} message{messageCount !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-400 dark:text-slate-500">
          {expanded ? "Collapse" : "Expand"}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-indigo-500/20 px-4 py-4">
          {loading && (
            <p className="text-sm text-gray-500 dark:text-slate-400">
              Loading thread history…
            </p>
          )}
          {error && (
            <p className="text-sm text-red-400">Error: {error}</p>
          )}
          {traces && traces.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-slate-400">
              No prior messages in this thread.
            </p>
          )}
          {traces && traces.length > 0 && (
            <div className="space-y-4">
              {traces.map((t) => {
                const isCurrent = t.id === currentTraceId;
                return (
                  <div
                    key={t.id}
                    className={`rounded-lg border p-4 ${
                      isCurrent
                        ? "border-indigo-500/50 bg-indigo-500/10"
                        : "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-xs text-gray-400 dark:text-slate-500">
                        {new Date(t.start_time).toLocaleString()}
                      </span>
                      <Link
                        href={`/traces/${t.id}`}
                        className="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                      >
                        {t.name || t.external_id}
                      </Link>
                      <StatusBadge status={t.status || undefined} />
                      {isCurrent && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                          current
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {!!t.input && (
                        <SmartViewer data={t.input as any} title="Input" />
                      )}
                      {!!t.output && (
                        <SmartViewer data={t.output as any} title="Output" />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
