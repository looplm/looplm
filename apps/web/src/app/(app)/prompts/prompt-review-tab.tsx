"use client";

import type { PromptReviewResult } from "@/lib/api";

const SEVERITY_COLORS: Record<string, string> = {
  high: "text-red-400",
  medium: "text-amber-400",
  low: "text-green-400",
};

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
export const sortBySeverity = <T extends { severity: string }>(items: T[]): T[] =>
  [...items].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3));

interface PromptReviewTabProps {
  review: PromptReviewResult | null;
  reviewing: boolean;
  copied: boolean;
  onCopy: (text: string) => void;
  onApply: () => void;
}

export function PromptReviewTab({ review, reviewing, copied, onCopy, onApply }: PromptReviewTabProps) {
  if (reviewing) {
    return (
      <div className="text-sm text-gray-500 dark:text-slate-400 p-4 text-center animate-pulse">
        Analyzing prompt...
      </div>
    );
  }

  if (!review) {
    return (
      <div className="text-sm text-gray-400 dark:text-slate-500 p-4 text-center">
        Click &quot;Review&quot; to analyze this prompt with AI.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {review.anti_patterns.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Anti-Patterns Found</h3>
          <div className="space-y-2">
            {sortBySeverity(review.anti_patterns).map((ap, i) => (
              <div key={i} className="p-3 bg-gray-100/50 dark:bg-slate-800/50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-medium ${SEVERITY_COLORS[ap.severity] ?? "text-slate-300"}`}>
                    {ap.pattern}
                  </span>
                  <span className="text-[9px] text-gray-400 dark:text-slate-500">{ap.severity}</span>
                </div>
                <p className="text-xs text-gray-500 dark:text-slate-400">{ap.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {review.suggestions.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Suggestions</h3>
          <ul className="space-y-1">
            {review.suggestions.map((s, i) => (
              <li key={i} className="text-xs text-gray-600 dark:text-slate-300 flex gap-2">
                <span className="text-indigo-600 dark:text-indigo-400">•</span> {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {review.rewritten_prompt && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400">Rewritten Prompt</h3>
            <div className="flex gap-2">
              <button
                onClick={() => onCopy(review.rewritten_prompt)}
                className="px-2 py-1 text-[10px] bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 rounded text-gray-600 dark:text-slate-300"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
              <button
                onClick={onApply}
                className="px-2 py-1 text-[10px] bg-indigo-50 dark:bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 rounded text-indigo-600 dark:text-indigo-300"
              >
                Apply
              </button>
            </div>
          </div>
          <pre className="p-4 bg-green-950/30 border border-green-500/20 rounded-lg text-xs text-green-200 whitespace-pre-wrap overflow-auto max-h-64">
            {review.rewritten_prompt}
          </pre>
        </div>
      )}

      {review.model && (
        <div className="text-[10px] text-gray-300 dark:text-slate-600 mt-2">
          Model: {review.model} · {review.reviewed_at ? new Date(review.reviewed_at).toLocaleString() : ""}
        </div>
      )}
    </div>
  );
}
