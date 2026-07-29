"use client";

import { useState } from "react";
import { getChunkMetadata, type PooledChunkForLabeling } from "@/lib/api";
import { gradeTint } from "./types";
import { GradeSelector } from "./grade-selector";
import { AiGradeBadge, ProvenanceBadges, pickIndexText } from "./chunk-row";
import { PassagePanel } from "./passage-panel";
import { ChunkText, isRenderable } from "@/components/chunk-text";

// A pooled candidate chunk (from an index search head). Lighter than ChunkRow — no rank or
// document locators — but judgeable the same way, with provenance badges and full-text fetch.
export function PoolChunkRow({
  chunk,
  testId,
  relevance,
  disabled,
  indexConnected,
  showAiLabels,
  renderMarkup,
  onGrade,
  onClear,
}: {
  chunk: PooledChunkForLabeling;
  // The test case this chunk is being judged under — passage selections hang off (test_id, chunk_id).
  testId: string;
  relevance: number | null;
  disabled: boolean;
  indexConnected: boolean;
  // Whether to show the LLM "AI judge" grade badge — hidden by default so it doesn't anchor
  // the human labeler.
  showAiLabels: boolean;
  // Workbench-wide default for rendering HTML/Markdown chunks as formatted content; each row can
  // still flip itself back to the raw text.
  renderMarkup: boolean;
  onGrade: (grade: number) => void;
  onClear: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [docState, setDocState] = useState<"idle" | "loading" | "loaded">("idle");
  // Per-row override of the workbench-wide render toggle (null = follow it).
  const [renderOverride, setRenderOverride] = useState<boolean | null>(null);

  const previewText = chunk.content_preview || "";
  const indexText = pickIndexText(doc);
  const fullText = indexText ?? previewText;
  const canFetchIndex = indexConnected && !!chunk.chunk_id;
  const isLong = previewText.length > 240 || previewText.includes("\n") || canFetchIndex;
  const shownText = expanded ? fullText : previewText;
  const rendered = renderOverride ?? renderMarkup;
  const hasMarkup = isRenderable(shownText);

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
        ) : shownText ? (
          <ChunkText text={shownText} rendered={rendered} clamp={!expanded} />
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
          {hasMarkup && (
            <button
              onClick={() => setRenderOverride(!rendered)}
              title={
                rendered
                  ? "Show the raw chunk text exactly as it is stored in the index"
                  : "Render this chunk's HTML/Markdown as formatted text and tables"
              }
              className="font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:underline"
            >
              {rendered ? "Raw text" : "Render markup"}
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
          {chunk.agentic_queries && chunk.agentic_queries.length > 0 && (
            <span
              className="text-indigo-500/80 dark:text-indigo-400/80 truncate max-w-[300px]"
              title={`Surfaced by agentic ${chunk.agentic_queries.length === 1 ? "query" : "queries"}: ${chunk.agentic_queries.join(" · ")}`}
            >
              via {chunk.agentic_queries.join(" · ")}
            </span>
          )}
        </div>

        {/* Passage-selection refinement: only offered once the chunk is judged relevant — it
            narrows *which* passages inside a relevant chunk help, so it's moot for a 0 grade. */}
        {relevance != null && relevance >= 1 && (
          <PassagePanel
            testId={testId}
            chunkId={chunk.chunk_id}
            canEdit={!disabled}
            indexConnected={indexConnected}
          />
        )}
      </div>

      <div className="shrink-0 flex items-center gap-2">
        {showAiLabels && chunk.ai_relevance != null && <AiGradeBadge grade={chunk.ai_relevance} />}
        <GradeSelector value={relevance} disabled={disabled} onSelect={onGrade} onClear={onClear} />
      </div>
    </div>
  );
}
