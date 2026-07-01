"use client";

import { useState } from "react";

// Compact multi-select for datasets: a button showing the selection summary that opens a checkbox
// list. Empty selection means "all / most-recent" (the backend default).
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

  const label =
    selected.length === 0
      ? "Most recent"
      : selected.length === 1
        ? datasets.find((d) => d.id === selected[0])?.name ?? "1 dataset"
        : `${selected.length} datasets`;

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[260px]"
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
              <span>{selected.length} selected</span>
              {selected.length > 0 && (
                <button onClick={() => onChange([])} className="hover:text-gray-600 dark:hover:text-slate-300">
                  Clear
                </button>
              )}
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
