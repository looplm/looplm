"use client";

import { useState } from "react";
import type { RagPipelineView, RagSource } from "@/lib/api-types/traces";
import StatusBadge from "@/components/status-badge";
import SmartViewer from "@/components/smart-viewer";
import { formatScore } from "@/components/compare-runs-badges";

/** One stage of the funnel header: a big count with a label. */
function FunnelStat({ value, label, tone = "default" }: { value: number; label: string; tone?: "default" | "muted" }) {
  return (
    <div className="text-center">
      <div className={`text-2xl font-bold ${tone === "muted" ? "text-gray-400 dark:text-slate-500" : ""}`}>{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-gray-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

function Arrow() {
  return <span className="text-gray-300 dark:text-slate-600 text-xl">→</span>;
}

/** Per-source row: citation marker, title, tool, and a score bar normalized to the set. */
function SourceRow({ source, maxScore }: { source: RagSource; maxScore: number }) {
  const selected = source.selected;
  const rate = source.score != null && maxScore > 0 ? source.score / maxScore : 0;
  const title = source.title || source.url || "untitled source";
  return (
    <div className={`flex items-center gap-3 py-1.5 ${selected ? "" : "opacity-50"}`}>
      <span
        className={`w-7 shrink-0 text-center text-[11px] font-mono rounded px-1 py-0.5 ${
          selected
            ? "bg-indigo-500/20 text-indigo-600 dark:text-indigo-300"
            : "bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500"
        }`}
        title={selected ? "Used in the final context" : "Found but not used in context"}
      >
        {source.citation_index != null ? `[${source.citation_index}]` : selected ? "✓" : "·"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer" className="text-sm truncate text-indigo-600 dark:text-indigo-400 hover:underline">
              {title}
            </a>
          ) : (
            <span className="text-sm truncate">{title}</span>
          )}
          {source.tool_name && (
            <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 font-mono">
              {source.tool_name.replace(/^mandatory-search-/, "")}
            </span>
          )}
        </div>
        {source.score != null && (
          <div className="h-1.5 mt-1 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
            <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.max(4, rate * 100)}%` }} />
          </div>
        )}
      </div>
      {source.score != null && (
        <span className="shrink-0 text-xs font-mono text-gray-500 dark:text-slate-400" title={source.score_scale ? `scale: ${source.score_scale}` : undefined}>
          {formatScore(source.score)}
        </span>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 first:mt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400 mb-2">{title}</h3>
      {children}
    </div>
  );
}

export default function RagPipeline({ view, compact = false }: { view: RagPipelineView; compact?: boolean }) {
  const [showContext, setShowContext] = useState(false);
  if (!view.available) return null;

  const sources = view.sources ?? [];
  const queries = view.queries ?? [];
  const corrections = view.judge?.corrections ?? [];
  const maxScore = sources.reduce((m, s) => Math.max(m, s.score ?? 0), 0);
  const anyInferred = sources.some((s) => s.selected && !s.selection_exact);
  const funnel = view.search;

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">RAG Pipeline</h2>
        {view.query_complexity && (
          <span className="text-[11px] px-2 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
            {view.query_complexity}
          </span>
        )}
      </div>

      {/* Funnel header */}
      <div className="flex items-center justify-center gap-6 py-3 rounded-lg bg-gray-50 dark:bg-slate-800/40">
        <FunnelStat value={view.counts?.found ?? 0} label="found" />
        <Arrow />
        <FunnelStat value={view.counts?.used_in_context ?? 0} label="in context" />
        <Arrow />
        <FunnelStat value={view.counts?.cited ?? 0} label="cited" tone="muted" />
      </div>

      {/* Queries */}
      {queries.length > 0 && (
        <Section title={`Queries (${queries.length})`}>
          <div className="flex flex-wrap gap-2">
            {queries.map((q, i) => (
              <span key={i} className="text-xs px-2 py-1 rounded-full bg-indigo-500/10 text-indigo-700 dark:text-indigo-300">
                {q}
              </span>
            ))}
          </div>
        </Section>
      )}

      {/* Search funnel */}
      {funnel && (
        <Section title="Retrieval">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-600 dark:text-slate-300">
            {funnel.search_call_count != null && <span>{funnel.search_call_count} search calls</span>}
            {funnel.summary_pages != null && (<><Arrow /><span>{funnel.summary_pages} summary pages</span></>)}
            {funnel.chunk_results != null && (<><Arrow /><span>{funnel.chunk_results} chunks</span></>)}
            {funnel.broadened && <span className="ml-2 text-[11px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-400">broadened</span>}
          </div>
          {funnel.candidates_before_filter != null && (
            <div className="mt-1 text-xs text-gray-500 dark:text-slate-400">
              {funnel.candidates_before_filter} candidates →{" "}
              {(funnel.dropped_by_relative_filter ?? 0) + (funnel.dropped_by_absolute_floor ?? 0)} dropped →{" "}
              {funnel.kept ?? "?"} kept
            </div>
          )}
        </Section>
      )}

      {/* Sources */}
      {sources.length > 0 && (
        <Section title={`Sources (${sources.length})`}>
          <div className="divide-y divide-gray-100/60 dark:divide-slate-800/60">
            {sources.map((s, i) => (
              <SourceRow key={i} source={s} maxScore={maxScore} />
            ))}
          </div>
          {anyInferred && (
            <p className="mt-2 text-[11px] text-gray-400 dark:text-slate-500">
              “In context” / citation markers inferred from the grounding judge’s source order — not logged explicitly upstream.
            </p>
          )}
        </Section>
      )}

      {/* Judge */}
      {view.judge && (view.judge.passed != null || corrections.length > 0) && (
        <Section title="Grounding judge">
          <div className="flex items-center gap-2">
            <StatusBadge status={view.judge.passed ? "success" : "failure"} />
            <span className="text-sm text-gray-600 dark:text-slate-300">
              {view.judge.passed ? "passed" : "failed"}
              {corrections.length > 0 && ` · ${corrections.length} correction(s)`}
            </span>
          </div>
          {corrections.length > 0 && (
            <ul className="mt-2 space-y-1">
              {corrections.map((c, i) => (
                <li key={i} className="text-xs text-gray-500 dark:text-slate-400">
                  <span className="font-mono text-amber-600 dark:text-amber-400">{c.type}</span>
                  {c.reason ? ` — ${c.reason}` : ""}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {/* Answer + assembled context (full view only) */}
      {!compact && (view.answer || view.assembled_context) && (
        <Section title="Generation">
          {view.answer_model && (
            <p className="text-xs text-gray-400 dark:text-slate-500 mb-2">
              {view.answer_model}
              {(view.answer_tokens_in != null || view.answer_tokens_out != null) &&
                ` · ${view.answer_tokens_in ?? 0}→${view.answer_tokens_out ?? 0} tokens`}
            </p>
          )}
          {view.answer && <SmartViewer data={view.answer as unknown as object} title="Answer" />}
          {view.assembled_context && (
            <div className="mt-3">
              <button
                onClick={() => setShowContext((v) => !v)}
                className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                {showContext ? "▼" : "▶"} Assembled context
              </button>
              {showContext && (
                <pre className="mt-2 max-h-96 overflow-auto text-xs whitespace-pre-wrap rounded-lg bg-gray-50 dark:bg-slate-800/40 p-3 text-gray-600 dark:text-slate-300">
                  {view.assembled_context}
                </pre>
              )}
            </div>
          )}
        </Section>
      )}
    </div>
  );
}
