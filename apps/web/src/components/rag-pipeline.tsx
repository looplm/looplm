"use client";

import { Fragment, useState } from "react";
import type { RagPipelineView, RagSource } from "@/lib/api-types/traces";
import SmartViewer from "@/components/smart-viewer";
import Tooltip from "@/components/tooltip";
import { formatScore } from "@/components/compare-runs-badges";

/** Small circled-"i" that reveals `content` on hover — for column-header explanations. */
function InfoIcon({ content }: { content: React.ReactNode }) {
  return (
    <Tooltip content={content}>
      <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-current text-[9px] font-medium leading-none text-gray-400 dark:text-slate-500 cursor-help align-middle">
        i
      </span>
    </Tooltip>
  );
}

const SCORE_HELP = (
  <span>
    How relevant retrieval judged this source — higher is better. The bar shows it relative to the
    top result in each group. Scores come from the semantic reranker and are then lifted by
    title/team-match boosts, so strong matches often read above 4. Hybrid results (rrf, bm25) use a
    different scale, tagged next to the number.
  </span>
);

/** Friendly label + display order for each retrieval tier (by source tool_name). */
const TIERS: { match: (t: string) => boolean; label: string; order: number }[] = [
  { match: (t) => t.includes("chunk"), label: "Chunks (reranked)", order: 0 },
  { match: (t) => t.includes("summ"), label: "Page summaries", order: 1 },
  { match: (t) => t.includes("full-page"), label: "Full pages", order: 2 },
  { match: (t) => t.includes("pdf"), label: "PDF attachments", order: 3 },
  { match: (t) => t.includes("web"), label: "Web pages", order: 4 },
];

function tierInfo(toolName: string | null | undefined) {
  const t = (toolName || "").toLowerCase();
  return TIERS.find((x) => x.match(t)) ?? { label: toolName || "Sources", order: 9 };
}

