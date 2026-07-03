"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getCaseDiagnosis,
  type CaseDiagnosisResponse,
  type DiagnosedChunk,
} from "@/lib/api";

// Each verdict's label, color, and what it points the fix at. Ordered worst-first to match the
// backend ordering of the missed list.
const VERDICT: Record<string, { label: string; cls: string; hint: string }> = {
  not_in_index: {
    label: "Not in index",
    cls: "bg-red-500/10 text-red-600 dark:text-red-300",
    hint: "The chunk key isn't in the index (stale label, re-indexed, or deleted).",
  },
  missing_embedding: {
    label: "Missing embedding",
    cls: "bg-red-500/10 text-red-600 dark:text-red-300",
    hint: "The chunk has no vector, so vector/hybrid search can never find it. Re-index.",
  },
  bad_chunk: {
    label: "Bad chunk",
    cls: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
    hint: "A quality flag (tiny/giant/mojibake/table/markup) makes it hard to retrieve. Re-chunk / clean the indexer.",
  },
  buried: {
    label: "Buried",
    cls: "bg-sky-500/10 text-sky-600 dark:text-sky-300",
    hint: "Clean and embedded, but ranked past k. A ranking problem, not a chunk problem.",
  },
  unretrievable: {
    label: "Unretrievable",
    cls: "bg-violet-500/10 text-violet-600 dark:text-violet-300",
    hint: "Clean and embedded, but never surfaces — a lexical/semantic gap, or the label is wrong.",
  },
};

const FLAG_LABEL: Record<string, string> = {
  tiny: "tiny",
  giant: "giant",
  mojibake: "mojibake",
  table_heavy: "table-heavy",
  markup_heavy: "markup",
  missing_embedding: "no embedding",
  empty: "empty",
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = VERDICT[verdict] ?? { label: verdict, cls: "bg-gray-500/10 text-gray-500", hint: "" };
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${v.cls}`}
      title={v.hint}
    >
      {v.label}
    </span>
  );
}

function MissedRow({ chunk }: { chunk: DiagnosedChunk }) {
  return (
    <li className="flex items-start gap-2 py-2">
      <VerdictBadge verdict={chunk.verdict} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[11px] text-gray-400 dark:text-slate-500">
          {chunk.grade != null && <span title="Gold relevance grade">grade {chunk.grade}</span>}
          {chunk.rank != null && <span title="Rank in the retriever's full list">rank {chunk.rank}</span>}
          {chunk.token_estimate != null && <span>~{chunk.token_estimate} tok</span>}
          {chunk.flags.map((f) => (
            <span
              key={f}
              className="px-1 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-300 font-medium"
            >
              {FLAG_LABEL[f] ?? f}
            </span>
          ))}
          {chunk.url ? (
            <a
              href={chunk.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-500 dark:text-indigo-400 hover:underline truncate max-w-[220px]"
              title={chunk.url}
            >
              {chunk.title || chunk.url}
            </a>
          ) : (
            chunk.title && <span className="truncate max-w-[220px]">{chunk.title}</span>
          )}
          <span className="font-mono text-gray-300 dark:text-slate-600 truncate max-w-[160px]" title={chunk.chunk_id}>
            {chunk.chunk_id}
          </span>
        </div>
        {chunk.content_preview && (
          <p className="mt-1 text-[12px] text-gray-600 dark:text-slate-300 line-clamp-3">
            {chunk.content_preview}
          </p>
        )}
      </div>
    </li>
  );
}

// Inline diagnosis for one case: fetches on mount, shows a verdict summary + the missed chunks.
export function CaseDiagnosisPanel({
  testId,
  k,
  retriever,
  goldSource,
}: {
  testId: string;
  k: number;
  retriever: string;
  goldSource: "human" | "ai" | "both";
}) {
  const [data, setData] = useState<CaseDiagnosisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(false);
    getCaseDiagnosis({ testId, k, retriever, goldSource }, ctrl.signal)
      .then((d) => setData(d))
      .catch(() => {
        if (!ctrl.signal.aborted) setError(true);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [testId, k, retriever, goldSource]);

  if (loading) {
    return <div className="px-4 py-3 text-xs text-gray-400 dark:text-slate-500">Diagnosing retrieval…</div>;
  }
  if (error) {
    return <div className="px-4 py-3 text-xs text-red-500">Could not run the diagnosis.</div>;
  }
  if (!data) return null;
  if (!data.provider_connected) {
    return (
      <div className="px-4 py-3 text-xs text-gray-500 dark:text-slate-400">
        Connect an index provider to diagnose retrieved chunks.
      </div>
    );
  }
  if (!data.available) {
    return (
      <div className="px-4 py-3 text-xs text-gray-500 dark:text-slate-400">
        No gold relevance labels for this case, so there is nothing to diagnose.{" "}
        <Link href={`/labeling/${encodeURIComponent(testId)}`} className="text-indigo-500 hover:underline">
          Judge chunks
        </Link>
      </div>
    );
  }

  const summaryEntries = Object.entries(data.summary).sort((a, b) => b[1] - a[1]);

  return (
    <div className="px-4 py-3 bg-gray-50/60 dark:bg-slate-800/20">
      <div className="flex items-center gap-2 flex-wrap text-[11px] text-gray-500 dark:text-slate-400 mb-2">
        <span className="font-medium text-gray-600 dark:text-slate-300">
          {data.retrieved_relevant_count}/{data.relevant_count} relevant found at k={data.k}
        </span>
        <span>·</span>
        <span>{data.missed_count} missed</span>
        {summaryEntries.map(([verdict, count]) => (
          <span key={verdict} className="inline-flex items-center gap-1">
            <VerdictBadge verdict={verdict} />
            <span className="tabular-nums">{count}</span>
          </span>
        ))}
        <Link
          href={`/labeling/${encodeURIComponent(testId)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-indigo-500 dark:text-indigo-400 hover:underline"
          title="Open this case in the labeling workbench to re-grade or fix labels"
        >
          Re-grade in Labeling ↗
        </Link>
      </div>
      {data.missed.length === 0 ? (
        <p className="text-xs text-emerald-600 dark:text-emerald-400">
          Every judged-relevant chunk was retrieved in the top {data.k}.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100/70 dark:divide-slate-800/70">
          {data.missed.map((c) => (
            <MissedRow key={c.chunk_id} chunk={c} />
          ))}
        </ul>
      )}
    </div>
  );
}
