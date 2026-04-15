"use client";

import { useState, useRef, useEffect } from "react";

const RELEVANCE_LEVELS = [
  { value: "core", label: "Core", description: "Affects pass/fail verdict" },
  { value: "important", label: "Important", description: "Key quality signals" },
  { value: "minor", label: "Minor", description: "Nice-to-have checks" },
] as const;

type RelevanceLevel = (typeof RELEVANCE_LEVELS)[number]["value"];

interface RelevanceFilterDropdownProps {
  onGenerate: (relevanceFilter: RelevanceLevel[] | undefined) => void;
  loading?: boolean;
  buttonClassName?: string;
}

export function RelevanceFilterDropdown({
  onGenerate,
  loading,
  buttonClassName,
}: RelevanceFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<RelevanceLevel>>(
    new Set(["core", "important", "minor"])
  );
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function toggle(level: RelevanceLevel) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        // Don't allow deselecting all
        if (next.size <= 1) return prev;
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  }

  function handleGenerate() {
    setOpen(false);
    const allSelected = selected.size === RELEVANCE_LEVELS.length;
    onGenerate(allSelected ? undefined : Array.from(selected));
  }

  const allSelected = selected.size === RELEVANCE_LEVELS.length;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={loading}
        className={
          buttonClassName ??
          "px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        }
      >
        {loading ? "Generating..." : "Generate Report"}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-72 rounded-xl bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 shadow-xl z-50">
          <div className="px-4 pt-3 pb-2">
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              Include graders by relevance
            </p>
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
              Select which grader levels to include in the report
            </p>
          </div>
          <div className="px-2 pb-2">
            {RELEVANCE_LEVELS.map((level) => (
              <label
                key={level.value}
                className="flex items-start gap-3 px-2 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.has(level.value)}
                  onChange={() => toggle(level.value)}
                  className="mt-0.5 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                />
                <div>
                  <span className="text-sm font-medium text-gray-800 dark:text-slate-200">
                    {level.label}
                  </span>
                  <p className="text-xs text-gray-400 dark:text-slate-500">
                    {level.description}
                  </p>
                </div>
              </label>
            ))}
          </div>
          <div className="px-4 pb-3 flex items-center justify-between border-t border-gray-100 dark:border-slate-800 pt-2">
            <span className="text-xs text-gray-400 dark:text-slate-500">
              {allSelected ? "All graders" : `${selected.size} of ${RELEVANCE_LEVELS.length} levels`}
            </span>
            <button
              onClick={handleGenerate}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
            >
              Generate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
