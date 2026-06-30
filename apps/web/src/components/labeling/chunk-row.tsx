"use client";

import { gradeLabel, GRADES } from "./types";

// Shared presentational helpers for chunk rows (used by the pooled-candidate rows). Labeling is
// dataset-driven: every judgeable chunk is a pooled candidate, so there's no separate
// trace-retrieved row component — just these badges and text helpers.

// Read-only badge showing the AI judge's grade for a chunk — a second opinion shown next to the
// human grade buttons, never merged into the human's own label.
export function AiGradeBadge({ grade }: { grade: number }) {
  const tone = GRADES.find((g) => g.value === grade)?.selected ?? "bg-slate-500 border-slate-500 text-white";
  return (
    <span
      title={`AI judge: ${grade} — ${gradeLabel(grade)}`}
      className={`shrink-0 inline-flex items-center gap-1 px-1.5 h-7 rounded-lg text-[10px] font-semibold border ${tone}`}
    >
      <span className="opacity-80">AI</span>
      {grade}
    </span>
  );
}

// Index fields that hold the chunk's full text, in priority order.
export const INDEX_TEXT_FIELDS = ["chunk_text", "content", "text", "chunkText"];

export function pickIndexText(fields: Record<string, unknown> | null): string | null {
  if (!fields) return null;
  for (const k of INDEX_TEXT_FIELDS) {
    const v = fields[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

// Provenance badge per retrieval head — tells the labeler *why* a chunk is in the pool.
export const PROVENANCE_BADGES: Record<string, { label: string; cls: string }> = {
  trace: { label: "Retrieved", cls: "bg-slate-500/10 text-slate-600 dark:text-slate-300" },
  keyword: { label: "BM25", cls: "bg-amber-500/10 text-amber-600 dark:text-amber-300" },
  vector: { label: "Vector", cls: "bg-violet-500/10 text-violet-600 dark:text-violet-300" },
  hybrid: { label: "Hybrid", cls: "bg-teal-500/10 text-teal-600 dark:text-teal-300" },
  semantic: { label: "Reranked", cls: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-300" },
  agentic: { label: "Agentic", cls: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-300" },
};

// Each badge shows the head and, when known, the rank the chunk held in that head — so the
// labeler sees both *why* a chunk is pooled and *where* each method ranked it (e.g. "Vector #3").
export function ProvenanceBadges({
  provenance,
  ranks,
}: {
  provenance: string[];
  ranks?: Record<string, number>;
}) {
  return (
    <>
      {provenance.map((p) => {
        const b =
          PROVENANCE_BADGES[p] ?? {
            label: p,
            cls: "bg-gray-500/10 text-gray-600 dark:text-gray-300",
          };
        const rank = ranks?.[p];
        return (
          <span
            key={p}
            className={`text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${b.cls}`}
          >
            {b.label}
            {rank != null && <span className="ml-1 font-mono normal-case">#{rank}</span>}
          </span>
        );
      })}
    </>
  );
}
