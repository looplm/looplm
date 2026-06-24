"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  getEvalRuns,
  getLabelingView,
  getChunkMetadata,
  getIndexProviders,
  saveChunkLabels,
  setLabelingComplete,
  type EvalRunListItem,
  type LabelingRunResponse,
  type LabelingCase,
  type ChunkForLabeling,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";

function ChunkMetadata({ chunkId }: { chunkId: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [fields, setFields] = useState<Record<string, unknown> | null>(null);
  const [loaded, setLoaded] = useState(false);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) {
      setLoading(true);
      getChunkMetadata(chunkId)
        .then((r) => setFields(r.fields ?? null))
        .catch(() => setFields(null))
        .finally(() => {
          setLoading(false);
          setLoaded(true);
        });
    }
  };

  return (
    <div className="mt-2">
      <button onClick={toggle} className="text-[11px] font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200">
        {open ? "Hide index fields" : "Index fields"}
      </button>
      {open && (
        <div className="mt-1.5 rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30 p-2.5">
          {loading ? (
            <p className="text-[11px] text-gray-400 dark:text-slate-500">Loading from index...</p>
          ) : !fields || Object.keys(fields).length === 0 ? (
            <p className="text-[11px] text-gray-400 dark:text-slate-500">
              This chunk was not found in the connected index.
            </p>
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
              {Object.entries(fields).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-gray-500 dark:text-slate-400 truncate">{k}</dt>
                  <dd className="text-gray-700 dark:text-slate-300 break-words">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
    </div>
  );
}

function ChunkRow({
  chunk,
  disabled,
  indexConnected,
  onLabel,
}: {
  chunk: ChunkForLabeling;
  disabled: boolean;
  indexConnected: boolean;
  onLabel: (relevant: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const labelable = !!chunk.chunk_id;
  const body = chunk.content || chunk.content_preview || "";
  const isLong = body.length > 240 || body.includes("\n");
  const docLabel = chunk.title || "source document";

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 border-b border-gray-50 dark:border-slate-800/50 ${
        chunk.relevant === true
          ? "bg-emerald-500/5"
          : chunk.relevant === false
            ? "bg-red-500/5"
            : ""
      }`}
    >
      <span className="shrink-0 w-6 text-right text-[11px] font-mono text-gray-400 dark:text-slate-500 pt-0.5">
        {chunk.rank}
      </span>

      <div className="min-w-0 flex-1">
        {/* Locator row: this is a chunk, and where it sits in the document */}
        <div className="flex items-center gap-2 flex-wrap mb-1.5">
          <span className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">
            Chunk
          </span>
          {chunk.heading_context && (
            <span className="text-[11px] text-gray-500 dark:text-slate-400 truncate" title={chunk.heading_context}>
              {chunk.heading_context}
            </span>
          )}
          {chunk.pdf_page_number != null && (
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
              PDF p.{chunk.pdf_page_number}
            </span>
          )}
          {chunk.score != null && (
            <span className="text-[10px] font-mono text-gray-400 dark:text-slate-500">
              score {chunk.score.toFixed(2)}
            </span>
          )}
        </div>

        {/* The chunk text: the thing being judged */}
        {body ? (
          <p
            className={`text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap ${
              expanded ? "" : "line-clamp-3"
            }`}
          >
            {body}
          </p>
        ) : (
          <p className="text-sm italic text-gray-400 dark:text-slate-500">No chunk text captured.</p>
        )}
        {isLong && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            {expanded ? "Show less" : "Show full chunk"}
          </button>
        )}

        {/* Secondary: link to the whole document, and the chunk id */}
        <div className="flex items-center gap-3 mt-2 text-[11px] text-gray-400 dark:text-slate-500">
          {chunk.url && (
            <a
              href={chunk.url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-gray-600 dark:hover:text-slate-300 hover:underline truncate max-w-[280px]"
              title={`Open document: ${docLabel}`}
            >
              Open document ↗
            </a>
          )}
          {chunk.chunk_id && <span className="font-mono truncate">{chunk.chunk_id}</span>}
          {chunk.relevant != null && chunk.labeled_by && (
            <span className="italic">by {chunk.labeled_by}</span>
          )}
        </div>

        {indexConnected && chunk.chunk_id && <ChunkMetadata chunkId={chunk.chunk_id} />}

        {!labelable && (
          <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
            No chunk id on this source, so it cannot be labeled yet (needs the rde-gpt chunk-id change deployed).
          </p>
        )}
      </div>

      <div className="shrink-0 flex items-center gap-1.5">
        <button
          disabled={disabled || !labelable}
          onClick={() => onLabel(true)}
          className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40 ${
            chunk.relevant === true
              ? "bg-emerald-500 border-emerald-500 text-white"
              : "border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-emerald-400"
          }`}
        >
          Relevant
        </button>
        <button
          disabled={disabled || !labelable}
          onClick={() => onLabel(false)}
          className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40 ${
            chunk.relevant === false
              ? "bg-red-500 border-red-500 text-white"
              : "border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-red-400"
          }`}
        >
          Not
        </button>
      </div>
    </div>
  );
}

function CaseCard({
  c,
  canEdit,
  indexConnected,
  collapsed,
  onToggleCollapse,
  onToggleComplete,
  onLabel,
}: {
  c: LabelingCase;
  canEdit: boolean;
  indexConnected: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onToggleComplete: (complete: boolean) => void;
  onLabel: (testId: string, chunk: ChunkForLabeling, relevant: boolean) => void;
}) {
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
          {c.chunks.map((chunk) => (
            <ChunkRow
              key={`${chunk.chunk_id ?? "x"}-${chunk.rank}`}
              chunk={chunk}
              disabled={!canEdit}
              indexConnected={indexConnected}
              onLabel={(relevant) => onLabel(c.test_id, chunk, relevant)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function LabelingPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("labeling");

  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [view, setView] = useState<LabelingRunResponse | null>(null);
  const [tab, setTab] = useState<"in_progress" | "complete">("in_progress");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [indexConnected, setIndexConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEvalRuns({ limit: "50" })
      .then((res) => setRuns(res.data))
      .catch(() => setRuns([]));
    getIndexProviders()
      .then((res) => setIndexConnected(res.data.length > 0))
      .catch(() => setIndexConnected(false));
  }, []);

  const load = useCallback((id: string | null) => {
    setLoading(true);
    setError(null);
    return getLabelingView(id ?? undefined)
      .then((v) => {
        setView(v);
        setCollapsed(new Set());
        if (!id && v.run_id) setRunId(v.run_id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

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
      // Collapse a case when it's marked complete to keep focus on remaining work.
      if (complete) setCollapsed((prev) => new Set(prev).add(testId));
      try {
        await setLabelingComplete(testId, complete);
      } catch {
        toast.error("Failed to update status");
        load(runId);
      }
    },
    [runId, load],
  );

  useEffect(() => {
    load(runId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Optimistic label: update local state, persist, roll back on error.
  const onLabel = useCallback(
    async (testId: string, chunk: ChunkForLabeling, relevant: boolean) => {
      if (!chunk.chunk_id) return;
      setView((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          cases: prev.cases.map((c) => {
            if (c.test_id !== testId) return c;
            const chunks = c.chunks.map((ch) =>
              ch.chunk_id === chunk.chunk_id ? { ...ch, relevant } : ch,
            );
            const labeled_count = chunks.filter((ch) => ch.relevant != null).length;
            const relevant_count = chunks.filter((ch) => ch.relevant === true).length;
            return { ...c, chunks, labeled_count, relevant_count };
          }),
        };
      });
      try {
        await saveChunkLabels([
          {
            test_id: testId,
            chunk_id: chunk.chunk_id,
            relevant,
            content_preview: chunk.content_preview,
            url: chunk.url,
            title: chunk.title,
          },
        ]);
      } catch {
        toast.error("Failed to save label");
        load(runId);
      }
    },
    [runId, load],
  );

  const progress = useMemo(() => {
    if (!view) return { labeled: 0, total: 0 };
    let labeled = 0;
    let total = 0;
    for (const c of view.cases) {
      labeled += c.labeled_count;
      total += c.chunks.filter((ch) => ch.chunk_id).length;
    }
    return { labeled, total };
  }, [view]);

  return (
    <div>
      <div className="flex items-center justify-between gap-4 mb-1">
        <h1 className="text-3xl font-bold">Labeling</h1>
        {runs.length > 0 && (
          <select
            value={runId ?? ""}
            onChange={(e) => setRunId(e.target.value || null)}
            className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[280px]"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        Judge the chunks each test case actually retrieved. Mark each one relevant or not;
        these labels become the ground truth for the chunk-level precision and recall on the
        Pipeline page. Labels are shared across runs, so you only judge a chunk once per query.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Loading retrieved chunks...
        </div>
      ) : !view || !view.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          No retrieved chunks captured for this run. Run an evaluation against the retrieval
          endpoint so its responses (with chunk ids) are captured, then come back to label.
        </div>
      ) : (
        <>
          <div className="flex items-center gap-3 mb-4 text-xs text-gray-400 dark:text-slate-500">
            <span>{progress.labeled} / {progress.total} chunks labeled</span>
            <div className="flex-1 max-w-[240px] h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500"
                style={{ width: `${progress.total ? (progress.labeled / progress.total) * 100 : 0}%` }}
              />
            </div>
            {!canEdit && <span className="text-amber-600 dark:text-amber-400">read-only access</span>}
            <div className="ml-auto flex items-center gap-3">
              <button onClick={collapseAll} className="hover:text-gray-600 dark:hover:text-slate-300">
                Collapse all
              </button>
              <button onClick={expandAll} className="hover:text-gray-600 dark:hover:text-slate-300">
                Expand all
              </button>
            </div>
          </div>

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
                        collapsed={collapsed.has(c.test_id)}
                        onToggleCollapse={() => toggleCase(c.test_id)}
                        onToggleComplete={(v) => onToggleComplete(c.test_id, v)}
                        onLabel={onLabel}
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
