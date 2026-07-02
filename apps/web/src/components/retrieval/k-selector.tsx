"use client";

// Compact "@k" cutoff selector for the Retrieval quality tables. Purely a display control — every
// k's value is already in the metrics response, so switching k just re-keys what the tables read
// (no recompute). Styled to match the panel's other header segmented toggles. Renders nothing when
// there's only one cutoff to choose from.
export function KSelector({
  ks,
  value,
  onChange,
}: {
  ks: number[];
  value: number;
  onChange: (k: number) => void;
}) {
  if (ks.length < 2) return null;
  return (
    <div className="flex items-center gap-1.5 text-xs" title="Cutoff depth: show metrics at the top-k">
      <span className="text-gray-400 dark:text-slate-500">@k</span>
      <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
        {ks.map((k) => (
          <button
            key={k}
            onClick={() => onChange(k)}
            className={`px-2.5 py-1.5 tabular-nums ${
              k === value
                ? "bg-indigo-600 text-white"
                : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
            }`}
          >
            {k}
          </button>
        ))}
      </div>
    </div>
  );
}
