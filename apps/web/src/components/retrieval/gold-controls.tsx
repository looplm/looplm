"use client";

import { gradeLabel } from "@/components/labeling/types";

export type GoldSource = "human" | "ai" | "both";
export type MinGrade = 1 | 2 | 3;

const toggleClass = (active: boolean) =>
  `px-2.5 py-1.5 ${
    active
      ? "bg-indigo-600 text-white"
      : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
  }`;

// Header controls for the labels path: which annotators resolve the gold, and how strictly the
// binary metrics binarize it. min grade is a TREC-style lenient/strict switch: recall, precision,
// hit rate and bpref only count chunks whose gold grade is at or above it; relevant chunks below
// it become unjudged (neither hits nor misses), and graded nDCG is unaffected either way.
export function GoldControls({
  goldSource,
  minGrade,
  onGoldSource,
  onMinGrade,
}: {
  goldSource: GoldSource;
  minGrade: MinGrade;
  onGoldSource: (g: GoldSource) => void;
  onMinGrade: (g: MinGrade) => void;
}) {
  return (
    <>
      <div
        className="flex items-center gap-1.5 text-xs"
        title="Which chunk labels resolve the gold: human only, the AI judge only, or both"
      >
        <span className="text-gray-400 dark:text-slate-500">Gold</span>
        <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
          {(["human", "ai", "both"] as const).map((g) => (
            <button
              key={g}
              onClick={() => onGoldSource(g)}
              className={`${toggleClass(goldSource === g)} capitalize`}
            >
              {g === "ai" ? "AI" : g}
            </button>
          ))}
        </div>
      </div>
      <div
        className="flex items-center gap-1.5 text-xs"
        title="Strictness: recall/precision/hit rate/MRR/bpref only count chunks labeled at or above this grade. Relevant chunks below it are treated as unjudged, not as misses. Exception: nDCG always weights by the full 1-3 grades, so its card does not move with this selector."
      >
        <span className="text-gray-400 dark:text-slate-500">Min grade</span>
        <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
          {([1, 2, 3] as const).map((g) => (
            <button
              key={g}
              onClick={() => onMinGrade(g)}
              className={`${toggleClass(minGrade === g)} tabular-nums`}
              title={`Counts as relevant: ${gradeLabel(g).toLowerCase()} or higher`}
            >
              {g}+
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
