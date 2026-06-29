"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  getLabelingView,
  getLabelingPool,
  getIndexProviders,
  setLabelingComplete,
  setLabelingSlice,
  saveChunkLabels,
  deleteChunkLabel,
  aiJudgeCase,
  type LabelingRunResponse,
  type LabelingPoolResponse,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { AgreementPanel } from "@/components/labeling/agreement-panel";
import { CaseCard } from "@/components/labeling/case-card";

// Compact "x ago" for the last-pooled timestamp. Falls back to the locale date past a week.
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days <= 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function LabelingPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("labeling");

  const [view, setView] = useState<LabelingRunResponse | null>(null);
  // The dataset the picker is on. Undefined until the first view resolves (backend picks the
  // most-recent dataset and tells us which); after that it's the explicit selection.
  const [datasetId, setDatasetId] = useState<string | undefined>(undefined);
  const [tab, setTab] = useState<"in_progress" | "complete">("in_progress");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [indexConnected, setIndexConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Each case's chunks ARE its index pool — eager-loaded per case and graded in place. Cached
  // server-side, so re-opening the page doesn't re-query the index.
  const [poolByCase, setPoolByCase] = useState<Record<string, LabelingPoolResponse>>({});
  const [poolLoading, setPoolLoading] = useState<Set<string>>(new Set());
  const poolRequested = useRef<Set<string>>(new Set());

  useEffect(() => {
    getIndexProviders()
      .then((res) => setIndexConnected(res.data.length > 0))
      .catch(() => setIndexConnected(false));
  }, []);

  // Load the labeling view for a dataset (or the most-recent one when unspecified).
  const load = useCallback((dsId?: string) => {
    setLoading(true);
    setError(null);
    return getLabelingView(dsId)
      .then((v) => {
        setView(v);
        setDatasetId(v.dataset_id ?? undefined);
        setCollapsed(new Set());
        // Fresh dataset: drop pools so they're re-fetched against the new cases.
        setPoolByCase({});
        setPoolLoading(new Set());
        poolRequested.current = new Set();
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(datasetId);
  }, [datasetId, load]);

  // Pool a set of cases through the index heads with bounded concurrency, writing each result
  // into poolByCase as it lands. ``refresh`` forces a server-side recompute (bypassing the cache).
  const loadPools = useCallback(
    async (testIds: string[], dsId: string | undefined, refresh: boolean) => {
      if (testIds.length === 0) return;
      setPoolLoading((prev) => new Set([...prev, ...testIds]));
      const settle = (id: string) =>
        setPoolLoading((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      let cursor = 0;
      const worker = async () => {
        while (cursor < testIds.length) {
          const testId = testIds[cursor++];
          try {
            const p = await getLabelingPool(testId, { datasetId: dsId, refresh });
            setPoolByCase((prev) => ({ ...prev, [testId]: p }));
          } catch {
            // Leave this case without a pool; it'll show as "no candidates".
          } finally {
            settle(testId);
          }
        }
      };
      const POOL_CONCURRENCY = 4;
      await Promise.all(Array.from({ length: Math.min(POOL_CONCURRENCY, testIds.length) }, worker));
    },
    [],
  );

  // Eager-pool every case once the view is in, so the chunks to judge appear without expanding.
  // The server-side pool cache makes repeat loads cheap. Skipped entirely with no index.
  useEffect(() => {
    if (!view?.available || !indexConnected) return;
    const todo = view.cases
      .filter((c) => !poolRequested.current.has(c.test_id))
      .map((c) => c.test_id);
    if (todo.length === 0) return;
    todo.forEach((id) => poolRequested.current.add(id));
    void loadPools(todo, view.dataset_id ?? undefined, false);
  }, [view, indexConnected, loadPools]);

  // Explicit recompute: re-pool every case against the index, bypassing the cache.
  const [recomputing, setRecomputing] = useState(false);
  const recomputePools = useCallback(async () => {
    if (!view) return;
    const ids = view.cases.map((c) => c.test_id);
    if (ids.length === 0) return;
    setRecomputing(true);
    try {
      await loadPools(ids, view.dataset_id ?? undefined, true);
    } finally {
      setRecomputing(false);
    }
  }, [view, loadPools]);

  // Oldest pool timestamp across loaded cases — the freshness floor shown on the page.
  const lastPooledAt = useMemo(() => {
    const times = Object.values(poolByCase)
      .map((p) => p.computed_at)
      .filter((t): t is string => !!t);
    return times.length ? times.reduce((a, b) => (a < b ? a : b)) : null;
  }, [poolByCase]);

  // Which index heads couldn't run (e.g. no vectorizer), aggregated across cases — so empty
  // pools are explainable: if a head is unavailable, it can't contribute candidates.
  const poolHeadsFailed = useMemo(() => {
    const failed: Record<string, string> = {};
    for (const p of Object.values(poolByCase)) {
      for (const [h, reason] of Object.entries(p.heads_failed)) if (!(h in failed)) failed[h] = reason;
    }
    return failed;
  }, [poolByCase]);

  const toggleCase = useCallback((testId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(testId)) next.delete(testId);
      else next.add(testId);
      return next;
    });
  }, []);

  const collapseAll = useCallback(() => {
    setCollapsed(new Set((view?.cases ?? []).map((c) => c.test_id)));
  }, [view]);

  const expandAll = useCallback(() => setCollapsed(new Set()), []);

  const onToggleComplete = useCallback(
    async (testId: string, complete: boolean) => {
      setView((prev) =>
        prev
          ? { ...prev, cases: prev.cases.map((c) => (c.test_id === testId ? { ...c, complete } : c)) }
          : prev,
      );
      if (complete) setCollapsed((prev) => new Set(prev).add(testId));
      try {
        await setLabelingComplete(testId, complete);
      } catch {
        toast.error("Failed to update status");
        load(datasetId);
      }
    },
    [load, datasetId],
  );

  const onSetSlice = useCallback(
    async (testId: string, slice: string | null) => {
      setView((prev) =>
        prev
          ? { ...prev, cases: prev.cases.map((c) => (c.test_id === testId ? { ...c, slice } : c)) }
          : prev,
      );
      try {
        await setLabelingSlice(testId, slice);
      } catch {
        toast.error("Failed to set slice");
        load(datasetId);
      }
    },
    [load, datasetId],
  );

  // Patch one pooled chunk's fields in place (optimistic grading / clearing / AI overlay).
  const patchPoolChunk = useCallback(
    (testId: string, chunkId: string, patch: Partial<PooledChunkForLabeling>) =>
      setPoolByCase((prev) => {
        const p = prev[testId];
        if (!p) return prev;
        return {
          ...prev,
          [testId]: {
            ...p,
            chunks: p.chunks.map((ch) => (ch.chunk_id === chunkId ? { ...ch, ...patch } : ch)),
          },
        };
      }),
    [],
  );

  // Optimistic graded label on a pooled chunk: update local state, persist, reload on error.
  const onGrade = useCallback(
    async (testId: string, chunk: PooledChunkForLabeling, relevance: number) => {
      patchPoolChunk(testId, chunk.chunk_id, { relevance });
      try {
        await saveChunkLabels([
          {
            test_id: testId,
            chunk_id: chunk.chunk_id,
            relevance,
            content_preview: chunk.content_preview,
            url: chunk.url,
            title: chunk.title,
          },
        ]);
      } catch {
        toast.error("Failed to save label");
        void loadPools([testId], view?.dataset_id ?? undefined, false);
      }
    },
    [patchPoolChunk, loadPools, view],
  );

  const onClearGrade = useCallback(
    async (testId: string, chunk: PooledChunkForLabeling) => {
      patchPoolChunk(testId, chunk.chunk_id, { relevance: null, labeled_by: null });
      try {
        await deleteChunkLabel(testId, chunk.chunk_id);
      } catch {
        toast.error("Failed to remove label");
        void loadPools([testId], view?.dataset_id ?? undefined, false);
      }
    },
    [patchPoolChunk, loadPools, view],
  );

  // Cases currently being graded by the AI judge (per-case spinner).
  const [aiJudging, setAiJudging] = useState<Set<string>>(new Set());

  // Run the AI judge over a case's pooled chunks, then fold the grades in as a read-only second
  // opinion (the human's own grades are untouched). "AI" joins the case's labelers.
  const onAiJudge = useCallback(
    async (testId: string) => {
      setAiJudging((prev) => new Set(prev).add(testId));
      try {
        const res = await aiJudgeCase(testId, { datasetId: view?.dataset_id ?? undefined });
        setPoolByCase((prev) => {
          const p = prev[testId];
          if (!p) return prev;
          return {
            ...prev,
            [testId]: {
              ...p,
              chunks: p.chunks.map((ch) =>
                ch.chunk_id in res.grades ? { ...ch, ai_relevance: res.grades[ch.chunk_id] } : ch,
              ),
            },
          };
        });
        setView((prev) =>
          prev
            ? {
                ...prev,
                cases: prev.cases.map((c) =>
                  c.test_id === testId && !c.labelers.includes("AI")
                    ? { ...c, labelers: [...c.labelers, "AI"] }
                    : c,
                ),
              }
            : prev,
        );
        toast.success(`AI judged ${res.judged} chunk${res.judged === 1 ? "" : "s"}`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "AI judge failed");
      } finally {
        setAiJudging((prev) => {
          const next = new Set(prev);
          next.delete(testId);
          return next;
        });
      }
    },
    [view],
  );

  // Progress: graded chunks over pooled chunks, across the pools loaded so far.
  const progress = useMemo(() => {
    let labeled = 0;
    let total = 0;
    for (const p of Object.values(poolByCase)) {
      total += p.chunks.length;
      labeled += p.chunks.filter((ch) => ch.relevance != null).length;
    }
    return { labeled, total };
  }, [poolByCase]);

  const datasets = view?.datasets ?? [];

  return (
    <div>
      <div className="flex items-center justify-between gap-4 mb-1">
        <h1 className="text-3xl font-bold">Labeling</h1>
        {datasets.length > 0 && (
          <select
            value={datasetId ?? ""}
            onChange={(e) => setDatasetId(e.target.value || undefined)}
            className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-sm"
            title="Dataset to label"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.test_count})
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        Judge the chunks your index retrieves for each test case in this dataset. Grade each one
        0 (irrelevant), 1 (marginally relevant), 2 (relevant), or 3 (highly relevant); these
        labels are the ground truth for the chunk-level precision, recall and nDCG on the Pipeline
        page (any grade ≥ 1 counts as relevant; nDCG weights by grade). Each case&apos;s candidates
        are pooled live from the connected index (BM25/vector/hybrid); use the search box on a case
        to pull in more.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {indexConnected === false && !loading && (
        <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-600 dark:text-amber-400 text-sm">
          No index provider is connected. Connect one in Settings → Integrations so candidate
          chunks can be pooled from the index for each query.
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Loading test cases...
        </div>
      ) : datasets.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          No datasets yet. Create a dataset (Datasets) with the queries you want to label, then
          come back here.
        </div>
      ) : !view || !view.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          This dataset has no test cases. Add some in Datasets, then come back to label.
        </div>
      ) : (
        <>
          <div className="flex items-center gap-3 mb-4 text-xs text-gray-400 dark:text-slate-500">
            <span>{progress.labeled} / {progress.total} pooled chunks labeled</span>
            <div className="flex-1 max-w-[240px] h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500"
                style={{ width: `${progress.total ? (progress.labeled / progress.total) * 100 : 0}%` }}
              />
            </div>
            {!canEdit && <span className="text-amber-600 dark:text-amber-400">read-only access</span>}
            <div className="ml-auto flex items-center gap-3">
              {indexConnected && (
                <div className="flex items-center gap-2">
                  <span title="Candidates are pooled live from the index. Shows the oldest pool across cases.">
                    {poolLoading.size > 0
                      ? "Pooling…"
                      : lastPooledAt
                        ? `Pooled ${relativeTime(lastPooledAt)}`
                        : "Not pooled"}
                  </span>
                  {Object.keys(poolHeadsFailed).length > 0 && (
                    <span
                      className="text-amber-600 dark:text-amber-400"
                      title={Object.entries(poolHeadsFailed)
                        .map(([h, r]) => `${h}: ${r}`)
                        .join("\n")}
                    >
                      {Object.keys(poolHeadsFailed).join(", ")} unavailable
                    </span>
                  )}
                  <button
                    onClick={recomputePools}
                    disabled={recomputing || poolLoading.size > 0}
                    title="Re-query the index for every case, bypassing the cache. Use after re-indexing."
                    className="px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
                  >
                    {recomputing ? "Recomputing…" : "Recompute"}
                  </button>
                </div>
              )}
              <button onClick={collapseAll} className="hover:text-gray-600 dark:hover:text-slate-300">
                Collapse all
              </button>
              <button onClick={expandAll} className="hover:text-gray-600 dark:hover:text-slate-300">
                Expand all
              </button>
            </div>
          </div>

          <AgreementPanel canEdit={canEdit} />

          {(() => {
            const inProgress = view.cases.filter((c) => !c.complete);
            const complete = view.cases.filter((c) => c.complete);
            const active = tab === "in_progress" ? inProgress : complete;
            const tabs = [
              { key: "in_progress" as const, label: "In progress", count: inProgress.length },
              { key: "complete" as const, label: "Complete", count: complete.length },
            ];
            return (
              <>
                <div className="flex items-center gap-1 mb-4 border-b border-gray-100 dark:border-slate-800">
                  {tabs.map((t) => (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                        tab === t.key
                          ? "border-indigo-500 text-gray-900 dark:text-white"
                          : "border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                      }`}
                    >
                      {t.label}
                      <span className="ml-1.5 text-xs text-gray-400 dark:text-slate-500">{t.count}</span>
                    </button>
                  ))}
                </div>

                {active.length > 0 ? (
                  <div className="space-y-4">
                    {active.map((c) => (
                      <CaseCard
                        key={c.test_id}
                        c={c}
                        canEdit={canEdit}
                        indexConnected={indexConnected}
                        datasetId={view.dataset_id ?? undefined}
                        pool={poolByCase[c.test_id] ?? null}
                        poolLoading={poolLoading.has(c.test_id)}
                        collapsed={collapsed.has(c.test_id)}
                        onToggleCollapse={() => toggleCase(c.test_id)}
                        onToggleComplete={(v) => onToggleComplete(c.test_id, v)}
                        onSetSlice={(s) => onSetSlice(c.test_id, s)}
                        onGrade={onGrade}
                        onClearGrade={onClearGrade}
                        onAiJudge={() => onAiJudge(c.test_id)}
                        aiJudging={aiJudging.has(c.test_id)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 dark:text-slate-500">
                    {tab === "in_progress"
                      ? "All cases are marked complete."
                      : "No cases marked complete yet."}
                  </p>
                )}
              </>
            );
          })()}
        </>
      )}
    </div>
  );
}
