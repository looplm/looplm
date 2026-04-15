"use client";

import type { TestCaseItem, TestCaseSuggestion } from "@/lib/api";

type ConditionData = Pick<
  TestCaseItem,
  "team_filter" | "tag_filter" | "context_filters" | "message_count" | "has_summary" | "metadata"
>;

export function TestCaseConditions({ data }: { data: ConditionData }) {
  const { team_filter, tag_filter, context_filters, message_count, has_summary, metadata } = data;
  const hasAnything =
    team_filter.length > 0 ||
    tag_filter.length > 0 ||
    Object.keys(context_filters).length > 0 ||
    message_count != null ||
    has_summary ||
    Object.keys(metadata || {}).length > 0;

  if (!hasAnything) {
    return <span className="text-xs text-gray-400 dark:text-slate-500">No conditions</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {team_filter.map((t) => (
        <span
          key={t}
          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300"
        >
          {t}
        </span>
      ))}
      {Object.entries(context_filters).map(([k, v]) =>
        v ? (
          <span
            key={k}
            className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300"
          >
            {k}: {v}
          </span>
        ) : null
      )}
      {message_count != null && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
          {message_count} msgs
        </span>
      )}
      {has_summary && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
          Summary
        </span>
      )}
      {tag_filter.map((t) => (
        <span
          key={t}
          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs border border-gray-300 dark:border-slate-600 text-gray-500 dark:text-slate-400"
        >
          {t}
        </span>
      ))}
      {Object.entries(metadata || {}).map(([k, v]) => (
        <span
          key={k}
          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
        >
          {k}: {typeof v === "boolean" ? (v ? "yes" : "no") : String(v)}
        </span>
      ))}
    </div>
  );
}

export function SuggestionConditions({ data }: { data: TestCaseSuggestion }) {
  return (
    <TestCaseConditions
      data={{
        team_filter: data.team_filter,
        tag_filter: data.tag_filter,
        context_filters: data.context_filters,
        message_count: data.message_count,
        has_summary: data.has_summary,
        metadata: {},
      }}
    />
  );
}
