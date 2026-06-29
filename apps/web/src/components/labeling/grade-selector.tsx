"use client";

import { GRADES } from "./types";

// Four-button 0..3 relevance picker, shared by retrieved rows, pooled candidates and adjudication.
export function GradeSelector({
  value,
  disabled,
  onSelect,
}: {
  value: number | null;
  disabled: boolean;
  onSelect: (grade: number) => void;
}) {
  return (
    <div className="shrink-0 flex items-center gap-1" role="group" aria-label="Relevance grade">
      {GRADES.map((g) => (
        <button
          key={g.value}
          disabled={disabled}
          onClick={() => onSelect(g.value)}
          title={`${g.value} — ${g.label}`}
          className={`w-7 h-7 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-40 ${
            value === g.value
              ? g.selected
              : `border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 ${g.hover}`
          }`}
        >
          {g.value}
        </button>
      ))}
    </div>
  );
}
