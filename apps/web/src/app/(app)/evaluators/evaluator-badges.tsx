export function TypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    llm_judge: "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400",
    deterministic: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
    hybrid: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  };
  const labels: Record<string, string> = {
    llm_judge: "LLM Judge",
    deterministic: "Code",
    hybrid: "Hybrid",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${styles[type] || "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400"}`}>
      {labels[type] || type}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string | null | undefined }) {
  const styles: Record<string, string> = {
    retrieval: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400",
    generation: "bg-fuchsia-100 dark:bg-fuchsia-900/30 text-fuchsia-700 dark:text-fuchsia-400",
  };
  if (!category) {
    return <span className="text-gray-300 dark:text-slate-600">&ndash;</span>;
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium capitalize ${styles[category] || "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400"}`}>
      {category}
    </span>
  );
}

export function SourceBadge({ source }: { source: string | null }) {
  const styles: Record<string, string> = {
    custom: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
    ragas: "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400",
    langfuse: "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400",
    discovered: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400",
  };
  const labels: Record<string, string> = {
    custom: "Custom",
    ragas: "RAGAS",
    langfuse: "Langfuse",
    discovered: "Discovered",
  };
  const s = source || "custom";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${styles[s] || "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400"}`}>
      {labels[s] || s.charAt(0).toUpperCase() + s.slice(1)}
    </span>
  );
}

export function RelevanceBadge({ relevance }: { relevance: string }) {
  const styles: Record<string, string> = {
    core: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
    important: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
    minor: "bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium capitalize ${styles[relevance] || styles.medium}`}>
      {relevance}
    </span>
  );
}

export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "-";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function PillGroup<T extends string>({
  options,
  value,
  onChange,
  styles,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  styles: Record<string, { active: string; inactive: string }>;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const selected = value === opt.value;
        const s = styles[opt.value] || { active: "bg-gray-200 text-gray-700", inactive: "bg-gray-50 text-gray-400" };
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              selected
                ? s.active
                : `${s.inactive} hover:opacity-80`
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function SectionHeader({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500">
      <span className="text-sm">{icon}</span>
      {label}
    </div>
  );
}

export const TYPE_PILL_STYLES: Record<string, { active: string; inactive: string }> = {
  llm_judge: {
    active: "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 ring-1 ring-purple-300 dark:ring-purple-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  deterministic: {
    active: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 ring-1 ring-blue-300 dark:ring-blue-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  hybrid: {
    active: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 ring-1 ring-amber-300 dark:ring-amber-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
};

export const SOURCE_PILL_STYLES: Record<string, { active: string; inactive: string }> = {
  custom: {
    active: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 ring-1 ring-green-300 dark:ring-green-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  ragas: {
    active: "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400 ring-1 ring-teal-300 dark:ring-teal-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  langfuse: {
    active: "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400 ring-1 ring-rose-300 dark:ring-rose-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  discovered: {
    active: "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 ring-1 ring-gray-300 dark:ring-gray-600",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
};

export const CHECK_TYPE_PILL_STYLES: Record<string, { active: string; inactive: string }> = {
  contains_urls: {
    active: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400 ring-1 ring-sky-300 dark:ring-sky-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  contains_sources: {
    active: "bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400 ring-1 ring-cyan-300 dark:ring-cyan-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  regex_match: {
    active: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 ring-1 ring-blue-300 dark:ring-blue-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  string_contains: {
    active: "bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 ring-1 ring-indigo-300 dark:ring-indigo-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  image_missing: {
    active: "bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 ring-1 ring-orange-300 dark:ring-orange-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  image_ordering: {
    active: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400 ring-1 ring-violet-300 dark:ring-violet-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
};

export const CATEGORY_PILL_STYLES: Record<string, { active: string; inactive: string }> = {
  retrieval: {
    active: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400 ring-1 ring-sky-300 dark:ring-sky-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  generation: {
    active: "bg-fuchsia-100 dark:bg-fuchsia-900/30 text-fuchsia-700 dark:text-fuchsia-400 ring-1 ring-fuchsia-300 dark:ring-fuchsia-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
};

export const RELEVANCE_PILL_STYLES: Record<string, { active: string; inactive: string }> = {
  core: {
    active: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-1 ring-red-300 dark:ring-red-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  important: {
    active: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 ring-1 ring-amber-300 dark:ring-amber-700",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
  minor: {
    active: "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 ring-1 ring-gray-300 dark:ring-gray-600",
    inactive: "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 ring-1 ring-gray-200 dark:ring-slate-700",
  },
};
