"use client";

import { useMemo } from "react";
import {
  type LabelingCase,
  type LabelingPoolResponse,
  type ChunkForLabeling,
} from "@/lib/api";
import { ChunkRow } from "./chunk-row";
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
  pool,
  poolLoading,
  collapsed,
  onToggleCollapse,
  onToggleComplete,
  onSetSlice,
  onGrade,
}: {
  c: LabelingCase;
  canEdit: boolean;
  indexConnected: boolean;
  // The case's index pool (trace chunks ∪ Azure heads), eager-loaded by the page. Used to
  // overlay per-method ranks onto the retrieved chunks and to seed the PoolSection.
  pool: LabelingPoolResponse | null;
  poolLoading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onToggleComplete: (complete: boolean) => void;
  onSetSlice: (slice: string | null) => void;
  onGrade: (testId: string, chunk: ChunkForLabeling, grade: number) => void;
}) {
  // chunk_id -> the heads that surfaced it and the rank it held in each, from the pool.
  const ranksByChunk = useMemo(() => {
    const m: Record<string, { provenance: string[]; ranks: Record<string, number> }> = {};
    for (const pc of pool?.chunks ?? []) {
      m[pc.chunk_id] = { provenance: pc.provenance, ranks: pc.ranks };
    }
    return m;
  }, [pool]);
  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30">
        <button
          onClick={onToggleCollapse}
          className="flex items-center gap-2 min-w-0 text-left"
        >
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
            {c.labeled_count}/{c.chunks.length} · {c.relevant_count} relevant
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
          {c.chunks.map((chunk) => {
            const pr = chunk.chunk_id ? ranksByChunk[chunk.chunk_id] : undefined;
            return (
              <ChunkRow
                key={`${chunk.chunk_id ?? "x"}-${chunk.rank}`}
                chunk={chunk}
                disabled={!canEdit}
                indexConnected={indexConnected}
                provenance={pr?.provenance}
                ranks={pr?.ranks}
                ranksLoading={poolLoading}
                onGrade={(grade) => onGrade(c.test_id, chunk, grade)}
              />
            );
          })}
          <PoolSection
            testId={c.test_id}
            canEdit={canEdit}
            indexConnected={indexConnected}
            initialPool={pool}
            traceChunkIds={
              new Set(c.chunks.map((ch) => ch.chunk_id).filter((id): id is string => !!id))
            }
          />
        </div>
      )}
    </div>
  );
}
