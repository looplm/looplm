"use client";

/**
 * Test questions tab: generates evaluation questions from indexed chunks.
 *
 * Each question is written from one chunk, so that chunk is its ground truth by construction.
 * The result is a labeled retrieval benchmark with no human labeling and no production traffic,
 * scoreable on the Retrieval page against a live index with no LLM in the loop.
 *
 * The run lifecycle lives in `useSyntheticQuestions`; the form and results in
 * `synthetic-questions/`.
 */

import { useState } from "react";
import Link from "next/link";

import type { SyntheticQuestionRunRequest } from "@/lib/api-types/synthetic-questions";

import { ResultsView } from "./synthetic-questions/results-view";
import { RunForm } from "./synthetic-questions/run-form";
import { useSyntheticQuestions } from "./use-synthetic-questions";

const STAGE_LABELS: Record<string, string> = {
  sampling: "Sampling chunks from the index",
  generating: "Writing questions",
  negatives: "Drafting unanswerable questions",
  verifying: "Checking the unanswerable ones against the index",
  persisting: "Saving the dataset",
};

export function SyntheticQuestionsTab({
  providerId,
  canEdit,
}: {
  providerId: string;
  canEdit: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [howOpen, setHowOpen] = useState(false);
  const { run, running, handleRun, handleCancel } = useSyntheticQuestions(providerId, setError);

  const start = (body: Omit<SyntheticQuestionRunRequest, "provider_id">) => handleRun(body);
  const progressPct = run && run.total > 0 ? (run.processed / run.total) * 100 : 0;

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Test questions</h2>
        <p className="text-xs text-gray-500 dark:text-slate-400">
          Generate evaluation questions from the chunks in this index. Each question is written
          from one chunk, so that chunk is the answer it should retrieve. You get a scoreable
          dataset before you have any real user data.
        </p>
        <button
          onClick={() => setHowOpen((v) => !v)}
          className="mt-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {howOpen ? "Hide details" : "How to read the scores"}
        </button>
      </div>

      {howOpen && (
        <div className="rounded-xl border border-gray-200 dark:border-slate-700 p-4 mb-5 text-xs text-gray-600 dark:text-slate-300 space-y-2">
          <p>
            <span className="font-medium">Read hit rate, MRR and nDCG.</span> Every question has
            exactly one known answer chunk, so recall@k is really hit rate, and precision@k cannot
            go above 1/k no matter how good the retriever is. That ceiling is an artifact of the
            method, not a finding.
          </p>
          <p>
            <span className="font-medium">Other relevant chunks stay unjudged.</span> A retriever
            may return a chunk that answers the question just as well; it is not marked wrong,
            it is simply not counted. bpref and condensed nDCG on the Retrieval page handle this
            correctly.
          </p>
          <p>
            <span className="font-medium">Unanswerable questions do not move recall.</span> They
            carry no answer chunk, so the retrieval metrics exclude them. They are there for the
            end-to-end eval run, to check the assistant says it does not know, and for tuning the
            reranker score cutoff.
          </p>
          <p>
            <span className="font-medium">Questions are generated, not reviewed.</span> Every case
            lands unvalidated so you can check them in the dataset before trusting the numbers.
          </p>
        </div>
      )}

      {canEdit ? (
        <RunForm providerId={providerId} disabled={running} onStart={start} />
      ) : (
        <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-4 mb-5 text-sm text-gray-500 dark:text-slate-400">
          You have read-only access to data sources, so you cannot start a generation run.
        </div>
      )}

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {running && run && (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-indigo-100 dark:border-indigo-900/40 bg-indigo-50/50 dark:bg-indigo-950/20 px-4 py-3 mb-5">
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-3.5 h-3.5 flex-shrink-0 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
            <div className="min-w-0">
              <p className="text-sm font-medium truncate">
                {STAGE_LABELS[run.stage ?? ""] ?? "Starting"}…
              </p>
              <p className="text-xs text-gray-500 dark:text-slate-400">
                {run.total > 0
                  ? `${run.processed.toLocaleString()} of ${run.total.toLocaleString()} chunks`
                  : `sampling up to ${run.sample_size.toLocaleString()} chunks`}
              </p>
              {run.total > 0 && (
                <div className="mt-1.5 max-w-xs h-1.5 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
                  <div
                    className="h-full bg-indigo-500"
                    style={{ width: `${Math.min(100, progressPct)}%` }}
                  />
                </div>
              )}
            </div>
          </div>
          {canEdit && (
            <button
              onClick={handleCancel}
              className="flex-shrink-0 px-3 py-1.5 rounded-lg text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/50 hover:bg-red-50 dark:hover:bg-red-900/20"
            >
              Stop
            </button>
          )}
        </div>
      )}

      {run?.status === "failed" && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
          {run.error || "The run failed."}
        </div>
      )}

      {run?.status === "cancelled" && !run.results && (
        <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-4 mb-5 text-sm text-gray-500 dark:text-slate-400">
          Run stopped. Nothing was saved: the dataset is written in one step at the end.
        </div>
      )}

      {run?.results ? (
        <ResultsView run={run} />
      ) : (
        !running &&
        !run && (
          <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center">
            <p className="text-sm text-gray-500 dark:text-slate-400">
              No questions generated yet. Preview a handful of chunks to see what comes out, then
              generate a full dataset.
            </p>
            <p className="mt-2 text-xs text-gray-400 dark:text-slate-500">
              Already have one?{" "}
              <Link href="/retrieval" className="text-indigo-600 dark:text-indigo-400 hover:underline">
                Score it on the Retrieval page
              </Link>
              .
            </p>
          </div>
        )
      )}
    </div>
  );
}
