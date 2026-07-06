"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  getCaseDiagnosis,
  getChunkMetadata,
  type CaseDiagnosisResponse,
  type DiagnosedChunk,
} from "@/lib/api";
import { pickIndexText } from "@/components/labeling/chunk-row";

// Deep-link to the labeling workbench for a case, scoped to its dataset so the view resolves it
// (the labeling page finds a case within a dataset — without ?dataset= it only works for the
// default/latest dataset, which is why the link "didn't always work").
function regradeHref(testId: string, datasetId?: string | null): string {
  const base = `/labeling/${encodeURIComponent(testId)}`;
  return datasetId ? `${base}?dataset=${encodeURIComponent(datasetId)}` : base;
}

// Big text / vector fields are shown separately (or not at all) — hide them from the field list.
const TEXT_FIELD_KEYS = new Set(["chunk_text", "content", "text", "chunkText"]);

function isVectorValue(v: unknown): boolean {
  return Array.isArray(v) && v.length > 16 && typeof v[0] === "number";
}

function formatFieldValue(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

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

const FLAG_HINT: Record<string, string> = {
  tiny: "Very short chunk (< ~40 tokens) — too little text to carry a retrievable idea.",
  giant: "Very long chunk — many embedding models truncate it, so the tail isn't represented in the vector.",
  mojibake: "Mis-decoded characters (e.g. 'Ã¼' for 'ü') that break both keyword and embedding matching.",
  table_heavy: "Dominated by table markup (pipes/tabs), which embeds and retrieves poorly.",
  markup_heavy: "Raw HTML/markup tags left in the text, diluting the content.",
  missing_embedding: "The chunk has no vector, so vector/hybrid search can never find it.",
  empty: "The chunk has no text content.",
};

// Instant hover tooltip (the native `title` has a ~1s delay). Fixed-positioned so it escapes the
// scrollable table's clipping, mirroring the `Info` component elsewhere on the page.
function HoverTip({ text, children }: { text: string; children: ReactNode }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  return (
    <>
      <span
        className="inline-flex cursor-help"
        onMouseEnter={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setPos({ x: r.left + r.width / 2, y: r.top });
        }}
        onMouseLeave={() => setPos(null)}
      >
        {children}
      </span>
      {pos && (
        <span
          className="fixed z-50 w-64 -translate-x-1/2 -translate-y-full whitespace-normal rounded-lg bg-slate-900 dark:bg-slate-800 px-3 py-2 text-left text-[11px] font-normal normal-case leading-snug tracking-normal text-slate-100 shadow-xl ring-1 ring-black/10 pointer-events-none"
          style={{ left: pos.x, top: pos.y - 8 }}
        >
          {text}
        </span>
      )}
    </>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = VERDICT[verdict] ?? { label: verdict, cls: "bg-gray-500/10 text-gray-500", hint: "" };
  return (
    <HoverTip text={v.hint || v.label}>
      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${v.cls}`}>
        {v.label}
      </span>
    </HoverTip>
  );
}

function MissedRow({ chunk }: { chunk: DiagnosedChunk }) {
  const [expanded, setExpanded] = useState(false);
  const [fields, setFields] = useState<Record<string, unknown> | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "loaded">("idle");

  // Lazily pull the full chunk (all index fields) the first time it's expanded.
  const load = () => {
    if (state !== "idle") return;
    setState("loading");
    getChunkMetadata(chunk.chunk_id)
      .then((r) => setFields(r.fields ?? null))
      .catch(() => setFields(null))
      .finally(() => setState("loaded"));
  };

  const fullText = pickIndexText(fields) ?? chunk.content_preview ?? "";
  const metaEntries = fields
    ? Object.entries(fields).filter(
        ([k, v]) => !TEXT_FIELD_KEYS.has(k) && v != null && v !== "" && !isVectorValue(v),
      )
    : [];

  return (
    <li className="py-2">
      <div className="flex items-start gap-2">
        <VerdictBadge verdict={chunk.verdict} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap text-[11px] text-gray-400 dark:text-slate-500">
            {chunk.grade != null && <span title="Gold relevance grade">grade {chunk.grade}</span>}
            {chunk.rank != null && <span title="Rank in the retriever's full list">rank {chunk.rank}</span>}
            {chunk.token_estimate != null && <span>~{chunk.token_estimate} tok</span>}
            {chunk.flags.map((f) => (
              <HoverTip key={f} text={FLAG_HINT[f] ?? f}>
                <span className="px-1 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-300 font-medium">
                  {FLAG_LABEL[f] ?? f}
                </span>
              </HoverTip>
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

          {expanded && state === "loading" ? (
            <p className="mt-1 text-[12px] italic text-gray-400 dark:text-slate-500">Loading full chunk…</p>
          ) : (expanded ? fullText : chunk.content_preview) ? (
            <p
              className={`mt-1 text-[12px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap ${
                expanded ? "" : "line-clamp-3"
              }`}
            >
              {expanded ? fullText : chunk.content_preview}
            </p>
          ) : null}

          {expanded && state === "loaded" && (
            metaEntries.length > 0 ? (
              <dl className="mt-2 grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 rounded-md border border-gray-100 dark:border-slate-800 bg-white/60 dark:bg-slate-900/40 p-2 text-[11px]">
                {metaEntries.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-gray-400 dark:text-slate-500 truncate" title={k}>{k}</dt>
                    <dd className="text-gray-600 dark:text-slate-300 break-words">{formatFieldValue(v)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="mt-1 text-[11px] italic text-gray-400 dark:text-slate-500">
                Not found in the index (stale label, re-indexed, or deleted).
              </p>
            )
          )}

          <button
            type="button"
            onClick={() => {
              const next = !expanded;
              setExpanded(next);
              if (next) load();
            }}
            className="mt-1 text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            {expanded ? "Show less" : "Show full chunk & fields"}
          </button>
        </div>
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
  minGrade,
}: {
  testId: string;
  k: number;
  retriever: string;
  goldSource: "human" | "ai" | "both";
  // Binary-metrics strictness: the miss list only contains chunks with gold grade >= minGrade.
  minGrade?: number;
}) {
  const [data, setData] = useState<CaseDiagnosisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(false);
    getCaseDiagnosis({ testId, k, retriever, goldSource, minGrade }, ctrl.signal)
      .then((d) => setData(d))
      .catch(() => {
        if (!ctrl.signal.aborted) setError(true);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [testId, k, retriever, goldSource, minGrade]);

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
        <Link href={regradeHref(testId, data.dataset_id)} className="text-indigo-500 hover:underline">
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
          href={regradeHref(testId, data.dataset_id)}
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
