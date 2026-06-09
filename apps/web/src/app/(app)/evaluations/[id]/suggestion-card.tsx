"use client";

import { useState } from "react";
import { type CodeSuggestionItem } from "@/lib/api";

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

export function SuggestionCard({
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
      {(suggestion.diff || suggestion.reasoning || ((suggestion.related_test_ids?.length ?? 0) > 0)) && (
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
                {!!suggestion.diff.before && (
                  <div>
                    <p className="text-xs text-red-500 dark:text-red-400 font-medium mb-1">Before:</p>
                    <pre className="text-xs font-mono bg-red-50 dark:bg-red-900/10 text-red-800 dark:text-red-300 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                      {suggestion.diff.before as string}
                    </pre>
                  </div>
                )}
                {!!suggestion.diff.after && (
                  <div>
                    <p className="text-xs text-green-500 dark:text-green-400 font-medium mb-1">After:</p>
                    <pre className="text-xs font-mono bg-green-50 dark:bg-green-900/10 text-green-800 dark:text-green-300 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                      {suggestion.diff.after as string}
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

          {(suggestion.related_test_ids?.length ?? 0) > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Related Tests</p>
              <div className="flex flex-wrap gap-1">
                {(suggestion.related_test_ids ?? []).map((tid) => (
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
