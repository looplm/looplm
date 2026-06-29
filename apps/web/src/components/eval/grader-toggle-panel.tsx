"use client";

import type { EvalRunDetail, EvaluatorItem } from "@/lib/api";
import {
  graderDisplayName,
  passRateTextColor,
  retrievalMetricBadges,
} from "@/app/(app)/evaluations/[id]/eval-utils";

interface GraderTogglePanelProps {
  allGraderNames: string[];
  run: EvalRunDetail;
  evaluatorMap: Record<string, EvaluatorItem>;
  disabledGraders: Set<string>;
  onToggleGrader: (name: string) => void;
}

export function GraderTogglePanel({
  allGraderNames,
  run,
  evaluatorMap,
  disabledGraders,
  onToggleGrader,
}: GraderTogglePanelProps) {
  if (allGraderNames.length === 0) return null;

  const passFailGraders = allGraderNames.filter((n) => evaluatorMap[n]?.affects_pass);
  const qualityGraders = allGraderNames.filter((n) => !evaluatorMap[n]?.affects_pass);

  const renderToggle = (name: string) => {
    const summary = run.grader_summary[name];
    const enabled = !disabledGraders.has(name);
    const meta = evaluatorMap[name];
    return (
      <button
        key={name}
        onClick={() => onToggleGrader(name)}
        className={`px-3 py-1.5 rounded-lg text-base font-medium border transition-colors flex items-center gap-1.5 ${
          enabled
            ? "bg-white dark:bg-slate-900 text-gray-800 dark:text-slate-200 border-gray-200 dark:border-slate-700"
            : "bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500 border-gray-200 dark:border-slate-700 line-through"
        }`}
      >
        {graderDisplayName(name, evaluatorMap)}
        <span className={`text-sm font-semibold ${enabled ? passRateTextColor(summary.pass_rate) : ""}`}>
          {(summary.pass_rate * 100).toFixed(0)}%
        </span>
        {meta && enabled && (
          <span className={`text-sm font-medium px-1.5 py-0.5 rounded ${
            meta.source === "ragas" ? "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400"
            : meta.source === "langfuse" ? "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400"
            : "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
          }`}>
            {meta.source === "ragas" ? "RAGAS" : meta.source === "langfuse" ? "Langfuse" : "Custom"}
          </span>
        )}
        {enabled && retrievalMetricBadges(summary).map(({ label, text, title }) => (
          <span
            key={label}
            className="text-sm font-medium text-indigo-600 dark:text-indigo-400"
            title={title}
          >
            {text}
          </span>
        ))}
      </button>
    );
  };

  return (
    <div className="mb-6 flex flex-col gap-4">
      {passFailGraders.length > 0 && (
        <div>
          <p className="text-sm font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
            Pass / Fail Graders
          </p>
          <div className="flex flex-wrap gap-2">
            {passFailGraders.map(renderToggle)}
          </div>
        </div>
      )}
      {qualityGraders.length > 0 && (
        <div>
          <p className="text-sm font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
            Additional Graders
          </p>
          <div className="flex flex-wrap gap-2">
            {qualityGraders.map(renderToggle)}
          </div>
        </div>
      )}
      {disabledGraders.size > 0 && (
        <p className="text-sm text-gray-400 dark:text-slate-500">
          {disabledGraders.size} grader{disabledGraders.size > 1 ? "s" : ""} disabled — stats recomputed
        </p>
      )}
    </div>
  );
}
