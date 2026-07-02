"use client";

// Labeled segmented selector styled to match the panel's header toggles. Display-only — used for
// the retriever selector and the per-k metric selector; switching just re-points what's rendered.
export function RetrieverSelector({
  options,
  value,
  onChange,
  label = "Retriever",
  title = "Which retriever the metrics above reflect",
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  label?: string;
  title?: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs" title={title}>
      <span className="text-gray-400 dark:text-slate-500">{label}</span>
      <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
        {options.map((o) => (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`px-2.5 py-1.5 whitespace-nowrap ${
              o.value === value
                ? "bg-indigo-600 text-white"
                : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
