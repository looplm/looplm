"use client";

import type {
  ContentFamily,
  DuplicationFamily,
  MetadataFamily,
  SizeFamily,
} from "@/lib/api-types/chunk-quality";

import { Bar, Explainer, fmtPct, Metric } from "./shared";

const numberFmt = (v: number | undefined) =>
  v === undefined ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 0 });

// ── Size & consistency ───────────────────────────────────────────────────────

export function SizeCard({ size }: { size: SizeFamily }) {
  if (!size.available) return <Unavailable reason="No chunk-body field was detected in this index." />;
  const t = size.tokens ?? { count: 0 };
  const maxBucket = Math.max(1, ...(size.histogram ?? []).map((b) => b.count));
  const groups = Object.entries(size.by_group ?? {});
  return (
    <div className="space-y-4">
      <Explainer>
        Chunks are the text snippets your search retrieves, and their length matters. Chunks under
        about 40 tokens (roughly 30 words) rarely contain enough information to be found or to
        answer anything; chunks over about 1200 tokens get cut off by the embedding model, so
        their later content becomes invisible to search. A pile-up at one size usually means the
        splitter is cutting at a hard limit instead of at natural boundaries.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric label="Median tokens" value={numberFmt(t.p50)} sub={`p95 ${numberFmt(t.p95)}`} />
        <Metric label="Mean" value={numberFmt(t.mean)} sub={`±${numberFmt(t.stdev)}`} />
        <Metric label="Consistency (CV)" value={t.cv ?? "—"} sub={t.cv && t.cv >= 0.8 ? "high variance" : "stable"} />
        <Metric label="Empty" value={fmtPct(size.empty_pct)} />
        <Metric label="Tiny (<40 tok)" value={fmtPct(size.tiny_pct)} />
        <Metric label="Oversized" value={fmtPct(size.giant_pct)} />
      </div>

      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">Token-length distribution</p>
        <div className="space-y-1">
          {(size.histogram ?? []).map((b) => (
            <div key={b.label} className="flex items-center gap-2 text-xs">
              <span className="w-20 text-right text-gray-500 dark:text-slate-400">{b.label}</span>
              <div className="flex-1">
                <Bar pct={(b.count / maxBucket) * 100} />
              </div>
              <span className="w-14 text-gray-600 dark:text-slate-300">{numberFmt(b.count)}</span>
            </div>
          ))}
        </div>
      </div>

      {groups.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
            By {size.group_field ?? "group"}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-gray-400 dark:text-slate-500">
                <tr>
                  <th className="text-left font-normal py-1">Value</th>
                  <th className="text-right font-normal">Chunks</th>
                  <th className="text-right font-normal">Median tok</th>
                  <th className="text-right font-normal">CV</th>
                </tr>
              </thead>
              <tbody>
                {groups.map(([g, v]) => (
                  <tr key={g} className="border-t border-gray-50 dark:border-slate-800/50">
                    <td className="py-1 truncate max-w-[16rem]">{g}</td>
                    <td className="text-right">{numberFmt(v.count)}</td>
                    <td className="text-right">{numberFmt(v.median)}</td>
                    <td className={`text-right ${v.cv >= 0.8 ? "text-amber-600 dark:text-amber-400" : ""}`}>{v.cv}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Duplication & overlap ──────────────────────────────────────────────────-─

export function DuplicationCard({ dup }: { dup: DuplicationFamily }) {
  if (!dup.available) return <Unavailable reason="No chunk-body field was detected in this index." />;
  const adj = dup.adjacency;
  return (
    <div className="space-y-4">
      <Explainer>
        When the same text is indexed more than once, a search returns copies instead of different
        results, wasting the few slots the answer model gets to see. Exact duplicates are
        identical chunks; near-duplicates are almost identical (think the same disclaimer on every
        page). Some overlap between neighboring chunks is intentional so sentences are not lost at
        the cut, but a high overlap means the index stores the same content twice.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric label="Exact duplicates" value={fmtPct(dup.exact_duplicate_pct)} sub={`${numberFmt(dup.exact_clusters)} clusters`} />
        <Metric label="Near-duplicate pairs" value={numberFmt(dup.near_duplicate_pairs)} sub={`of ${numberFmt(dup.near_dup_scanned)} scanned`} />
        {adj?.available && adj.pairs ? (
          <>
            <Metric label="Adjacent overlap (median)" value={fmtPct(adj.median_overlap_pct)} />
            <Metric label="Pairs with no overlap" value={fmtPct(adj.zero_overlap_pct)} />
            <Metric label="Multi-chunk docs" value={numberFmt(adj.multi_chunk_parents)} />
          </>
        ) : null}
      </div>
      {adj?.available && (
        <p className="text-xs text-gray-400 dark:text-slate-500">
          {adj.pairs
            ? adj.ordered
              ? "Adjacent overlap measured on chunks ordered by their ordinal field."
              : "No chunk-ordinal field found — adjacency measured pairwise within a parent (approximate)."
            : "Not enough multi-chunk parent documents in the sample to measure overlap."}
        </p>
      )}
    </div>
  );
}

// ── Metadata completeness ────────────────────────────────────────────────────

export function MetadataCard({ meta }: { meta: MetadataFamily }) {
  const crit = meta.critical ?? {};
  const critOrder: { key: string; label: string }[] = [
    { key: "text", label: "Body" },
    { key: "title", label: "Title" },
    { key: "url", label: "Source URL" },
    { key: "parent", label: "Parent id" },
  ];
  return (
    <div className="space-y-4">
      <Explainer>
        Besides its text, each chunk carries fields like title, source URL and document id. When
        these are missing, results cannot be filtered, cited or traced back to their source.
        Orphan chunks have neither a URL nor a parent document, so nobody can tell where their
        content came from.
      </Explainer>
      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">Critical fields</p>
        <div className="space-y-1.5">
          {critOrder.map(({ key, label }) => {
            const c = crit[key];
            const fill = c?.fill_rate ?? null;
            return (
              <div key={key} className="flex items-center gap-2 text-xs">
                <span className="w-24 text-gray-600 dark:text-slate-300">{label}</span>
                <div className="flex-1">
                  <Bar pct={fill ?? 0} tone={fill === null ? undefined : fill >= 99 ? "good" : fill >= 90 ? "warn" : "bad"} />
                </div>
                <span className="w-24 text-right text-gray-500 dark:text-slate-400">
                  {c?.field ? fmtPct(fill) : "not present"}
                </span>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">
          Orphan chunks (no URL and no parent id): {fmtPct(meta.orphans_pct)}
        </p>
      </div>

      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
          All indexed fields ({meta.facetable_field_count}) — lowest coverage first
        </p>
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-400 dark:text-slate-500 sticky top-0 bg-white dark:bg-slate-900">
              <tr>
                <th className="text-left font-normal py-1">Field</th>
                <th className="text-left font-normal w-40">Fill</th>
                <th className="text-right font-normal">Distinct</th>
                <th className="text-left font-normal pl-3">Top values</th>
              </tr>
            </thead>
            <tbody>
              {(meta.fields ?? []).map((f) => (
                <tr key={f.field} className="border-t border-gray-50 dark:border-slate-800/50 align-top">
                  <td className="py-1 pr-2 font-mono truncate max-w-[12rem]">
                    {f.field}
                    {f.multivalued && <span className="text-gray-400"> (multi)</span>}
                  </td>
                  <td className="py-1">
                    <div className="flex items-center gap-1.5">
                      <div className="w-20">
                        <Bar
                          pct={f.fill_rate ?? 0}
                          tone={f.fill_rate === null ? undefined : f.fill_rate >= 95 ? "good" : f.fill_rate >= 70 ? "warn" : "bad"}
                        />
                      </div>
                      <span className="text-gray-500 dark:text-slate-400">
                        {fmtPct(f.fill_rate)}
                        {f.fill_source === "sample" && <span className="text-gray-400">~</span>}
                      </span>
                    </div>
                  </td>
                  <td className="text-right text-gray-500 dark:text-slate-400">
                    {f.cardinality_capped ? "≥" : ""}{numberFmt(f.cardinality)}
                  </td>
                  <td className="pl-3 text-gray-500 dark:text-slate-400 truncate max-w-[18rem]">
                    {f.top.map((t) => t.value).slice(0, 3).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-gray-400 dark:text-slate-500 mt-1">
          ~ = estimated from the sample (field not server-side facetable). Others are exact whole-corpus counts.
        </p>
      </div>
    </div>
  );
}

// ── Content / parser quality ─────────────────────────────────────────────────

export function ContentCard({ content }: { content: ContentFamily }) {
  if (!content.available) return <Unavailable reason="No chunk-body field was detected in this index." />;
  return (
    <div className="space-y-4">
      <Explainer>
        Checks whether the text itself arrived intact from the ingestion pipeline. Mojibake is
        broken character encoding (a German ü turning into Ã¼), which ruins both keyword matching
        and embeddings. Table-heavy chunks are tables flattened into pipe characters that read as
        noise. Raw markup means leftover HTML tags. Embedding coverage shows how many chunks
        actually have a search vector; a chunk without one is invisible to semantic search.
      </Explainer>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Metric label="Mojibake" value={fmtPct(content.mojibake_pct)} sub="broken characters" />
        <Metric label="Table-heavy" value={fmtPct(content.table_heavy_pct)} sub="flattened tables" />
        <Metric label="Raw markup" value={fmtPct(content.markup_heavy_pct)} sub="leftover HTML" />
        <Metric
          label="Embedding coverage"
          value={fmtPct(content.embedding?.coverage_pct)}
          sub={content.embedding?.field ? undefined : "vector field not retrievable"}
        />
      </div>
      {content.boilerplate && content.boilerplate.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">Repeated boilerplate lines</p>
          <ul className="space-y-1 text-xs">
            {content.boilerplate.map((b, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-gray-400 dark:text-slate-500 flex-shrink-0">×{b.count}</span>
                <span className="truncate text-gray-600 dark:text-slate-300">{b.line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Unavailable({ reason }: { reason: string }) {
  return <p className="text-xs text-gray-400 dark:text-slate-500">{reason}</p>;
}
