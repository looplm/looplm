"use client";

import { useState } from "react";
import { getChunkMetadata, type ChunkForLabeling } from "@/lib/api";
import { gradeTint } from "./types";
import { GradeSelector } from "./grade-selector";

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

export function ChunkRow({
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
