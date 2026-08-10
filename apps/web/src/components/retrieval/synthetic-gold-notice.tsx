"use client";

import Link from "next/link";

/**
 * Shown whenever the metrics are resolved against synthetic gold.
 *
 * Synthetic questions have exactly one known answer chunk each, which changes how two of the
 * headline numbers should be read: recall@k is really hit rate, and precision@k cannot exceed
 * 1/k however good the retriever is. Without this note the precision cards read as a serious
 * quality problem when they are an artifact of the method.
 */
export function SyntheticGoldNotice() {
  return (
    <div className="rounded-xl border border-amber-100 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-950/20 px-4 py-3 mb-6 text-xs text-amber-900 dark:text-amber-200">
      <p className="font-medium mb-0.5">Scored against generated questions</p>
      <p>
        Each question has one known answer chunk, so recall@k here is hit rate and precision@k
        cannot go above 1/k. Compare retrievers on hit rate, MRR and nDCG; a low precision@k is
        the method, not a finding. Chunks that answer the question just as well are unjudged
        rather than wrong, which is what bpref and condensed nDCG account for.{" "}
        <Link href="/data-sources" className="underline hover:no-underline">
          Generate or review the questions
        </Link>
        .
      </p>
    </div>
  );
}