function FunnelStat({ value, label, hint, tone = "default" }: { value: number; label: string; hint: string; tone?: "default" | "muted" }) {
  return (
    <div className="text-center" title={hint}>
      <div className={`text-2xl font-bold ${tone === "muted" ? "text-gray-400 dark:text-slate-500" : ""}`}>{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-gray-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

function Arrow() {
  return <span className="text-gray-300 dark:text-slate-600 text-xl">→</span>;
}

/** Compact ▲/▼ indicator for a source's rank change due to reranking. */
function RerankDelta({ before, after }: { before: number; after: number }) {
  const delta = before - after; // positive → moved up (promoted)
  const cls = delta > 0 ? "text-green-600 dark:text-green-400" : delta < 0 ? "text-red-600 dark:text-red-400" : "text-gray-400 dark:text-slate-500";
  const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "—";
  return (
    <span className={`shrink-0 text-[11px] font-mono tabular-nums ${cls}`} title={`Reranking moved this from #${before} to #${after}`}>
      {arrow}
      {delta !== 0 ? Math.abs(delta) : ""}
    </span>
  );
}

function SourceRow({ source, maxScore }: { source: RagSource; maxScore: number }) {
  const selected = source.selected;
  const rate = source.score != null && maxScore > 0 ? source.score / maxScore : 0;
  const title = source.title || source.url || "untitled source";
  const hasRank = source.rank_before != null && source.rank_after != null;
  return (
    <div className={`flex items-center gap-3 py-1.5 ${selected ? "" : "opacity-50"}`}>
      <span
        className={`w-7 shrink-0 text-center text-[11px] font-mono rounded px-1 py-0.5 ${
          selected ? "bg-indigo-500/20 text-indigo-600 dark:text-indigo-300" : "bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500"
        }`}
        title={selected ? "Placed into the model's context" : "Found but not used in context"}
      >
        {source.citation_index != null ? `[${source.citation_index}]` : selected ? "✓" : "·"}
      </span>
      {hasRank && <RerankDelta before={source.rank_before!} after={source.rank_after!} />}
      <div className="min-w-0 flex-1">
        {source.url ? (
          <a href={source.url} target="_blank" rel="noreferrer" className="block text-sm truncate text-indigo-600 dark:text-indigo-400 hover:underline">
            {title}
          </a>
        ) : (
          <span className="block text-sm truncate">{title}</span>
        )}
        {source.score != null && (
          <div className="h-1.5 mt-1 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
            <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.max(4, rate * 100)}%` }} />
          </div>
        )}
      </div>
      {source.score != null && (
        <span className="shrink-0 text-xs font-mono text-gray-500 dark:text-slate-400">
          {formatScore(source.score)}
          {source.score_scale && <span className="ml-1 text-[9px] uppercase text-gray-400 dark:text-slate-600">{source.score_scale}</span>}
        </span>
      )}
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 first:mt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400 mb-1">{title}</h3>
      {hint && <p className="text-xs text-gray-400 dark:text-slate-500 mb-2">{hint}</p>}
      {children}
    </div>
  );
}

export default function RagPipeline({ view, compact = false }: { view: RagPipelineView; compact?: boolean }) {
  const [showContext, setShowContext] = useState(false);
  const allSources = view.sources ?? [];
  const hasSelected = allSources.some((s) => s.selected);
  const [showAll, setShowAll] = useState(!hasSelected);
  if (!view.available) return null;

  const queries = view.queries ?? [];
  const corrections = view.judge?.corrections ?? [];
  const funnel = view.search;
  const anyRerank = allSources.some((s) => s.rank_before != null && s.rank_after != null);

  // In-context sources read best in the order the model saw them (citation order); the
  // rest ("found, not used" — mostly the summary/discovery tier) are grouped by tier and
  // ranked, revealed on demand.
  const inContext = allSources
    .filter((s) => s.selected)
    .sort((a, b) => {
      const ca = a.citation_index ?? Number.MAX_SAFE_INTEGER;
      const cb = b.citation_index ?? Number.MAX_SAFE_INTEGER;
      return ca !== cb ? ca - cb : (b.score ?? 0) - (a.score ?? 0);
    });
  const inCtxMax = inContext.reduce((m, s) => Math.max(m, s.score ?? 0), 0);

  const foundGroups = new Map<string, { label: string; order: number; rows: RagSource[]; max: number }>();
  for (const s of allSources.filter((s) => !s.selected)) {
    const info = tierInfo(s.tool_name);
    const g = foundGroups.get(info.label) ?? { label: info.label, order: info.order, rows: [], max: 0 };
    g.rows.push(s);
    g.max = Math.max(g.max, s.score ?? 0);
    foundGroups.set(info.label, g);
  }
  const orderedFoundGroups = [...foundGroups.values()].sort((a, b) => a.order - b.order);
  const foundCount = allSources.length - inContext.length;

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold">RAG Pipeline</h2>
        {view.query_complexity && (
          <span className="text-[11px] px-2 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">{view.query_complexity}</span>
        )}
      </div>
      <p className="text-xs text-gray-400 dark:text-slate-500 mb-4">How the answer was retrieved, ranked, and grounded.</p>

      {/* Funnel header */}
      <div className="flex items-center justify-center gap-6 py-3 rounded-lg bg-gray-50 dark:bg-slate-800/40">
        <FunnelStat value={view.counts?.found ?? 0} label="found" hint="Sources returned by retrieval" />
        <Arrow />
        <FunnelStat value={view.counts?.used_in_context ?? 0} label="in context" hint="Sources placed into the model's prompt" />
        <Arrow />
        <FunnelStat value={view.counts?.cited ?? 0} label="cited" tone="muted" hint="Sources actually referenced in the answer" />
      </div>
      <p className="text-center text-xs text-gray-400 dark:text-slate-500 mt-2">
        {view.counts?.found ?? 0} retrieved → {view.counts?.used_in_context ?? 0} placed in the model&apos;s context → {view.counts?.cited ?? 0} cited in the answer
      </p>

      {/* Queries */}
      {queries.length > 0 && (
        <Section title={`Queries (${queries.length})`} hint="Search queries expanded from the user's question.">
          <div className="flex flex-wrap gap-2">
            {queries.map((q, i) => (
              <span key={i} className="text-xs px-2 py-1 rounded-full bg-indigo-500/10 text-indigo-700 dark:text-indigo-300">{q}</span>
            ))}
          </div>
        </Section>
      )}

      {/* Retrieval */}
      {funnel && !compact && (
        <Section title="Retrieval">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-600 dark:text-slate-300">
            {funnel.search_call_count != null && <span>{funnel.search_call_count} search calls</span>}
            {funnel.summary_pages != null && (<><Arrow /><span>{funnel.summary_pages} summary pages</span></>)}
            {funnel.chunk_results != null && (<><Arrow /><span>{funnel.chunk_results} chunks</span></>)}
            {funnel.broadened && <span className="ml-2 text-[11px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-400">broadened</span>}
          </div>
          {funnel.candidates_before_filter != null && (
            <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">
              Relevance filter: {funnel.candidates_before_filter} candidates →{" "}
              {(funnel.dropped_by_relative_filter ?? 0) + (funnel.dropped_by_absolute_floor ?? 0)} dropped →{" "}
              {funnel.kept ?? "?"} kept
            </p>
          )}
        </Section>
      )}

      {/* Sources */}
      {allSources.length > 0 && (
        <div className="mt-5">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400 mb-2">
            Sources ({view.counts?.used_in_context ?? 0} in context / {allSources.length} found)
            <InfoIcon
              content={
                <span className="block space-y-1">
                  <span className="block"><span className="font-mono">[N]</span> — the order this source was placed into the model’s context (its citation marker), shown in that order.</span>
                  {anyRerank && <span className="block"><span className="text-green-600 dark:text-green-400">▲</span>/<span className="text-red-600 dark:text-red-400">▼</span> — rank change from reranking.</span>}
                  <span className="block">A <span className="font-mono">···</span> gap is a context slot we couldn’t match to a retrieved row on this trace (matched by URL upstream) — not a source the judge removed. Numbering is exact once the app logs citation indices directly.</span>
                </span>
              }
            />
          </h3>

          {/* In context — ordered by citation number */}
          {inContext.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] font-medium text-gray-500 dark:text-slate-400">In context</span>
                <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
                  Score
                  <InfoIcon content={SCORE_HELP} />
                </span>
              </div>
              <div className="divide-y divide-gray-100/60 dark:divide-slate-800/60">
                {inContext.map((s, i) => {
                  const prevIdx = i === 0 ? 0 : inContext[i - 1]?.citation_index ?? null;
                  const gap =
                    s.citation_index != null && prevIdx != null && s.citation_index - prevIdx > 1
                      ? s.citation_index - prevIdx - 1
                      : 0;
                  return (
                    <Fragment key={i}>
                      {gap > 0 && (
                        <div className="flex items-center gap-2 py-1 pl-7 text-[11px] text-gray-400 dark:text-slate-500">
                          <span className="font-mono tracking-widest">···</span>
                          <span>{gap} more in context, not matched to a retrieved row</span>
                        </div>
                      )}
                      <SourceRow source={s} maxScore={inCtxMax} />
                    </Fragment>
                  );
                })}
              </div>
            </div>
          )}

          {/* Found but not used (mostly the discovery/summary tier) */}
          {foundCount > 0 && (
            <>
              <button
                onClick={() => setShowAll((v) => !v)}
                className="mt-3 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                {showAll ? "Hide sources not used" : `Show ${foundCount} found but not used`}
              </button>
              {showAll && (
                <div className="mt-2 space-y-3">
                  {orderedFoundGroups.map((g) => (
                    <div key={g.label}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] font-medium text-gray-500 dark:text-slate-400">{g.label}</span>
                        <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
                          Score
                          <InfoIcon content={SCORE_HELP} />
                        </span>
                      </div>
                      <div className="divide-y divide-gray-100/60 dark:divide-slate-800/60">
                        {g.rows.map((s, i) => (
                          <SourceRow key={i} source={s} maxScore={g.max} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Judge */}
      {view.judge && (view.judge.passed != null || corrections.length > 0) && (
        <Section
          title="Grounding judge"
          hint="An LLM checks the draft answer against the sources and fixes ungrounded statements or wrong citations before replying — the answer shown is already corrected."
        >
          <div className="flex items-center gap-2">
            <span
              className={`text-[11px] px-2 py-0.5 rounded font-medium ${
                view.judge.passed
                  ? "bg-green-500/15 text-green-700 dark:text-green-400"
                  : "bg-amber-500/15 text-amber-700 dark:text-amber-400"
              }`}
            >
              {view.judge.passed ? "Grounded" : "Corrections applied"}
            </span>
            <span className="text-sm text-gray-600 dark:text-slate-300">
              {view.judge.passed
                ? "no changes needed"
                : `${corrections.length} grounding/citation fix${corrections.length === 1 ? "" : "es"}`}
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

      {/* Generation (full view only) */}
      {!compact && (view.answer || view.assembled_context) && (
        <Section title="Generation">
          {view.answer_model && (
            <p className="text-xs text-gray-400 dark:text-slate-500 mb-2">
              {view.answer_model}
              {(view.answer_tokens_in != null || view.answer_tokens_out != null) && ` · ${view.answer_tokens_in ?? 0}→${view.answer_tokens_out ?? 0} tokens`}
            </p>
          )}
          {view.answer && <SmartViewer data={view.answer as unknown as object} title="Answer" />}
          {view.assembled_context && (
            <div className="mt-3">
              <button onClick={() => setShowContext((v) => !v)} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
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
