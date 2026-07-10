"use client";

/**
 * Renderers for the extended chunk-quality families (boundary, standalone,
 * cohesion, retrieval frequency, claim boundaries). Sibling of family-cards.tsx,
 * split so neither file crosses the size cap.
 */

import type {
  BoundaryFamily,
  ClaimBoundaryFamily,
  CohesionFamily,
  PassUsage,
  RetrievalFrequencyFamily,
  StandaloneFamily,
} from "@/lib/api-types/chunk-quality";

import { FlaggedChunks } from "./flagged-chunks";
import { Bar, Explainer, fmtPct, Metric } from "./shared";

const numberFmt = (v: number | undefined) =>
  v === undefined ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 0 });

function Unavailable({ reason }: { reason?: string }) {
  return (
    <p className="text-sm text-gray-400 dark:text-slate-500">
      {reason ?? "This pass did not run."}
    </p>
  );
}

function UsageNote({ usage }: { usage?: PassUsage }) {
  if (!usage) return null;
  const cost = usage.cost_usd === null ? "" : ` · $${usage.cost_usd.toFixed(4)}`;
  return (
    <p className="text-[11px] text-gray-400 dark:text-slate-500">
      {usage.total_tokens.toLocaleString()} tokens{cost}
    </p>
  );
}

// ── Boundary quality ─────────────────────────────────────────────────────────

export function BoundaryCard({ boundary }: { boundary: BoundaryFamily }) {
  if (!boundary.available) return <Unavailable reason={boundary.reason} />;
  return (
    <div className="space-y-4">
      <Explainer>
        Checks where the chunker cuts the text. A chunk that starts lowercase or on a comma
        continues a sentence that lives in the previous chunk; one that ends without punctuation
        was cut off mid-thought. Split tables and numbered steps severed across two chunks (step 2
        ends one chunk, step 3 opens the next) mean a reader of a single retrieved chunk gets half
        the information. High numbers here usually mean the splitter cuts at a size limit instead
        of at sentence or section boundaries.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric label="End mid-content" value={fmtPct(boundary.bad_end_pct)} sub={`${numberFmt(boundary.bad_end)} chunks`} />
        <Metric label="Start mid-sentence" value={fmtPct(boundary.bad_start_pct)} sub={`${numberFmt(boundary.bad_start)} chunks`} />
        <Metric label="Split tables" value={fmtPct(boundary.mid_table_pct)} />
        <Metric label="Mid-list starts" value={fmtPct(boundary.mid_list_pct)} />
        <Metric
          label="Severed steps"
          value={numberFmt(boundary.severed_steps)}
          sub={`${numberFmt(boundary.adjacent_pairs_checked)} pairs checked`}
        />
      </div>
      <FlaggedChunks
        items={(boundary.examples ?? []).map((e) => ({
          id: e.chunk_id,
          label: e.issue.replace(/_/g, " "),
          snippet: e.snippet,
        }))}
      />
    </div>
  );
}

// ── Standalone interpretability ──────────────────────────────────────────────

export function StandaloneCard({
  standalone,
  usage,
}: {
  standalone: StandaloneFamily;
  usage?: PassUsage;
}) {
  if (!standalone.available) return <Unavailable reason={standalone.reason} />;
  return (
    <div className="space-y-4">
      <Explainer>
        Search returns each chunk on its own, without the page around it. Here an LLM reads a
        sample of chunks exactly that way and asks: can this be understood standalone? A chunk
        like &quot;In this case the dose is halved&quot; fails because nothing in the chunk says
        which case is meant. Context-dependent chunks are wasted index space: even when retrieval
        finds them, the answer model cannot safely use them. This percentage is the single best
        number to compare chunking strategies on.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric
          label="Context-dependent"
          value={fmtPct(standalone.dependent_pct)}
          sub={`${numberFmt(standalone.dependent)} of ${numberFmt(standalone.judged)} judged`}
        />
        <Metric label="Judged" value={numberFmt(standalone.judged)} sub={`of ${numberFmt(standalone.sampled)} sampled`} />
      </div>
      <div className="max-w-sm">
        <Bar
          pct={standalone.dependent_pct ?? 0}
          tone={(standalone.dependent_pct ?? 0) >= 40 ? "bad" : (standalone.dependent_pct ?? 0) >= 20 ? "warn" : "good"}
        />
        <p className="text-[11px] text-gray-400 dark:text-slate-500 mt-1">
          Share of chunks that depend on unstated surrounding context. Track this across chunker
          versions.
        </p>
      </div>
      <FlaggedChunks
        items={(standalone.examples ?? []).map((e) => ({
          id: e.chunk_id,
          label: e.reason,
          snippet: e.snippet,
        }))}
      />
      <UsageNote usage={usage} />
    </div>
  );
}

// ── Embedding cohesion ───────────────────────────────────────────────────────

