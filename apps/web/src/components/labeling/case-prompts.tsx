"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  aiJudgePreviewCase,
  type AiJudgePreviewResponse,
  type LabelingQueries,
  type LabelingPromptDefaults,
} from "@/lib/api";

// Per-case tools shown above the pooled chunks: the queries that were sent to the index (base
// question + the agentic planner's sub-queries), an editable planner rubric to (re)plan them, and
// the editable AI-judge rubric the header's "AI judge" button runs with. Keeping both editable
// prompts here makes "what was sent" and "what graded it" inspectable in one place.
export function CasePromptsPanel({
  testId,
  datasetId,
  queries,
  defaults,
  canEdit,
  indexConnected,
  planning,
  judgeInstructions,
  onJudgeInstructionsChange,
  onPlan,
}: {
  testId: string;
  datasetId?: string;
  queries: LabelingQueries | null | undefined;
  defaults: LabelingPromptDefaults | null;
  canEdit: boolean;
  indexConnected: boolean;
  planning: boolean;
  // The AI-judge rubric (null = use the default). Owned by the parent so the header judge button
  // runs with whatever is set here.
  judgeInstructions: string | null;
  onJudgeInstructionsChange: (value: string | null) => void;
  // Plan (or re-plan) the agentic sub-queries. ``instructions`` undefined → server default rubric.
  onPlan: (instructions?: string) => void;
}) {
  const [openPlanner, setOpenPlanner] = useState(false);
  const [openJudge, setOpenJudge] = useState(false);
  const [plannerText, setPlannerText] = useState<string | null>(null);
  // The full prompt (system + user, with chunk text folded in) the judge would send, rendered
  // server-side on demand so it never drifts from what actually runs.
  const [preview, setPreview] = useState<AiJudgePreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const base = queries?.base ?? [];
  const agentic = queries?.agentic ?? [];
  const plannerValue = plannerText ?? defaults?.query_planner ?? "";
  const judgeValue = judgeInstructions ?? defaults?.ai_judge ?? "";

  // Fetch the exact prompt for the current (possibly edited) rubric. Editing the rubric or
  // re-pooling invalidates the shown preview, so clear it whenever we re-open.
  const loadPreview = async () => {
    setPreviewing(true);
    try {
      const res = await aiJudgePreviewCase(testId, {
        datasetId,
        instructions: judgeInstructions ?? undefined,
      });
      setPreview(res);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to render the prompt");
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div className="px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30 space-y-2.5 text-[12px]">
      <div className="flex items-start gap-2 flex-wrap">
        <span className="font-semibold text-gray-500 dark:text-slate-400 shrink-0 mt-0.5">
          Queries sent
        </span>
        <div className="min-w-0 flex-1 space-y-1.5">
          {base.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-600 dark:text-slate-300">
                Base
              </span>
              <span className="text-gray-700 dark:text-slate-300 truncate">{base[0]}</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-600 dark:text-indigo-300">
              Agentic
            </span>
            {agentic.length > 0 ? (
              agentic.map((q, i) => (
                <span
                  key={`${i}-${q}`}
                  className="px-1.5 py-0.5 rounded bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-300"
                  title={q}
                >
                  {q}
                </span>
              ))
            ) : (
              <span className="italic text-gray-400 dark:text-slate-500">
                none planned yet
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <button
            disabled={!canEdit || planning || !indexConnected}
            onClick={() => setOpenPlanner((v) => !v)}
            className="px-2 py-1 rounded-lg text-[11px] font-medium border border-indigo-300 dark:border-indigo-700/60 text-indigo-600 dark:text-indigo-300 hover:border-indigo-400 disabled:opacity-40"
          >
            {agentic.length > 0 ? "Re-plan queries" : "Plan queries"}
          </button>
          <button
            onClick={() => setOpenJudge((v) => !v)}
            className="px-2 py-1 rounded-lg text-[11px] font-medium border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-gray-300"
          >
            {openJudge ? "Hide judge rubric" : "Judge rubric"}
          </button>
        </div>
      </div>

      {openPlanner && (
        <div className="rounded-lg border border-indigo-200 dark:border-indigo-800/50 bg-white dark:bg-slate-900 p-2.5 space-y-2">
          <label className="block text-[11px] font-medium text-gray-500 dark:text-slate-400">
            Query planner rubric — how to decompose the question into focused search queries
          </label>
          <textarea
            value={plannerValue}
            onChange={(e) => setPlannerText(e.target.value)}
            rows={5}
            disabled={!canEdit}
            className="w-full rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1.5 text-[12px] font-mono leading-relaxed disabled:opacity-50"
          />
          <div className="flex items-center gap-2">
            <button
              disabled={!canEdit || planning || !indexConnected}
              onClick={() => onPlan(plannerText ?? undefined)}
              className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-indigo-500 text-white hover:bg-indigo-600 disabled:opacity-40"
            >
              {planning ? "Planning…" : "Plan queries & re-pool"}
            </button>
            <button
              onClick={() => setPlannerText(null)}
              disabled={plannerText === null}
              className="px-2 py-1 rounded-lg text-[11px] font-medium border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:border-gray-300 disabled:opacity-40"
            >
              Reset to default
            </button>
          </div>
        </div>
      )}

      {openJudge && (
        <div className="rounded-lg border border-violet-200 dark:border-violet-800/50 bg-white dark:bg-slate-900 p-2.5 space-y-2">
          <label className="block text-[11px] font-medium text-gray-500 dark:text-slate-400">
            AI judge rubric — the header&apos;s ✦ AI judge button grades chunks with this prompt
          </label>
          <textarea
            value={judgeValue}
            onChange={(e) => {
              onJudgeInstructionsChange(e.target.value);
              setPreview(null); // the shown full prompt no longer matches the edited rubric
            }}
            rows={6}
            disabled={!canEdit}
            className="w-full rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1.5 text-[12px] font-mono leading-relaxed disabled:opacity-50"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                onJudgeInstructionsChange(null);
                setPreview(null);
              }}
              disabled={judgeInstructions === null}
              className="px-2 py-1 rounded-lg text-[11px] font-medium border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:border-gray-300 disabled:opacity-40"
            >
              Reset to default
            </button>
            <button
              onClick={loadPreview}
              disabled={previewing || !indexConnected}
              title="Render the exact system + user message (query and chunk text folded in) that would be sent to the LLM"
              className="px-2 py-1 rounded-lg text-[11px] font-medium border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400 disabled:opacity-40"
            >
              {previewing ? "Rendering…" : preview ? "Refresh full prompt" : "Preview full prompt"}
            </button>
          </div>

          {preview && (
            <div className="space-y-2 pt-1">
              <div className="text-[11px] text-gray-400 dark:text-slate-500">
                Exact prompt sent to the LLM · {preview.chunk_count} chunk
                {preview.chunk_count === 1 ? "" : "s"} in full
                {preview.batches.length > 1
                  ? ` · split across ${preview.batches.length} calls to fit the context window`
                  : ""}
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-1">
                  System message
                </div>
                <pre className="max-h-48 overflow-auto rounded-md border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-950 px-2 py-1.5 text-[11px] font-mono leading-relaxed whitespace-pre-wrap break-words text-gray-700 dark:text-slate-300">
                  {preview.system_prompt}
                </pre>
              </div>
              {preview.batches.map((batch, i) => (
                <div key={i}>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-1">
                    {preview.batches.length > 1
                      ? `User message ${i + 1}/${preview.batches.length} · ${batch.chunk_count} chunk${batch.chunk_count === 1 ? "" : "s"}`
                      : "User message (query + chunks)"}
                  </div>
                  <pre className="max-h-96 overflow-auto rounded-md border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-950 px-2 py-1.5 text-[11px] font-mono leading-relaxed whitespace-pre-wrap break-words text-gray-700 dark:text-slate-300">
                    {batch.user_prompt}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
