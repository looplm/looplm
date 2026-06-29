"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  getLabelingView,
  getLabelingPool,
  getChunkMetadata,
  getIndexProviders,
  getAgreement,
  setGold,
  saveChunkLabels,
  setLabelingComplete,
  setLabelingSlice,
  type LabelingRunResponse,
  type LabelingCase,
  type LabelingPoolResponse,
  type ChunkForLabeling,
  type PooledChunkForLabeling,
  type AgreementReport,
  type Disagreement,
} from "@/lib/api";

// Risk slices a test case can be assigned to (matches the API's SLICE_VALUES).
const SLICES = ["broad", "safety", "adversarial"] as const;

const SLICE_BADGE: Record<string, string> = {
  safety: "bg-red-500/10 text-red-600 dark:text-red-300 border-red-500/30",
  adversarial: "bg-orange-500/10 text-orange-600 dark:text-orange-300 border-orange-500/30",
  broad: "bg-slate-500/10 text-slate-600 dark:text-slate-300 border-slate-500/20",
};
import { usePermissions } from "@/components/permissions-context";

// Index fields that hold the chunk's full text, in priority order.
const INDEX_TEXT_FIELDS = ["chunk_text", "content", "text", "chunkText"];

function pickIndexText(fields: Record<string, unknown> | null): string | null {
  if (!fields) return null;
  for (const k of INDEX_TEXT_FIELDS) {
    const v = fields[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

// Graded relevance scale (TREC-style): 0 irrelevant … 3 highly relevant. Any grade >= 1
// counts as relevant for the set-based metrics; nDCG uses the grade as gain.
const GRADES: { value: number; label: string; selected: string; hover: string }[] = [
  { value: 0, label: "Irrelevant", selected: "bg-red-500 border-red-500 text-white", hover: "hover:border-red-400" },
  { value: 1, label: "Marginally relevant", selected: "bg-amber-500 border-amber-500 text-white", hover: "hover:border-amber-400" },
  { value: 2, label: "Relevant", selected: "bg-emerald-500 border-emerald-500 text-white", hover: "hover:border-emerald-400" },
  { value: 3, label: "Highly relevant", selected: "bg-emerald-600 border-emerald-600 text-white", hover: "hover:border-emerald-500" },
];

function gradeLabel(grade: number): string {
  return GRADES.find((g) => g.value === grade)?.label ?? String(grade);
}

// Row background tint by grade: irrelevant red, any-relevant emerald, unjudged none.
function gradeTint(grade: number | null | undefined): string {
  if (grade == null) return "";
  return grade >= 1 ? "bg-emerald-500/5" : "bg-red-500/5";
}

// Four-button 0..3 relevance picker, shared by retrieved rows, pooled candidates and adjudication.
function GradeSelector({
  value,
  disabled,
  onSelect,
}: {
  value: number | null;
  disabled: boolean;
  onSelect: (grade: number) => void;
}) {
  return (
    <div className="shrink-0 flex items-center gap-1" role="group" aria-label="Relevance grade">
      {GRADES.map((g) => (
        <button
          key={g.value}
          disabled={disabled}
          onClick={() => onSelect(g.value)}
          title={`${g.value} — ${g.label}`}
          className={`w-7 h-7 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-40 ${
            value === g.value
              ? g.selected
              : `border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 ${g.hover}`
          }`}
        >
          {g.value}
        </button>
      ))}
    </div>
  );
}

function ChunkRow({
  chunk,
  disabled,
  indexConnected,
  provenance,
  ranks,
  ranksLoading,
  onGrade,
}: {
  chunk: ChunkForLabeling;
  disabled: boolean;
  indexConnected: boolean;
  // Per-method ranks for this chunk, sourced live from the index heads (Azure AI Search):
  // which heads surfaced it and the rank it held in each. "trace" is omitted by the caller
  // since the left-margin number already shows the final retrieved rank.
  provenance?: string[];
  ranks?: Record<string, number>;
  ranksLoading?: boolean;
  onGrade: (grade: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showMeta, setShowMeta] = useState(false);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [docState, setDocState] = useState<"idle" | "loading" | "loaded">("idle");

  const labelable = !!chunk.chunk_id;
  const docLabel = chunk.title || "source document";
  const traceText = chunk.content || chunk.content_preview || "";
  const indexText = pickIndexText(doc);
  // The index holds the authoritative, untruncated chunk; the trace copy can be cut off.
  const fullText = indexText ?? traceText;
  const collapsedText = traceText || indexText || "";
  const canFetchIndex = indexConnected && !!chunk.chunk_id;
  const isLong = traceText.length > 240 || traceText.includes("\n") || canFetchIndex;

  const loadDoc = () => {
    if (docState !== "idle" || !canFetchIndex || !chunk.chunk_id) return;
    setDocState("loading");
    getChunkMetadata(chunk.chunk_id)
      .then((r) => setDoc(r.fields ?? null))
      .catch(() => setDoc(null))
      .finally(() => setDocState("loaded"));
  };

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 border-b border-gray-50 dark:border-slate-800/50 ${gradeTint(
        chunk.relevance,
      )}`}
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
          {/* Per-method ranks from the index heads (Azure AI Search): where BM25/vector/hybrid
              each ranked this chunk. "trace" is excluded — the left-margin number already shows
              the final retrieved rank. */}
          {provenance && provenance.some((p) => p !== "trace") ? (
            <ProvenanceBadges provenance={provenance.filter((p) => p !== "trace")} ranks={ranks} />
          ) : ranksLoading ? (
            <span className="text-[9px] uppercase tracking-wide text-gray-400 dark:text-slate-500 animate-pulse">
              ranking…
            </span>
          ) : indexConnected && provenance ? (
            <span
              className="text-[9px] uppercase tracking-wide text-gray-400 dark:text-slate-500"
              title="No index head (BM25/vector/hybrid) ranked this chunk within the pooled depth"
            >
              not pooled
            </span>
          ) : null}
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

        {/* The chunk text: the thing being judged. Expanded view prefers the index copy. */}
        {expanded ? (
          docState === "loading" ? (
            <p className="text-sm italic text-gray-400 dark:text-slate-500">Loading full chunk from index...</p>
          ) : fullText ? (
            <p className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
              {fullText}
            </p>
          ) : (
            <p className="text-sm italic text-gray-400 dark:text-slate-500">No chunk text available.</p>
          )
        ) : collapsedText ? (
          <p className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap line-clamp-3">
            {collapsedText}
          </p>
        ) : (
          <p className="text-sm italic text-gray-400 dark:text-slate-500">No chunk text captured.</p>
        )}

        <div className="flex items-center gap-3 mt-1">
          {isLong && (
            <button
              onClick={() => {
                const next = !expanded;
                setExpanded(next);
                if (next) loadDoc();
              }}
              className="text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {expanded ? "Show less" : "Show full chunk"}
            </button>
          )}
          {expanded && indexText && (
            <span className="text-[10px] text-gray-400 dark:text-slate-500">full text from index</span>
          )}
        </div>

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
          {chunk.relevance != null && chunk.labeled_by && (
            <span className="italic">by {chunk.labeled_by}</span>
          )}
        </div>

        {canFetchIndex && (
          <div className="mt-2">
            <button
              onClick={() => {
                setShowMeta((v) => !v);
                loadDoc();
              }}
              className="text-[11px] font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
            >
              {showMeta ? "Hide index fields" : "Index fields"}
            </button>
            {showMeta && (
              <div className="mt-1.5 rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30 p-2.5">
                {docState === "loading" ? (
                  <p className="text-[11px] text-gray-400 dark:text-slate-500">Loading from index...</p>
                ) : !doc || Object.keys(doc).length === 0 ? (
                  <p className="text-[11px] text-gray-400 dark:text-slate-500">
                    This chunk was not found in the connected index.
                  </p>
                ) : (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                    {Object.entries(doc).map(([k, v]) => (
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
        )}

        {!labelable && (
          <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
            No chunk id on this source, so it cannot be labeled yet (needs the rde-gpt chunk-id change deployed).
          </p>
        )}
      </div>

      <GradeSelector
        value={chunk.relevance ?? null}
        disabled={disabled || !labelable}
        onSelect={onGrade}
      />
    </div>
  );
}

// Provenance badge per retrieval head — tells the labeler *why* a chunk is in the pool.
const PROVENANCE_BADGES: Record<string, { label: string; cls: string }> = {
  trace: { label: "Retrieved", cls: "bg-slate-500/10 text-slate-600 dark:text-slate-300" },
  keyword: { label: "BM25", cls: "bg-amber-500/10 text-amber-600 dark:text-amber-300" },
  vector: { label: "Vector", cls: "bg-violet-500/10 text-violet-600 dark:text-violet-300" },
  hybrid: { label: "Hybrid", cls: "bg-teal-500/10 text-teal-600 dark:text-teal-300" },
};

// Each badge shows the head and, when known, the rank the chunk held in that head — so the
// labeler sees both *why* a chunk is pooled and *where* each method ranked it (e.g. "Vector #3").
function ProvenanceBadges({
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

// A pooled candidate chunk (from an index search head). Lighter than ChunkRow — no rank or
// document locators — but judgeable the same way, with provenance badges and full-text fetch.
function PoolChunkRow({
  chunk,
  relevance,
  disabled,
  indexConnected,
  onGrade,
}: {
  chunk: PooledChunkForLabeling;
  relevance: number | null;
  disabled: boolean;
  indexConnected: boolean;
  onGrade: (grade: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [docState, setDocState] = useState<"idle" | "loading" | "loaded">("idle");

  const previewText = chunk.content_preview || "";
  const indexText = pickIndexText(doc);
  const fullText = indexText ?? previewText;
  const canFetchIndex = indexConnected && !!chunk.chunk_id;
  const isLong = previewText.length > 240 || previewText.includes("\n") || canFetchIndex;

  const loadDoc = () => {
    if (docState !== "idle" || !canFetchIndex) return;
    setDocState("loading");
    getChunkMetadata(chunk.chunk_id)
      .then((r) => setDoc(r.fields ?? null))
      .catch(() => setDoc(null))
      .finally(() => setDocState("loaded"));
  };

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 border-b border-gray-50 dark:border-slate-800/50 ${gradeTint(
        relevance,
      )}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap mb-1.5">
          <ProvenanceBadges provenance={chunk.provenance} ranks={chunk.ranks} />
          {chunk.score != null && (
            <span className="text-[10px] font-mono text-gray-400 dark:text-slate-500">
              score {chunk.score.toFixed(2)}
            </span>
          )}
        </div>

        {expanded && docState === "loading" ? (
          <p className="text-sm italic text-gray-400 dark:text-slate-500">
            Loading full chunk from index...
          </p>
        ) : (expanded ? fullText : previewText) ? (
          <p
            className={`text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap ${
              expanded ? "" : "line-clamp-3"
            }`}
          >
            {expanded ? fullText : previewText}
          </p>
        ) : (
          <p className="text-sm italic text-gray-400 dark:text-slate-500">No chunk text.</p>
        )}

        <div className="flex items-center gap-3 mt-1 text-[11px] text-gray-400 dark:text-slate-500">
          {isLong && (
            <button
              onClick={() => {
                const next = !expanded;
                setExpanded(next);
                if (next) loadDoc();
              }}
              className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {expanded ? "Show less" : "Show full chunk"}
            </button>
          )}
          {chunk.url && (
            <a
              href={chunk.url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-gray-600 dark:hover:text-slate-300 hover:underline truncate max-w-[240px]"
            >
              Open document ↗
            </a>
          )}
          <span className="font-mono truncate">{chunk.chunk_id}</span>
          {relevance != null && chunk.labeled_by && <span className="italic">by {chunk.labeled_by}</span>}
        </div>
      </div>

      <GradeSelector value={relevance} disabled={disabled} onSelect={onGrade} />
    </div>
  );
}

// Per-case pool augmentation: union the case's retrieved chunks with fresh candidates from the
// connected index (BM25/vector/hybrid), so a labeler can judge relevant chunks the system
// missed. Also hosts the manual "search the index" box. Self-contained: it owns its labels
// optimistically (pooled candidates aren't part of the trace-based case counts).
function PoolSection({
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

function CaseCard({
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

// Cohen's kappa interpretation (Landis & Koch bands), for a plain-language verdict.
function kappaVerdict(k: number): { text: string; cls: string } {
  if (k < 0.2) return { text: "slight agreement", cls: "text-red-600 dark:text-red-400" };
  if (k < 0.4) return { text: "fair agreement", cls: "text-amber-600 dark:text-amber-400" };
  if (k < 0.6) return { text: "moderate agreement", cls: "text-amber-600 dark:text-amber-400" };
  if (k < 0.8) return { text: "substantial agreement", cls: "text-emerald-600 dark:text-emerald-400" };
  return { text: "almost perfect agreement", cls: "text-emerald-600 dark:text-emerald-400" };
}

// Inter-annotator agreement (Cohen's kappa) over double-judged chunks, plus an adjudication
// list to resolve disagreements into gold. Project-wide; loads on expand.
function AgreementPanel({ canEdit }: { canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<AgreementReport | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [goldByKey, setGoldByKey] = useState<Record<string, number>>({});

  const load = useCallback(() => {
    setState("loading");
    getAgreement()
      .then((r) => {
        setReport(r);
        setState("loaded");
      })
      .catch(() => setState("error"));
  }, []);

  const onToggle = () => {
    const next = !open;
    setOpen(next);
    if (next && state === "idle") load();
  };

  const adjudicate = (d: Disagreement, grade: number) => {
    const key = `${d.test_id}|${d.chunk_id}`;
    const prev = goldByKey[key];
    setGoldByKey((m) => ({ ...m, [key]: grade }));
    setGold(d.test_id, d.chunk_id, grade).catch(() => {
      toast.error("Failed to adjudicate");
      setGoldByKey((m) => {
        const next = { ...m };
        if (prev == null) delete next[key];
        else next[key] = prev;
        return next;
      });
    });
  };

  const k = report?.average_kappa;
  const verdict = k != null ? kappaVerdict(k) : null;

  return (
    <div className="mb-4 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-[12px] font-medium text-gray-600 dark:text-slate-300 hover:bg-gray-50/60 dark:hover:bg-slate-800/30"
      >
        <span className="text-gray-400">{open ? "▾" : "▸"}</span>
        Annotator agreement
        {report?.available && verdict && (
          <span className={`ml-1 ${verdict.cls}`}>
            κ {k!.toFixed(2)} · {verdict.text}
          </span>
        )}
        {report && !report.available && (
          <span className="ml-1 font-normal text-gray-400 dark:text-slate-500">
            needs a second annotator
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-gray-100 dark:border-slate-800">
          {state === "loading" ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-3">Computing agreement…</p>
          ) : state === "error" ? (
            <p className="text-[12px] text-red-500 py-3">Failed to load agreement.</p>
          ) : !report || !report.available ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-3">
              Cohen&apos;s κ needs at least two annotators judging the same chunks. Have a second
              reviewer label a 10–15% overlap sample, then κ and disagreements show up here.
            </p>
          ) : (
            <div className="pt-3 space-y-4">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[12px] text-gray-500 dark:text-slate-400">
                <span>
                  <span className="font-semibold tabular-nums">{report.overlap_count}</span>{" "}
                  double-judged chunks ({Math.round(report.double_judged_pct * 100)}% of{" "}
                  {report.judged_items})
                </span>
                <span>{report.annotators.map((a) => `${a.name} (${a.judged_count})`).join(", ")}</span>
              </div>

              {report.pairwise.length > 1 && (
                <div className="text-[11px] text-gray-500 dark:text-slate-400 space-y-0.5">
                  {report.pairwise.map((p) => (
                    <div key={`${p.a}-${p.b}`}>
                      {p.a} ↔ {p.b}: κ {p.kappa.toFixed(2)} <span className="text-gray-400">(n={p.n})</span>
                    </div>
                  ))}
                </div>
              )}

              {report.disagreements.length > 0 ? (
                <div>
                  <div className="text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-2">
                    Disagreements to adjudicate ({report.disagreements.length})
                  </div>
                  <div className="rounded-lg border border-gray-100 dark:border-slate-800 divide-y divide-gray-50 dark:divide-slate-800/50">
                    {report.disagreements.map((d) => {
                      const key = `${d.test_id}|${d.chunk_id}`;
                      const gold = goldByKey[key] ?? d.gold ?? null;
                      return (
                        <div key={key} className="flex items-start gap-3 px-3 py-2.5">
                          <div className="min-w-0 flex-1">
                            <p className="text-[12px] text-gray-700 dark:text-slate-300 truncate">
                              {d.title || d.chunk_id}
                            </p>
                            <p className="text-[11px] text-gray-400 dark:text-slate-500">
                              {d.votes
                                .map((v) => `${v.labeler}: ${v.relevance} (${gradeLabel(v.relevance)})`)
                                .join(" · ")}
                              {gold != null && (
                                <span className="ml-2 text-gray-500 dark:text-slate-400">
                                  → gold: {gold} ({gradeLabel(gold)})
                                </span>
                              )}
                            </p>
                          </div>
                          <GradeSelector
                            value={gold}
                            disabled={!canEdit}
                            onSelect={(grade) => adjudicate(d, grade)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <p className="text-[12px] text-gray-400 dark:text-slate-500">
                  No disagreements among the double-judged chunks.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

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
  const [tab, setTab] = useState<"in_progress" | "complete">("in_progress");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [indexConnected, setIndexConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Per-method ranks come from the index heads (Azure), pooled per case. Eager-loaded for every
  // case once the view is in, so each retrieved chunk can show where each method ranked it.
  // The pool is cached server-side, so re-opening the page doesn't re-query the index.
  const [poolByCase, setPoolByCase] = useState<Record<string, LabelingPoolResponse>>({});
  const [poolLoading, setPoolLoading] = useState<Set<string>>(new Set());
  const poolRequested = useRef<Set<string>>(new Set());

  useEffect(() => {
    getIndexProviders()
      .then((res) => setIndexConnected(res.data.length > 0))
      .catch(() => setIndexConnected(false));
  }, []);

  // Labeling aggregates every test case across the project's runs — no run selection needed.
  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    return getLabelingView()
      .then((v) => {
        setView(v);
        setCollapsed(new Set());
        // Fresh view: drop any pooled ranks so they're re-fetched against the new cases.
        setPoolByCase({});
        setPoolLoading(new Set());
        poolRequested.current = new Set();
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Pool a set of cases through the index heads (Azure) with bounded concurrency, writing each
  // result into poolByCase as it lands. ``refresh`` forces a server-side recompute (bypassing
  // the pool cache). Shared by the eager initial load and the manual "recompute" button.
  const loadPools = useCallback(async (testIds: string[], refresh: boolean) => {
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
          const p = await getLabelingPool(testId, { refresh });
          setPoolByCase((prev) => ({ ...prev, [testId]: p }));
        } catch {
          // Leave this case without ranks; its chunks just won't show method badges.
        } finally {
          settle(testId);
        }
      }
    };
    const POOL_CONCURRENCY = 4;
    await Promise.all(Array.from({ length: Math.min(POOL_CONCURRENCY, testIds.length) }, worker));
  }, []);

  // Eager-pool every case once the view is in, so each retrieved chunk shows its per-method
  // ranks. The server-side pool cache makes repeat loads cheap. Skipped entirely with no index.
  useEffect(() => {
    if (!view?.available || !indexConnected) return;
    const todo = view.cases
      .filter((c) => c.chunks.some((ch) => ch.chunk_id) && !poolRequested.current.has(c.test_id))
      .map((c) => c.test_id);
    if (todo.length === 0) return;
    todo.forEach((id) => poolRequested.current.add(id));
    void loadPools(todo, false);
  }, [view, indexConnected, loadPools]);

  // Explicit recompute: re-pool every labelable case against the index, bypassing the cache.
  const [recomputing, setRecomputing] = useState(false);
  const recomputePools = useCallback(async () => {
    if (!view) return;
    const ids = view.cases
      .filter((c) => c.chunks.some((ch) => ch.chunk_id))
      .map((c) => c.test_id);
    if (ids.length === 0) return;
    setRecomputing(true);
    try {
      await loadPools(ids, true);
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

  // Which index heads actually ran vs. couldn't (e.g. no vectorizer), aggregated across cases.
  // Surfaced so "not pooled" rows are explainable: if a head is unavailable, it can't rank.
  const poolHeads = useMemo(() => {
    const ran = new Set<string>();
    const failed: Record<string, string> = {};
    for (const p of Object.values(poolByCase)) {
      for (const h of p.heads_ran) if (h !== "trace") ran.add(h);
      for (const [h, reason] of Object.entries(p.heads_failed)) if (!(h in failed)) failed[h] = reason;
    }
    return { ran: [...ran], failed };
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
      // Collapse a case when it's marked complete to keep focus on remaining work.
      if (complete) setCollapsed((prev) => new Set(prev).add(testId));
      try {
        await setLabelingComplete(testId, complete);
      } catch {
        toast.error("Failed to update status");
        load();
      }
    },
    [load],
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
        load();
      }
    },
    [load],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Optimistic graded label: update local state, persist, roll back on error.
  const onGrade = useCallback(
    async (testId: string, chunk: ChunkForLabeling, relevance: number) => {
      if (!chunk.chunk_id) return;
      setView((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          cases: prev.cases.map((c) => {
            if (c.test_id !== testId) return c;
            const chunks = c.chunks.map((ch) =>
              ch.chunk_id === chunk.chunk_id ? { ...ch, relevance } : ch,
            );
            const labeled_count = chunks.filter((ch) => ch.relevance != null).length;
            const relevant_count = chunks.filter((ch) => (ch.relevance ?? 0) >= 1).length;
            return { ...c, chunks, labeled_count, relevant_count };
          }),
        };
      });
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
        load();
      }
    },
    [load],
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
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        Judge the chunks each test case actually retrieved. Grade each one 0 (irrelevant),
        1 (marginally relevant), 2 (relevant), or 3 (highly relevant); these labels become the
        ground truth for the chunk-level precision, recall and nDCG on the Pipeline page (any
        grade ≥ 1 counts as relevant; nDCG weights by grade). Labels are shared across runs, so
        you only judge a chunk once per query. Expand a case to also pool extra candidates from
        the connected index (BM25/vector/hybrid) and judge chunks the system may have missed.
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
          No retrieved chunks captured yet. Run an evaluation against the retrieval
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
              {indexConnected && (
                <div className="flex items-center gap-2">
                  <span
                    title="Per-method ranks (BM25/vector/hybrid) are pooled live from the index (Azure AI Search). Shows the oldest pool across cases."
                  >
                    {poolLoading.size > 0
                      ? "Pooling ranks…"
                      : lastPooledAt
                        ? `Ranks pooled ${relativeTime(lastPooledAt)}`
                        : "Ranks not pooled"}
                  </span>
                  {Object.keys(poolHeads.failed).length > 0 && (
                    <span
                      className="text-amber-600 dark:text-amber-400"
                      title={Object.entries(poolHeads.failed)
                        .map(([h, r]) => `${h}: ${r}`)
                        .join("\n")}
                    >
                      {Object.keys(poolHeads.failed).join(", ")} unavailable
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
                        pool={poolByCase[c.test_id] ?? null}
                        poolLoading={poolLoading.has(c.test_id)}
                        collapsed={collapsed.has(c.test_id)}
                        onToggleCollapse={() => toggleCase(c.test_id)}
                        onToggleComplete={(v) => onToggleComplete(c.test_id, v)}
                        onSetSlice={(s) => onSetSlice(c.test_id, s)}
                        onGrade={onGrade}
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