export function CohesionCard({ cohesion }: { cohesion: CohesionFamily }) {
  if (!cohesion.available) return <Unavailable reason={cohesion.reason} />;
  const smear = cohesion.smear ?? { count: 0 };
  return (
    <div className="space-y-4">
      <Explainer>
        A chunk is found by comparing one vector (its embedding) against the question. When a
        chunk mixes several topics, that single vector becomes an average of all of them and
        matches no specific question well. To measure this, each sentence of the chunk is embedded
        separately and the spread between the sentence vectors is computed: 0 means every sentence
        is about the same thing, higher values mean the sentences drift apart. Chunks above the
        threshold likely want splitting into one-topic pieces. Compare values within this index
        rather than as absolutes; the natural baseline varies by embedding model and language.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric
          label="Multi-topic chunks"
          value={fmtPct(cohesion.high_spread_pct)}
          sub={`spread ≥ ${cohesion.threshold ?? "—"}`}
        />
        <Metric
          label="Median spread"
          value={smear.p50 ?? "—"}
          sub="0 = one topic, 1 = unrelated"
        />
        <Metric
          label="Scored"
          value={numberFmt(cohesion.scored)}
          sub={`${numberFmt(cohesion.sentences_embedded)} sentences embedded`}
        />
      </div>
      <FlaggedChunks
        items={(cohesion.examples ?? []).map((e) => ({
          id: e.chunk_id,
          label: `spread ${e.smear}`,
          snippet: e.snippet,
        }))}
      />
    </div>
  );
}

// ── Retrieval frequency ──────────────────────────────────────────────────────

export function RetrievalFrequencyCard({ freq }: { freq: RetrievalFrequencyFamily }) {
  if (!freq.available) return <Unavailable reason={freq.reason} />;
  const maxBucket = Math.max(1, ...(freq.histogram ?? []).map((b) => b.count));
  const sourceLabel =
    freq.source === "probe"
      ? "keyword probe"
      : `traces, last ${freq.window_days ?? "?"} days`;
  return (
    <div className="space-y-4">
      <Explainer>
        Counts how often each sampled chunk actually appeared in retrieval results. Both extremes
        point at problems. Dead chunks were never retrieved once: they are junk, badly indexed, or
        content nobody asks about, and they still dilute every search. Hot chunks show up for a
        large share of all queries regardless of topic; that is usually boilerplate (intros,
        disclaimers) generic enough to match everything, crowding better results out of the top
        spots.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric label="Dead chunks" value={fmtPct(freq.dead_pct)} sub={`${numberFmt(freq.dead)} never retrieved`} />
        <Metric label="Hot chunks" value={numberFmt(freq.hot)} sub={`≥ ${numberFmt(freq.hot_threshold)} events`} />
        <Metric label="Events scanned" value={numberFmt(freq.events_scanned)} sub={sourceLabel} />
        <Metric label="Unique chunks retrieved" value={numberFmt(freq.unique_chunks_retrieved)} />
      </div>

      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
          Retrieval count per sampled chunk
        </p>
        <div className="space-y-1">
          {(freq.histogram ?? []).map((b) => (
            <div key={b.label} className="flex items-center gap-2 text-xs">
              <span className="w-20 text-right text-gray-500 dark:text-slate-400">{b.label}</span>
              <div className="flex-1">
                <Bar pct={(b.count / maxBucket) * 100} tone={b.label === "0" ? "warn" : undefined} />
              </div>
              <span className="w-14 text-gray-600 dark:text-slate-300">{numberFmt(b.count)}</span>
            </div>
          ))}
        </div>
      </div>

      {(freq.top_hot ?? []).length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
            Hottest chunks
          </p>
          <ul className="space-y-0.5">
            {(freq.top_hot ?? []).map((h) => (
              <li key={h.chunk_id} className="flex items-center gap-2 text-xs">
                <span className="w-10 text-right font-semibold">{h.count}×</span>
                <span className="truncate text-gray-600 dark:text-slate-300">
                  {h.title || h.chunk_id}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Claim boundaries ─────────────────────────────────────────────────────────

export function ClaimBoundaryCard({
  claims,
  usage,
}: {
  claims: ClaimBoundaryFamily;
  usage?: PassUsage;
}) {
  if (!claims.available) return <Unavailable reason={claims.reason} />;
  return (
    <div className="space-y-4">
      <Explainer>
        Takes known-good answers from your test dataset, splits each into its individual facts,
        and checks per fact: does one single chunk contain the full evidence for it? A fact whose
        evidence is spread over two chunks (cross-boundary) forces the system to retrieve both
        halves and stitch them together, which often fails. When the two halves are adjacent
        chunks of the same document, the chunker itself cut through the fact; a coarser chunking
        would fix it. Unsupported means no combination of the labeled chunks backs the fact at
        all.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric
          label="Cross-boundary claims"
          value={fmtPct(claims.cross_boundary_pct)}
          sub={`${numberFmt(claims.cross_boundary)} of ${numberFmt(claims.claims_total)} claims`}
        />
        <Metric
          label="Across adjacent chunks"
          value={numberFmt(claims.cross_adjacent)}
          sub="split by the chunker itself"
        />
        <Metric label="Single-chunk" value={numberFmt(claims.single_chunk)} />
        <Metric label="Unsupported" value={numberFmt(claims.unsupported)} />
        <Metric
          label="Cases"
          value={numberFmt(claims.cases_analyzed)}
          sub={`${numberFmt(claims.cases_skipped)} skipped`}
        />
      </div>
      {(claims.examples ?? []).length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
            Claims needing multiple chunks
          </p>
          <ul className="space-y-1.5">
            {(claims.examples ?? []).map((e, i) => (
              <li key={i} className="text-xs">
                <span className="text-gray-600 dark:text-slate-300">{e.claim}</span>{" "}
                <span className="text-gray-400 dark:text-slate-500 font-mono">
                  [{e.chunk_ids.join(", ")}]
                </span>
                {e.adjacent && (
                  <span className="ml-1 px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                    adjacent
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <UsageNote usage={usage} />
    </div>
  );
}
