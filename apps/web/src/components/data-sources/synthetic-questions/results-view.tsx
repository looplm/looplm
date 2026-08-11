"use client";

/**
 * Results of a synthetic-question run: what was produced, what was discarded, and the
 * questions themselves with the chunk each one is grounded in.
 */

import Link from "next/link";

import { StatCard } from "@/components/eval-shared";
import type {
  SyntheticQuestionItem,
  SyntheticQuestionRunDetail,
  SyntheticStyle,
} from "@/lib/api-types/synthetic-questions";

const SKIP_LABELS: Record<string, string> = {
  empty: "empty",
  tiny: "too short",
  mojibake: "mis-decoded characters",
  markup_heavy: "raw markup",
  duplicate: "sampled twice",
};

const STYLE_STYLES: Record<SyntheticStyle, string> = {
  factual: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  paraphrase: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300",
  negative: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

const STYLE_LABELS: Record<SyntheticStyle, string> = {
  factual: "Factual",
  paraphrase: "Paraphrased",
  negative: "Unanswerable",
};

function StyleChip({ style }: { style: SyntheticStyle }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${STYLE_STYLES[style]}`}>
      {STYLE_LABELS[style]}
    </span>
  );
}

function QuestionRow({ question }: { question: SyntheticQuestionItem }) {
  return (
    <div className="px-4 py-3 border-b border-gray-100 dark:border-slate-800 last:border-0">
      <div className="flex items-start gap-2">
        <StyleChip style={question.style} />
        <p className="text-sm flex-1 min-w-0">{question.text}</p>
      </div>
      {question.style === "negative" ? (
        <p className="mt-1.5 ml-1 text-xs text-gray-500 dark:text-slate-400">
          No source chunk. The assistant should say it cannot answer this.
        </p>
      ) : (
        <div className="mt-1.5 ml-1 text-xs text-gray-500 dark:text-slate-400">
          <span className="font-medium">Answer chunk: </span>
          {question.source_url ? (
            <a
              href={question.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {question.source_title || question.source_chunk_id}
            </a>
          ) : (
            <span>{question.source_title || question.source_chunk_id}</span>
          )}
          {question.source_preview && (
            <p className="mt-1 line-clamp-2 text-gray-400 dark:text-slate-500">
              {question.source_preview}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function ResultsView({ run }: { run: SyntheticQuestionRunDetail }) {
  const results = run.results;
  if (!results) return null;
  const { counts, questions } = results;
  const skipped = Object.entries(counts.chunks_skipped ?? {}).filter(([, n]) => n > 0);
  const total = questions.length;

  // A benchmark drawn from a handful of documents measures those documents, not the corpus, and
  // its recall numbers are not a verdict on retrieval. Say so on the run rather than leaving the
  // reader to work it out from a scoreboard.
  const docs = counts.documents_used ?? 0;
  const concentrated = docs > 0 && counts.chunks_used / docs > 4;

  return (
    <div>
      {concentrated && (
        <div className="rounded-xl border border-amber-100 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-950/20 px-4 py-3 mb-5 text-xs text-amber-900 dark:text-amber-200">
          <p className="font-medium mb-0.5">Narrow coverage</p>
          <p>
            {counts.chunks_used.toLocaleString()} chunks came from only {docs.toLocaleString()}{" "}
            document{docs === 1 ? "" : "s"}, so these questions measure those documents rather
            than the corpus. Scores from this dataset are not a verdict on retrieval overall.
            Sample more chunks, or scope the run to a category with more documents in it.
          </p>
        </div>
      )}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Questions" value={total.toLocaleString()} />
        <StatCard
          label="Documents covered"
          value={(counts.documents_used ?? 0).toLocaleString()}
        />
        <StatCard
          label="Unanswerable"
          value={questions.filter((q) => q.style === "negative").length.toLocaleString()}
        />
        <StatCard
          label={run.persist ? "Cases created" : "Preview"}
          value={run.persist ? counts.cases_created.toLocaleString() : "not saved"}
        />
      </div>

      {run.persist && run.dataset_id && (
        <div className="rounded-xl border border-emerald-100 dark:border-emerald-900/40 bg-emerald-50/50 dark:bg-emerald-950/20 px-4 py-3 mb-5 text-sm">
          Saved {counts.cases_created.toLocaleString()} test cases into{" "}
          <Link
            href={`/datasets/${run.dataset_id}`}
            className="font-medium text-emerald-700 dark:text-emerald-300 hover:underline"
          >
            {run.dataset_name || "the dataset"}
          </Link>
          . Score it on the{" "}
          <Link
            href="/retrieval"
            className="font-medium text-emerald-700 dark:text-emerald-300 hover:underline"
          >
            Retrieval page
          </Link>{" "}
          by selecting this dataset and the Synthetic gold source.
        </div>
      )}

      <div className="rounded-xl border border-gray-200 dark:border-slate-700 p-4 mb-5 text-xs text-gray-600 dark:text-slate-300">
        <p className="font-medium mb-1">What was set aside</p>
        <ul className="space-y-0.5">
          <li>
            Sampled {counts.chunks_sampled.toLocaleString()} chunks, used{" "}
            {counts.chunks_used.toLocaleString()} from{" "}
            {(counts.documents_used ?? 0).toLocaleString()} documents
            {skipped.length > 0 && (
              <>
                {" "}
                (skipped{" "}
                {skipped
                  .map(([flag, n]) => `${n} ${SKIP_LABELS[flag] ?? flag}`)
                  .join(", ")}
                )
              </>
            )}
            .
          </li>
          {counts.duplicates_dropped > 0 && (
            <li>
              Dropped {counts.duplicates_dropped.toLocaleString()} repeated questions. Two cases
              asking the same thing with different answer chunks would score one as a miss no
              matter what the retriever returns.
            </li>
          )}
          {counts.negatives_generated > 0 && (
            <li>
              Drafted {counts.negatives_generated.toLocaleString()} unanswerable questions
              {counts.negatives_dropped > 0 && (
                <>
                  {" "}
                  and discarded {counts.negatives_dropped.toLocaleString()} the index turned out
                  to answer
                </>
              )}
              .
            </li>
          )}
        </ul>
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/50">
          <p className="text-sm font-medium">
            Generated questions{" "}
            <span className="text-gray-400 dark:text-slate-500">({total.toLocaleString()})</span>
          </p>
        </div>
        {questions.map((question, i) => (
          <QuestionRow key={`${question.source_chunk_id ?? "neg"}-${i}`} question={question} />
        ))}
        {total === 0 && (
          <p className="px-4 py-6 text-sm text-center text-gray-500 dark:text-slate-400">
            No questions survived. Every sampled chunk was either unusable or could not support a
            standalone question.
          </p>
        )}
      </div>
    </div>
  );
}
