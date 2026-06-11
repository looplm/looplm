"use client";

import { useMemo, useState } from "react";
import type { PlannedLocation } from "@/lib/api";

function topFolder(path: string): string {
  const parts = path.split("/");
  return parts.length > 1 ? parts[0] : "(root)";
}

export function ImportSelectionModal({
  locations,
  repo,
  busy,
  onConfirm,
  onCancel,
}: {
  locations: PlannedLocation[];
  repo: string | null;
  busy: boolean;
  onConfirm: (selectedExternalIds: string[]) => void;
  onCancel: () => void;
}) {
  // Default: everything checked. Already-saved stay checked (kept regardless).
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(locations.map((l) => l.external_id)),
  );

  const groups = useMemo(() => {
    const m = new Map<string, PlannedLocation[]>();
    for (const loc of locations) {
      const key = topFolder(loc.file_path);
      (m.get(key) ?? m.set(key, []).get(key)!).push(loc);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [locations]);

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const newCount = locations.filter((l) => !l.already_saved && checked.has(l.external_id)).length;
  const allChecked = checked.size === locations.length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-xl">
        <div className="p-4 border-b border-gray-100 dark:border-slate-800">
          <h2 className="text-lg font-semibold">Choose prompts to import</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            Found {locations.length} prompt{locations.length !== 1 ? "s" : ""} in {repo ?? "the repo"}.
            Uncheck any you don&apos;t want. Already-saved ones are kept.
          </p>
        </div>

        <div className="px-4 py-2 border-b border-gray-100 dark:border-slate-800 flex items-center justify-between text-xs">
          <button
            onClick={() =>
              setChecked(allChecked ? new Set() : new Set(locations.map((l) => l.external_id)))
            }
            className="text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            {allChecked ? "Deselect all" : "Select all"}
          </button>
          <span className="text-gray-400 dark:text-slate-500">{checked.size} selected</span>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {groups.map(([folder, locs]) => (
            <div key={folder}>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-1">
                {folder}
              </div>
              <div className="space-y-1">
                {locs.map((loc) => (
                  <label
                    key={loc.external_id}
                    className="flex items-start gap-2 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800/50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked.has(loc.external_id)}
                      onChange={() => toggle(loc.external_id)}
                      className="mt-0.5"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{loc.name}</span>
                        {loc.already_saved && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 border border-gray-200 dark:border-slate-700 shrink-0">
                            saved
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-gray-400 dark:text-slate-500 truncate font-mono">
                        {loc.file_path}
                        {loc.line_start ? `:${loc.line_start}` : ""}
                      </div>
                      {loc.note && (
                        <div className="text-[10px] text-gray-400 dark:text-slate-500 truncate">{loc.note}</div>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-gray-100 dark:border-slate-800 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 text-sm rounded-lg bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm([...checked])}
            disabled={busy || checked.size === 0}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? "Starting…" : newCount > 0 ? `Import ${newCount} prompt${newCount !== 1 ? "s" : ""}` : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
