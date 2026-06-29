"use client";

import { useState } from "react";
import { getChunkMetadata, type PooledChunkForLabeling } from "@/lib/api";
import { gradeTint } from "./types";
import { GradeSelector } from "./grade-selector";
import { AiGradeBadge, ProvenanceBadges, pickIndexText } from "./chunk-row";

// A pooled candidate chunk (from an index search head). Lighter than ChunkRow — no rank or
// document locators — but judgeable the same way, with provenance badges and full-text fetch.
export function PoolChunkRow({
  chunk,
  relevance,
  disabled,
  indexConnected,
  onGrade,
  onClear,
}: {
  chunk: PooledChunkForLabeling;
  relevance: number | null;
  disabled: boolean;
  indexConnected: boolean;
  onGrade: (grade: number) => void;
  onClear: () => void;
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
          {/* Per-head rank badges are the honest signal; the raw backend score isn't shown
              because each head scores on a different, incomparable scale (BM25 unbounded vs
              RRF ~1 vs reranker 0-4). */}
          <ProvenanceBadges provenance={chunk.provenance} ranks={chunk.ranks} />
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

      <div className="shrink-0 flex items-center gap-2">
        {chunk.ai_relevance != null && <AiGradeBadge grade={chunk.ai_relevance} />}
        <GradeSelector value={relevance} disabled={disabled} onSelect={onGrade} onClear={onClear} />
      </div>
    </div>
  );
}
