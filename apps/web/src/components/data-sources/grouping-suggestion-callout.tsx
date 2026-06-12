"use client";

import { useState } from "react";

import type {
  IndexGroupingSuggestion,
  IndexPartitionKey,
} from "@/lib/api-types/index-explorer";

function labelFor(key: string, keys: IndexPartitionKey[]): string {
  return keys.find((k) => k.key === key)?.label ?? key;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-3.5 h-3.5 flex-shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

function HintRow({
  severity,
  title,
  message,
  suggestedField,
}: {
  severity: "info" | "warning";
  title: string;
  message: string;
  suggestedField: string | null;
}) {
  const warn = severity === "warning";
  return (
    <div
      className={`flex gap-2 rounded-lg px-3 py-2 text-xs ${
        warn
          ? "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300"
          : "bg-gray-50 dark:bg-slate-800/60 text-gray-600 dark:text-slate-300"
      }`}
    >
      <span className="flex-shrink-0">{warn ? "⚠️" : "💡"}</span>
      <span>
        <span className="font-medium">{title}</span>
        {message ? <> — {message}</> : null}
        {suggestedField ? (
          <>
            {" "}
            <span className="text-[11px]">Suggested field:</span>{" "}
            <code className="rounded bg-black/5 dark:bg-white/10 px-1 py-0.5">
              {suggestedField}
            </code>
          </>
        ) : null}
      </span>
    </div>
  );
}

export function GroupingSuggestionCallout({
  suggestion,
  keys,
  loading,
  error,
  onReanalyze,
  canReanalyze,
}: {
  suggestion: IndexGroupingSuggestion | null;
  keys: IndexPartitionKey[];
  loading: boolean;
  error: string | null;
  onReanalyze: () => void;
  canReanalyze: boolean;
}) {
  const [open, setOpen] = useState(false);

  // Nothing to show until we have a result, an error, or work in flight.
  if (!loading && !error && !suggestion) return null;

  // Reason for the level whose field set matches `fields` (order-insensitive).
  const levelReason = (fields: string[]) => {
    const want = [...fields].sort().join(",");
    return (
      suggestion?.levels.find((l) => [...l.keys].sort().join(",") === want)?.reason ?? ""
    );
  };

  // Compact teaser for the collapsed header: the suggested hierarchy as a short
  // inline path, falling back to a tip count.
  const teaser = (() => {
    if (loading) return "analyzing index…";
    if (!suggestion) return "";
    if (suggestion.suggested_levels.length > 0) {
      return suggestion.suggested_levels
        .map((lvl) => lvl.map((k) => labelFor(k, keys)).join(" or "))
        .join(" → ");
    }
    const n = suggestion.hints.length;
    return n > 0 ? `${n} tip${n === 1 ? "" : "s"}` : "";
  })();

  return (
    <div className="rounded-xl border border-indigo-100 dark:border-indigo-900/40 bg-indigo-50/50 dark:bg-indigo-900/10 p-4 mb-4">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 items-center gap-2 text-left text-sm font-medium text-indigo-700 dark:text-indigo-300"
          aria-expanded={open}
        >
          <Chevron open={open} />
          <span className="flex-shrink-0">✨ Suggested grouping</span>
          {!open && teaser && (
            <span className="truncate text-xs font-normal text-indigo-500/80 dark:text-indigo-400/80">
              {teaser}
            </span>
          )}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onReanalyze();
          }}
          disabled={loading || !canReanalyze}
          className="flex-shrink-0 text-xs px-2 py-1 rounded-md text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100/60 dark:hover:bg-indigo-900/30 disabled:opacity-40 disabled:cursor-not-allowed"
          title={canReanalyze ? "Re-run the analysis" : "You don't have permission to re-run"}
        >
          Re-analyze
        </button>
      </div>

      {error && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>
      )}

      {open && suggestion && (
        <>
          {suggestion.summary && (
            <p className="mt-2 text-sm text-gray-600 dark:text-slate-300">
              {suggestion.summary}
            </p>
          )}

          {suggestion.suggested_levels.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {suggestion.suggested_levels.map((level, idx) => (
                <span key={idx} className="flex items-center gap-1.5">
                  {idx > 0 && (
                    <span className="text-gray-400 dark:text-slate-500">→</span>
                  )}
                  <span
                    className="flex items-center gap-1 px-2 py-1 rounded-md bg-white dark:bg-slate-900 border border-indigo-200/70 dark:border-indigo-800/50 text-xs text-gray-700 dark:text-slate-200"
                    title={levelReason(level)}
                  >
                    {level.map((key, j) => (
                      <span key={key} className="flex items-center gap-1">
                        {j > 0 && (
                          <span className="text-[10px] text-gray-400 dark:text-slate-500">
                            or
                          </span>
                        )}
                        {labelFor(key, keys)}
                      </span>
                    ))}
                  </span>
                </span>
              ))}
            </div>
          )}

          {suggestion.hints.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-medium text-gray-700 dark:text-slate-200">
                Tips for restructuring your index
              </p>
              <p className="mt-0.5 text-[11px] text-gray-500 dark:text-slate-400">
                These suggest metadata/index changes for clearer grouping and drill-down in
                LoopLM — they are not aimed at better search or retrieval performance.
              </p>
              <div className="mt-2 space-y-1.5">
                {suggestion.hints.map((h, idx) => (
                  <HintRow
                    key={idx}
                    severity={h.severity}
                    title={h.title}
                    message={h.message}
                    suggestedField={h.suggested_field}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
