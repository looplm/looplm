"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import {
  getLabelingPool,
  saveChunkLabels,
  deleteChunkLabel,
  type LabelingPoolResponse,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { PoolChunkRow } from "./pool-chunk-row";

// Manual "find more candidates" tool: search the connected index with a custom query to surface
// chunks beyond the case's auto-pool (already shown above). Self-contained — it owns its labels
// optimistically; graded candidates persist by (test_id, chunk_id) like any other label.
export function PoolSection({
  testId,
  datasetId,
  canEdit,
  indexConnected,
  alreadyShownIds,
}: {
  testId: string;
  datasetId?: string;
  canEdit: boolean;
  indexConnected: boolean;
  // Chunk ids already rendered in the case's auto-pool, filtered out of search results so this
  // section only surfaces genuinely new candidates.
  alreadyShownIds: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const [pool, setPool] = useState<LabelingPoolResponse | null>(null);
  const [q, setQ] = useState("");
  const [searching, setSearching] = useState(false);
  // chunk_id -> graded relevance 0..3 (or null when cleared) the user assigned (optimistic).
  const [labels, setLabels] = useState<Record<string, number | null>>({});

  const search = useCallback(
    (query: string) => {
      setSearching(true);
      return getLabelingPool(testId, { datasetId, q: query })
        .then((p) => setPool(p))
        .catch(() => toast.error("Search failed"))
        .finally(() => setSearching(false));
    },
    [testId, datasetId],
  );

  const restoreLabel = (chunkId: string, prev: number | null | undefined) =>
    setLabels((m) => {
      const next = { ...m };
      if (prev === undefined) delete next[chunkId];
      else next[chunkId] = prev;
      return next;
    });

  const onGrade = (chunk: PooledChunkForLabeling, relevance: number) => {
    const prev = labels[chunk.chunk_id];
    setLabels((m) => ({ ...m, [chunk.chunk_id]: relevance }));
    saveChunkLabels([
      {
        test_id: testId,
        chunk_id: chunk.chunk_id,
        relevance,
        content_preview: chunk.content_preview,
        url: chunk.url,
        title: chunk.title,
      },
    ]).catch(() => {
      toast.error("Failed to save label");
      restoreLabel(chunk.chunk_id, prev);
    });
  };

  const onClear = (chunk: PooledChunkForLabeling) => {
    const prev = labels[chunk.chunk_id];
    setLabels((m) => ({ ...m, [chunk.chunk_id]: null }));
    deleteChunkLabel(testId, chunk.chunk_id).catch(() => {
      toast.error("Failed to remove label");
      restoreLabel(chunk.chunk_id, prev);
    });
  };

  // Only candidates not already shown in the case's auto-pool.
  const candidates = (pool?.chunks ?? []).filter((c) => !alreadyShownIds.has(c.chunk_id));

  if (!indexConnected) return null;

  return (
    <div className="border-t border-dashed border-gray-200 dark:border-slate-700/60">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-[12px] font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
      >
        <span>{open ? "▾" : "▸"}</span>
        Search the index for more candidates
        {pool && open && (
          <span className="text-[11px] font-normal text-gray-400 dark:text-slate-500">
            · {candidates.length} new
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-3">
          <div className="flex items-center gap-2 mb-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && q.trim() && search(q.trim())}
              placeholder="Search the index for more candidates (BM25 / vector / hybrid)…"
              className="flex-1 text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5"
            />
            <button
              disabled={!q.trim() || searching}
              onClick={() => q.trim() && search(q.trim())}
              className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
            >
              {searching ? "…" : "Search"}
            </button>
          </div>

          {pool && (
            <p className="text-[11px] text-gray-400 dark:text-slate-500 mb-2">
              Heads: {pool.heads_ran.join(", ") || "none"}
              {Object.keys(pool.heads_failed).length > 0 &&
                ` · unavailable: ${Object.keys(pool.heads_failed).join(", ")}`}
            </p>
          )}

          {searching ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-2">Searching…</p>
          ) : pool && candidates.length === 0 ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-2">
              No new candidates beyond those already listed above.
            </p>
          ) : candidates.length > 0 ? (
            <div className="rounded-lg border border-gray-100 dark:border-slate-800 overflow-hidden">
              {candidates.map((chunk) => (
                <PoolChunkRow
                  key={chunk.chunk_id}
                  chunk={chunk}
                  relevance={
                    chunk.chunk_id in labels ? labels[chunk.chunk_id] : chunk.relevance ?? null
                  }
                  disabled={!canEdit}
                  indexConnected={indexConnected}
                  onGrade={(grade) => onGrade(chunk, grade)}
                  onClear={() => onClear(chunk)}
                />
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
