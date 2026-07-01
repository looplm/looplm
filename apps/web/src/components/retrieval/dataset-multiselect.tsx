"use client";

import { useState } from "react";

// Compact multi-select for datasets: a button showing the selection summary that opens a checkbox
// list with Select all / Clear all. The caller decides what an empty selection means.
export function DatasetMultiSelect({
  datasets,
  selected,
  onChange,
}: {
  datasets: { id: string; name: string }[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);

  const allSelected = datasets.length > 0 && selected.length === datasets.length;
  const label =
    selected.length === 0
      ? "Select datasets"
      : allSelected
        ? `All datasets (${datasets.length})`
        : selected.length === 1
          ? datasets.find((d) => d.id === selected[0])?.name ?? "1 dataset"
          : `${selected.length} of ${datasets.length} datasets`;

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 text-sm rounded-lg border bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[260px] ${
          selected.length === 0
            ? "border-amber-300 dark:border-amber-500/40 text-amber-600 dark:text-amber-400"
            : "border-gray-200 dark:border-slate-700"
        }`}
        title="Datasets to aggregate over"
      >
        <span className="truncate">{label}</span>
        <span className="text-gray-400">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-1 z-20 w-72 max-h-72 overflow-auto rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg p-1">
            <div className="flex items-center justify-between px-2 py-1.5 text-[11px] text-gray-400 dark:text-slate-500">
              <span>
                {selected.length} of {datasets.length} selected
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onChange(datasets.map((d) => d.id))}
                  disabled={allSelected}
                  className="hover:text-gray-600 dark:hover:text-slate-300 disabled:opacity-40"
                >
                  Select all
                </button>
                <button
                  onClick={() => onChange([])}
                  disabled={selected.length === 0}
                  className="hover:text-gray-600 dark:hover:text-slate-300 disabled:opacity-40"
                >
                  Clear all
                </button>
              </div>
            </div>
            {datasets.map((d) => (
              <label
                key={d.id}
                className="flex items-center gap-2 px-2 py-1.5 text-sm rounded hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(d.id)}
                  onChange={() => toggle(d.id)}
                  className="rounded border-gray-300 dark:border-slate-600"
                />
                <span className="truncate">{d.name}</span>
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
