"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
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
  planCaseQueries,
  getLabelingPrompts,
  type LabelingRunResponse,
  type LabelingPoolResponse,
  type LabelingPromptDefaults,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { WorkbenchView } from "@/components/labeling/workbench-view";

export default function LabelingWorkbenchPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("labeling");
  const router = useRouter();
  const params = useParams<{ testId: string }>();
  const searchParams = useSearchParams();
  const testId = decodeURIComponent(params.testId);
  const datasetId = searchParams.get("dataset") ?? undefined;

  const [view, setView] = useState<LabelingRunResponse | null>(null);
  const [pool, setPool] = useState<LabelingPoolResponse | null>(null);
  const [indexConnected, setIndexConnected] = useState(false);
  const [poolLoading, setPoolLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [promptDefaults, setPromptDefaults] = useState<LabelingPromptDefaults | null>(null);
  const [aiJudging, setAiJudging] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [recomputing, setRecomputing] = useState(false);

  useEffect(() => {
    getIndexProviders()
      .then((res) => setIndexConnected(res.data.length > 0))
      .catch(() => setIndexConnected(false));
    getLabelingPrompts()
      .then(setPromptDefaults)
      .catch(() => setPromptDefaults(null));
  }, []);

  // The view gives the ordered case list (for prev/next nav) and this case's tallies/status.
  useEffect(() => {
    setLoading(true);
    setError(null);
    getLabelingView(datasetId)
      .then(setView)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // Pool this one case's chunks. ``refresh`` bypasses the server-side cache.
  const loadPool = useCallback(
    (refresh: boolean) => {
      if (!indexConnected) {
        setPoolLoading(false);
        return Promise.resolve();
      }
      setPoolLoading(true);
      return getLabelingPool(testId, { datasetId, refresh })
        .then(setPool)
        .catch(() => setPool(null))
        .finally(() => setPoolLoading(false));
    },
    [testId, datasetId, indexConnected],
  );

  useEffect(() => {
    void loadPool(false);
  }, [loadPool]);

  const c = useMemo(
    () => view?.cases.find((x) => x.test_id === testId) ?? null,
    [view, testId],
  );

  // Prev/next within the dataset's case order, for keyboard + button navigation.
  const nav = useMemo(() => {
    const cases = view?.cases ?? [];
    const idx = cases.findIndex((x) => x.test_id === testId);
    const href = (id: string) =>
      `/labeling/${encodeURIComponent(id)}${datasetId ? `?dataset=${encodeURIComponent(datasetId)}` : ""}`;
    return {
      idx,
      total: cases.length,
      prev: idx > 0 ? href(cases[idx - 1].test_id) : null,
      next: idx >= 0 && idx < cases.length - 1 ? href(cases[idx + 1].test_id) : null,
    };
  }, [view, testId, datasetId]);

  // n / p jump to the adjacent question (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable))
        return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "n" && nav.next) router.push(nav.next);
      else if (e.key === "p" && nav.prev) router.push(nav.prev);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav, router]);

  const patchChunk = useCallback(
    (chunkId: string, patch: Partial<PooledChunkForLabeling>) =>
      setPool((prev) =>
        prev
          ? { ...prev, chunks: prev.chunks.map((ch) => (ch.chunk_id === chunkId ? { ...ch, ...patch } : ch)) }
          : prev,
      ),
    [],
  );

  const onGrade = useCallback(
    async (tid: string, chunk: PooledChunkForLabeling, relevance: number) => {
      patchChunk(chunk.chunk_id, { relevance });
      try {
        await saveChunkLabels([
          {
            test_id: tid,
            chunk_id: chunk.chunk_id,
            relevance,
            content_preview: chunk.content_preview,
            url: chunk.url,
            title: chunk.title,
          },
        ]);
      } catch {
        toast.error("Failed to save label");
        void loadPool(false);
      }
    },
    [patchChunk, loadPool],
  );

  const onClearGrade = useCallback(
    async (tid: string, chunk: PooledChunkForLabeling) => {
      patchChunk(chunk.chunk_id, { relevance: null, labeled_by: null });
      try {
        await deleteChunkLabel(tid, chunk.chunk_id);
      } catch {
        toast.error("Failed to remove label");
        void loadPool(false);
      }
    },
    [patchChunk, loadPool],
  );

  const onToggleComplete = useCallback(
    async (complete: boolean) => {
      setView((prev) =>
        prev
          ? { ...prev, cases: prev.cases.map((x) => (x.test_id === testId ? { ...x, complete } : x)) }
          : prev,
      );
      try {
        await setLabelingComplete(testId, complete);
      } catch {
        toast.error("Failed to update status");
      }
    },
    [testId],
  );

  const onSetSlice = useCallback(
    async (slice: string | null) => {
      setView((prev) =>
        prev
          ? { ...prev, cases: prev.cases.map((x) => (x.test_id === testId ? { ...x, slice } : x)) }
          : prev,
      );
      try {
        await setLabelingSlice(testId, slice);
        // Slice changes the pool depth, so re-pool at the new depth.
        void loadPool(false);
      } catch {
        toast.error("Failed to set slice");
      }
    },
    [testId, loadPool],
  );

  const onRecompute = useCallback(async () => {
    setRecomputing(true);
    try {
      await loadPool(true);
    } finally {
      setRecomputing(false);
    }
  }, [loadPool]);

  const onAiJudge = useCallback(
    async (instructions?: string) => {
      setAiJudging(true);
      try {
        const res = await aiJudgeCase(testId, { datasetId, instructions });
        setPool((prev) =>
          prev
            ? {
                ...prev,
                chunks: prev.chunks.map((ch) =>
                  ch.chunk_id in res.grades ? { ...ch, ai_relevance: res.grades[ch.chunk_id] } : ch,
                ),
              }
            : prev,
        );
        setView((prev) =>
          prev
            ? {
                ...prev,
                cases: prev.cases.map((x) =>
                  x.test_id === testId && !x.labelers.includes("AI")
                    ? { ...x, labelers: [...x.labelers, "AI"] }
                    : x,
                ),
              }
            : prev,
        );
        toast.success(`AI judged ${res.judged} chunk${res.judged === 1 ? "" : "s"}`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "AI judge failed");
      } finally {
        setAiJudging(false);
      }
    },
    [testId, datasetId],
  );

  const onPlan = useCallback(
    async (instructions?: string) => {
      setPlanning(true);
      try {
        const res = await planCaseQueries(testId, { datasetId, instructions });
        await loadPool(false);
        toast.success(
          res.agentic.length > 0
            ? `Planned ${res.agentic.length} agentic quer${res.agentic.length === 1 ? "y" : "ies"}`
            : "No agentic queries were planned for this case",
        );
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Query planning failed");
      } finally {
        setPlanning(false);
      }
    },
    [testId, datasetId, loadPool],
  );

  const backHref = `/labeling${datasetId ? `?dataset=${encodeURIComponent(datasetId)}` : ""}`;

  return (
    // Fill the scroll area and lay out as a column so the top bar + workbench header stay put and
    // only the chunk list scrolls (see WorkbenchView). ``min-h-0`` lets the inner list shrink to
    // enable its own overflow.
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-4 mb-4 flex-none">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
        >
          <span aria-hidden>←</span> All questions
        </Link>
        <div className="flex items-center gap-3 text-sm">
          {nav.idx >= 0 && nav.total > 0 && (
            <span className="text-gray-400 dark:text-slate-500">
              {nav.idx + 1} / {nav.total}
            </span>
          )}
          <div className="flex items-center gap-1.5">
            {nav.prev ? (
              <Link
                href={nav.prev}
                title="Previous question (p)"
                className="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400"
              >
                ← Prev
              </Link>
            ) : (
              <span className="px-2.5 py-1 rounded-lg border border-gray-100 dark:border-slate-800 text-gray-300 dark:text-slate-700">
                ← Prev
              </span>
            )}
            {nav.next ? (
              <Link
                href={nav.next}
                title="Next question (n)"
                className="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400"
              >
                Next →
              </Link>
            ) : (
              <span className="px-2.5 py-1 rounded-lg border border-gray-100 dark:border-slate-800 text-gray-300 dark:text-slate-700">
                Next →
              </span>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm flex-none">
          {error}
        </div>
      )}

      {indexConnected === false && !loading && (
        <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-600 dark:text-amber-400 text-sm flex-none">
          No index provider is connected. Connect one in Settings → Integrations so candidate chunks
          can be pooled for this query.
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Loading question…
        </div>
      ) : !c ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          This question is not in the selected dataset.{" "}
          <Link href={backHref} className="text-indigo-500 hover:underline">
            Back to all questions
          </Link>
          .
        </div>
      ) : (
        <WorkbenchView
          c={c}
          canEdit={canEdit}
          indexConnected={indexConnected}
          datasetId={view?.dataset_id ?? datasetId}
          pool={pool}
          poolLoading={poolLoading}
          recomputing={recomputing}
          onRecompute={onRecompute}
          onToggleComplete={onToggleComplete}
          onSetSlice={onSetSlice}
          onGrade={onGrade}
          onClearGrade={onClearGrade}
          onAiJudge={onAiJudge}
          aiJudging={aiJudging}
          onPlan={onPlan}
          planning={planning}
          promptDefaults={promptDefaults}
        />
      )}
    </div>
  );
}
