"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  getLabelingPool,
  saveChunkLabels,
  type LabelingPoolResponse,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { PoolChunkRow } from "./pool-chunk-row";

// Per-case pool augmentation: union the case's retrieved chunks with fresh candidates from the
// connected index (BM25/vector/hybrid), so a labeler can judge relevant chunks the system
// missed. Also hosts the manual "search the index" box. Self-contained: it owns its labels
// optimistically (pooled candidates aren't part of the trace-based case counts).
export function PoolSection({
  testId,
  canEdit,
  indexConnected,
  initialPool,
  traceChunkIds,
}: {
  testId: string;
  canEdit: boolean;
  indexConnected: boolean;
  // Pool already fetched by the page (auto query). Adopted as-is so opening this section
  // doesn't re-hit the index; a manual search still re-queries.
  initialPool: LabelingPoolResponse | null;
  traceChunkIds: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">(
    initialPool ? "loaded" : "idle",
  );
  const [pool, setPool] = useState<LabelingPoolResponse | null>(initialPool);
  const [q, setQ] = useState("");
  const [searching, setSearching] = useState(false);
  // chunk_id -> graded relevance 0..3 the user assigned to a pooled candidate (optimistic).
  const [labels, setLabels] = useState<Record<string, number>>({});

  // Adopt the page's pool once it arrives, as long as we haven't run our own (manual) search.
  useEffect(() => {
    if (initialPool && state === "idle") {
      setPool(initialPool);
      setState("loaded");
    }
  }, [initialPool, state]);

  const load = useCallback(
    (query?: string) => {
      const busy = query !== undefined;
      if (busy) setSearching(true);
      else setState("loading");
      return getLabelingPool(testId, { q: query })
        .then((p) => {
          setPool(p);
          setState("loaded");
        })
        .catch(() => setState("error"))
        .finally(() => busy && setSearching(false));
    },
    [testId],
  );

  const onToggle = () => {
    const next = !open;
    setOpen(next);
    if (next && state === "idle") load();
  };

  const onGradePool = (chunk: PooledChunkForLabeling, relevance: number) => {
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
      setLabels((m) => {
        const next = { ...m };
        if (prev == null) delete next[chunk.chunk_id];
        else next[chunk.chunk_id] = prev;
        return next;
      });
    });
  };

  // Show only candidates not already listed above as retrieved chunks.
  const candidates = (pool?.chunks ?? []).filter((c) => !traceChunkIds.has(c.chunk_id));

  return (
    <div className="border-t border-dashed border-gray-200 dark:border-slate-700/60">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-[12px] font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
      >
        <span>{open ? "▾" : "▸"}</span>
        Find more candidates from the index
        {pool && open && (
          <span className="text-[11px] font-normal text-gray-400 dark:text-slate-500">
            · pooled {pool.pool_size}, {candidates.length} new
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-3">
          {!indexConnected ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-2">
              Connect an index provider (Settings → Integrations) to pool BM25/vector/hybrid
              candidates the system may have missed.
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-2">
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && q.trim() && load(q.trim())}
                  placeholder="Search the index for more candidates (BM25 / vector / hybrid)…"
                  className="flex-1 text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5"
                />
                <button
                  disabled={!q.trim() || searching}
                  onClick={() => q.trim() && load(q.trim())}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
                >
                  {searching ? "…" : "Search"}
                </button>
                {q && (
                  <button
                    onClick={() => {
                      setQ("");
                      load();
                    }}
                    className="text-[12px] text-gray-400 hover:text-gray-600 dark:hover:text-slate-300"
                  >
                    Reset
                  </button>
                )}
              </div>

              {pool && (
                <p className="text-[11px] text-gray-400 dark:text-slate-500 mb-2">
                  Heads: {pool.heads_ran.join(", ") || "none"}
                  {Object.keys(pool.heads_failed).length > 0 &&
                    ` · unavailable: ${Object.keys(pool.heads_failed).join(", ")}`}
                </p>
              )}

              {state === "loading" ? (
                <p className="text-[12px] text-gray-400 dark:text-slate-500 py-2">Pooling candidates…</p>
              ) : state === "error" ? (
                <p className="text-[12px] text-red-500 py-2">Failed to load the pool.</p>
              ) : candidates.length === 0 ? (
                <p className="text-[12px] text-gray-400 dark:text-slate-500 py-2">
                  No additional candidates beyond what was already retrieved.
                </p>
              ) : (
                <div className="rounded-lg border border-gray-100 dark:border-slate-800 overflow-hidden">
                  {candidates.map((chunk) => (
                    <PoolChunkRow
                      key={chunk.chunk_id}
                      chunk={chunk}
                      relevance={labels[chunk.chunk_id] ?? chunk.relevance ?? null}
                      disabled={!canEdit}
                      indexConnected={indexConnected}
                      onGrade={(grade) => onGradePool(chunk, grade)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
