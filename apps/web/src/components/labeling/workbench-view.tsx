"use client";

import { useEffect, useMemo, useState } from "react";
import {
  type LabelingCase,
  type LabelingPoolResponse,
  type LabelingPromptDefaults,
  type PooledChunkForLabeling,
} from "@/lib/api";
import { PoolChunkRow } from "./pool-chunk-row";
import { PoolSection } from "./pool-section";
import { CasePromptsPanel } from "./case-prompts";
import { relativeTime } from "./labeling-controls";

// Risk slices a test case can be assigned to (matches the API's SLICE_VALUES).
const SLICES = ["broad", "safety", "adversarial"] as const;

const SLICE_BADGE: Record<string, string> = {
  safety: "bg-red-500/10 text-red-600 dark:text-red-300 border-red-500/30",
  adversarial: "bg-orange-500/10 text-orange-600 dark:text-orange-300 border-orange-500/30",
  broad: "bg-slate-500/10 text-slate-600 dark:text-slate-300 border-slate-500/20",
};

// The per-question workbench: one case's question pinned at the top, its pooled chunks below.
// This is the focused single-item view (one question at a time) — the index links here per case.
export function WorkbenchView({
  c,
  canEdit,
  indexConnected,
  datasetId,
  pool,
  poolLoading,
  recomputing,
  onRecompute,
  onToggleComplete,
  onSetSlice,
  onGrade,
  onClearGrade,
  onAiJudge,
  aiJudging,
  includeExpectedAnswer,
  onIncludeExpectedAnswerChange,
  onPlan,
  planning,
  promptDefaults,
}: {
  c: LabelingCase;
  canEdit: boolean;
  indexConnected: boolean;
  datasetId?: string;
  // The case's live index pool — the chunks to judge.
  pool: LabelingPoolResponse | null;
  poolLoading: boolean;
  recomputing: boolean;
  // Re-query the index for this one case, bypassing the cache.
  onRecompute: () => void;
  onToggleComplete: (complete: boolean) => void;
  onSetSlice: (slice: string | null) => void;
  onGrade: (testId: string, chunk: PooledChunkForLabeling, grade: number) => void;
  onClearGrade: (testId: string, chunk: PooledChunkForLabeling) => void;
  // Run the LLM "AI judge" over this case's pooled chunks. ``instructions`` overrides the default
  // rubric (edited in the prompts panel).
  onAiJudge: (instructions?: string) => void;
  aiJudging: boolean;
  // Whether the AI judge folds this case's reference answer into its prompt.
  includeExpectedAnswer: boolean;
  onIncludeExpectedAnswerChange: (value: boolean) => void;
  // Plan (or re-plan) the agentic sub-queries for this case, then re-pool.
  onPlan: (instructions?: string) => void;
  planning: boolean;
  promptDefaults: LabelingPromptDefaults | null;
}) {
  // Edited AI-judge rubric for this case (null = use the default), and whether the judge panel is
  // open. The header "AI judge" button opens the panel (two-step); "Run AI judge" in it grades.
  const [judgeInstructions, setJudgeInstructions] = useState<string | null>(null);
  const [judgeOpen, setJudgeOpen] = useState(false);
  // The reference answer is shown expanded by default (the labeler judges chunks against it).
  const [answerOpen, setAnswerOpen] = useState(true);

  // AI judge grades are hidden by default so they don't anchor the human labeler. The choice is
  // remembered across cases (and reloads) via localStorage.
  const [showAiLabels, setShowAiLabels] = useState(false);
  useEffect(() => {
    setShowAiLabels(localStorage.getItem("labeling:showAiLabels") === "1");
  }, []);
  const toggleAiLabels = () =>
    setShowAiLabels((v) => {
      const next = !v;
      localStorage.setItem("labeling:showAiLabels", next ? "1" : "0");
      return next;
    });

  const chunks = useMemo(() => pool?.chunks ?? [], [pool]);
  const counts = useMemo(() => {
    if (!pool) return { labeled: c.labeled_count, relevant: c.relevant_count, total: null as number | null };
    return {
      labeled: chunks.filter((ch) => ch.relevance != null).length,
      relevant: chunks.filter((ch) => (ch.relevance ?? 0) >= 1).length,
      total: chunks.length,
    };
  }, [pool, chunks, c.labeled_count, c.relevant_count]);

  const shownIds = useMemo(() => new Set(chunks.map((ch) => ch.chunk_id)), [chunks]);

  return (
    <div className="flex flex-col min-h-0 flex-1 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900">
      {/* The question, expected answer and queries are a fixed pane; only the chunk list below
          scrolls. flex-none keeps this block at its natural height. */}
      <div className="flex-none rounded-t-xl overflow-hidden">
      <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800">
        <h2
          className="text-[15px] font-semibold text-gray-900 dark:text-white min-w-0"
          title={c.input ?? c.test_id}
        >
          {c.input || c.test_id}
        </h2>
        <div className="shrink-0 flex items-center gap-3 text-[11px] text-gray-400 dark:text-slate-500">
          {(() => {
            // When AI labels are hidden, keep the AI judge out of the "labeled by" line too.
            const shownLabelers = showAiLabels ? c.labelers : c.labelers.filter((l) => l !== "AI");
            return shownLabelers.length > 0 ? (
              <span
                className="hidden sm:inline italic truncate max-w-[160px]"
                title={`Labeled by ${shownLabelers.join(", ")}`}
              >
                by {shownLabelers.join(", ")}
              </span>
            ) : null;
          })()}
          <span>
            {counts.labeled}
            {counts.total != null ? `/${counts.total}` : ""} · {counts.relevant} relevant
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
          {indexConnected && (
            <button
              onClick={onRecompute}
              disabled={recomputing || poolLoading}
              title="Re-query the index for this question, bypassing the cache. Use after re-indexing."
              className="px-2 py-1 rounded-lg text-[11px] font-medium border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
            >
              {recomputing ? "Recomputing…" : "Recompute"}
            </button>
          )}
          <button
            onClick={toggleAiLabels}
            title={
              showAiLabels
                ? "Hide the AI judge grades on each chunk"
                : "Show the AI judge grades on each chunk"
            }
            className={`px-2 py-1 rounded-lg text-[11px] font-medium border disabled:opacity-40 ${
              showAiLabels
                ? "border-violet-400 bg-violet-500/10 text-violet-600 dark:text-violet-300"
                : "border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-violet-400"
            }`}
          >
            {showAiLabels ? "Hide AI labels" : "Show AI labels"}
          </button>
          <button
            disabled={!canEdit || !indexConnected}
            onClick={() => setJudgeOpen((v) => !v)}
            title="Open the AI judge prompt — review or edit it, then run it to grade this case's chunks"
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium border disabled:opacity-40 ${
              judgeOpen
                ? "border-violet-400 bg-violet-500/10 text-violet-600 dark:text-violet-300"
                : "border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400"
            }`}
          >
            <span aria-hidden>✦</span>
            AI judge
          </button>
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
        {c.expected_answer && (
          <div className="px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-emerald-50/40 dark:bg-emerald-900/10">
            <button
              onClick={() => setAnswerOpen((v) => !v)}
              className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300"
            >
              <span aria-hidden>{answerOpen ? "▾" : "▸"}</span>
              Expected answer
            </button>
            {answerOpen && (
              // Capped so a long reference answer can't eat the viewport while frozen — it
              // scrolls internally instead, keeping the chunks below in view.
              <p className="mt-1.5 max-h-[38vh] overflow-y-auto text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
                {c.expected_answer}
              </p>
            )}
          </div>
        )}
        {indexConnected && (
          <CasePromptsPanel
            testId={c.test_id}
            datasetId={datasetId}
            queries={pool?.queries}
            defaults={promptDefaults}
            canEdit={canEdit}
            indexConnected={indexConnected}
            planning={planning}
            judgeInstructions={judgeInstructions}
            onJudgeInstructionsChange={setJudgeInstructions}
            onPlan={onPlan}
            judgeOpen={judgeOpen}
            onRunJudge={onAiJudge}
            aiJudging={aiJudging}
            includeExpectedAnswer={includeExpectedAnswer}
            onIncludeExpectedAnswerChange={onIncludeExpectedAnswerChange}
          />
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto rounded-b-xl">
        {!indexConnected ? (
          <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">
            Connect an index provider (Settings → Integrations) to pool candidate chunks for this
            query.
          </p>
        ) : poolLoading && !pool ? (
          <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">Pooling candidates…</p>
        ) : chunks.length === 0 ? (
          <p className="px-4 py-6 text-[12px] text-gray-400 dark:text-slate-500">
            No candidates found for this query
            {pool && Object.keys(pool.heads_failed).length > 0
              ? ` (${Object.keys(pool.heads_failed).join(", ")} unavailable)`
              : ""}
            . Use the search box below to try a different query.
          </p>
        ) : (
          chunks.map((chunk) => (
            <PoolChunkRow
              key={chunk.chunk_id}
              chunk={chunk}
              testId={c.test_id}
              relevance={chunk.relevance ?? null}
              disabled={!canEdit}
              indexConnected={indexConnected}
              showAiLabels={showAiLabels}
              onGrade={(grade) => onGrade(c.test_id, chunk, grade)}
              onClear={() => onClearGrade(c.test_id, chunk)}
            />
          ))
        )}
        <PoolSection
          testId={c.test_id}
          datasetId={datasetId}
          canEdit={canEdit}
          indexConnected={indexConnected}
          showAiLabels={showAiLabels}
          alreadyShownIds={shownIds}
        />
        {pool?.computed_at && (
          <p className="px-4 py-2 text-[11px] text-gray-400 dark:text-slate-500 border-t border-gray-100 dark:border-slate-800">
            Pooled {relativeTime(pool.computed_at)}
          </p>
        )}
      </div>
    </div>
  );
}
