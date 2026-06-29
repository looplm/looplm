"use client";

import { useMemo } from "react";
import {
  type LabelingCase,
  type LabelingPoolResponse,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { PoolChunkRow } from "./pool-chunk-row";
import { PoolSection } from "./pool-section";

// Risk slices a test case can be assigned to (matches the API's SLICE_VALUES).
const SLICES = ["broad", "safety", "adversarial"] as const;

const SLICE_BADGE: Record<string, string> = {
  safety: "bg-red-500/10 text-red-600 dark:text-red-300 border-red-500/30",
  adversarial: "bg-orange-500/10 text-orange-600 dark:text-orange-300 border-orange-500/30",
  broad: "bg-slate-500/10 text-slate-600 dark:text-slate-300 border-slate-500/20",
};

export function CaseCard({
  c,
  canEdit,
  indexConnected,
  datasetId,
  pool,
  poolLoading,
  collapsed,
  onToggleCollapse,
  onToggleComplete,
  onSetSlice,
  onGrade,
  onClearGrade,
  onAiJudge,
  aiJudging,
}: {
  c: LabelingCase;
  canEdit: boolean;
  indexConnected: boolean;
  datasetId?: string;
  // The case's live index pool — the chunks to judge — eager-loaded by the page.
  pool: LabelingPoolResponse | null;
  poolLoading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onToggleComplete: (complete: boolean) => void;
  onSetSlice: (slice: string | null) => void;
  onGrade: (testId: string, chunk: PooledChunkForLabeling, grade: number) => void;
  onClearGrade: (testId: string, chunk: PooledChunkForLabeling) => void;
  // Run the LLM "AI judge" over this case's pooled chunks (a one-click second annotator).
  onAiJudge: () => void;
  aiJudging: boolean;
}) {
  const chunks = useMemo(() => pool?.chunks ?? [], [pool]);
  // Counts come from the live pool once loaded; until then fall back to the view's tallies.
  const counts = useMemo(() => {
    if (!pool) return { labeled: c.labeled_count, relevant: c.relevant_count, total: null as number | null };
    return {
      labeled: chunks.filter((ch) => ch.relevance != null).length,
      relevant: chunks.filter((ch) => (ch.relevance ?? 0) >= 1).length,
      total: chunks.length,
    };
  }, [pool, chunks, c.labeled_count, c.relevant_count]);

  const shownIds = useMemo(
    () => new Set(chunks.map((ch) => ch.chunk_id)),
    [chunks],
  );

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30">
        <button onClick={onToggleCollapse} className="flex items-center gap-2 min-w-0 text-left">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`shrink-0 text-gray-400 dark:text-slate-500 transition-transform ${collapsed ? "" : "rotate-90"}`}
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate" title={c.input ?? c.test_id}>
            {c.input || c.test_id}
          </span>
        </button>
        <div className="shrink-0 flex items-center gap-3 text-[11px] text-gray-400 dark:text-slate-500">
          {c.labelers.length > 0 && (
            <span className="hidden sm:inline italic truncate max-w-[160px]" title={`Labeled by ${c.labelers.join(", ")}`}>
              by {c.labelers.join(", ")}
            </span>
          )}
          <span>
            {counts.labeled}
            {counts.total != null ? `/${counts.total}` : ""} · {counts.relevant} relevant
          </span>
          <select
            disabled={!canEdit}
            value={c.slice ?? "broad"}
            onChange={(e) => onSetSlice(e.target.value === "broad" ? null : e.target.value)}
            title="Risk slice — safety/adversarial are pooled deeper and reported separately"
            className={`rounded-lg border px-2 py-1 text-[11px] font-medium capitalize disabled:opacity-40 ${
              SLICE_BADGE[c.slice ?? "broad"]
            }`}
          >
            {SLICES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            disabled={!canEdit || aiJudging || !indexConnected}
            onClick={onAiJudge}
            title="Grade this case's chunks with the LLM — a second opinion that shows up in annotator agreement"
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400 disabled:opacity-40"
          >
            <span aria-hidden className={aiJudging ? "animate-pulse" : ""}>✦</span>
            {aiJudging ? "Judging…" : "AI judge"}
          </button>
          <button
            disabled={!canEdit}
            onClick={() => onToggleComplete(!c.complete)}
            className={`px-2 py-1 rounded-lg text-[11px] font-medium border transition-colors disabled:opacity-40 ${
              c.complete
                ? "bg-emerald-500 border-emerald-500 text-white"
                : "border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-emerald-400"
            }`}
          >
            {c.complete ? "✓ Complete" : "Mark complete"}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div>
          {!indexConnected ? (
            <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">
              Connect an index provider (Settings → Integrations) to pool candidate chunks for
              this query.
            </p>
          ) : poolLoading && !pool ? (
            <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">Pooling candidates…</p>
          ) : chunks.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">
              No candidates found for this query
              {pool && Object.keys(pool.heads_failed).length > 0
                ? ` (${Object.keys(pool.heads_failed).join(", ")} unavailable)`
                : ""}
              . Use the search box below to try a different query.
            </p>
          ) : (
            chunks.map((chunk) => (
              <PoolChunkRow
                key={chunk.chunk_id}
                chunk={chunk}
                relevance={chunk.relevance ?? null}
                disabled={!canEdit}
                indexConnected={indexConnected}
                onGrade={(grade) => onGrade(c.test_id, chunk, grade)}
                onClear={() => onClearGrade(c.test_id, chunk)}
              />
            ))
          )}
          <PoolSection
            testId={c.test_id}
            datasetId={datasetId}
            canEdit={canEdit}
            indexConnected={indexConnected}
            alreadyShownIds={shownIds}
          />
        </div>
      )}
    </div>
  );
}
