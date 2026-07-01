"use client";

/**
 * In-app explainer for the wanted-sources gap analysis: how each CSV row is
 * reconciled against the connected index, and what every status verdict means.
 * Mirrors the matching engine in
 * apps/api/app/index_providers/source_gaps.py — keep the thresholds in sync.
 */

import { STATUS_CHIP } from "./source-registry-shared";

function Chip({ status }: { status: keyof typeof STATUS_CHIP }) {
  const chip = STATUS_CHIP[status];
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${chip.cls}`}>
      {chip.label}
    </span>
  );
}

export function WantedSourcesInfo() {
  return (
    <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-900/40 p-4 mb-4 text-sm text-gray-600 dark:text-slate-300 space-y-4">
      <p>
        A gap analysis reconciles two lists: the <strong>wanted sources</strong> you imported
        as CSV (documents that <em>should</em> be retrievable) and the documents that are{" "}
        <strong>actually in the connected index</strong>. It never re-fetches or re-embeds
        anything. It matches identities and gives each wanted source a verdict.
      </p>

      <div>
        <p className="font-medium text-gray-700 dark:text-slate-200 mb-1">
          How each source is matched
        </p>
        <ol className="list-decimal list-inside space-y-1.5">
          <li>
            <strong>Exact URL match.</strong> If a row has its own document URL, we reproduce
            the indexer&apos;s deterministic page id (a hash of the canonicalized URL) and ask
            the index whether that exact document is present. A row can list both an HTML page
            and its PDF twin. Either one indexed counts as covered.
          </li>
          <li>
            <strong>Platform rows.</strong> When one URL is shared by 3 or more rows, it is a
            portal or landing page the crawler walks, not an individual document. The URL says
            nothing about the single document, so the URL check is skipped and the row falls
            through to title search.
          </li>
          <li>
            <strong>Title search.</strong> We full-text-search the index for the source name
            and score the best hit by <em>token overlap</em>: the fraction of the name&apos;s
            meaningful words (accent-folded, stopwords and short words dropped) that appear in
            the matched title. The search is scoped to the expected adapter first, then retried
            across the whole index. A hit found under a different adapter than expected is
            flagged in the detail text.
          </li>
        </ol>
      </div>

      <div>
        <p className="font-medium text-gray-700 dark:text-slate-200 mb-2">What each status means</p>
        <ul className="space-y-2">
          <li className="flex gap-2">
            <span className="shrink-0 w-28">
              <Chip status="covered_url" />
            </span>
            <span>Exact match on the source&apos;s own document URL. The strongest signal.</span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 w-28">
              <Chip status="covered_title" />
            </span>
            <span>
              Strong title match (60% or more of the name&apos;s words appear in an indexed
              document). Treated as covered.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 w-28">
              <Chip status="review" />
            </span>
            <span>
              Weak title match (between 30% and 60% overlap). Something similar is indexed but
              it is not a confident match, so verify it by hand.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 w-28">
              <Chip status="missing" />
            </span>
            <span>
              No URL hit and no title match above 30%. No evidence the document is in the index.
              Action for the indexing pipeline. &quot;Platform row&quot; in the detail means the
              row shared a portal URL, so only title search was tried.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="shrink-0 w-28">
              <Chip status="acked" />
            </span>
            <span>
              Intentionally not indexed. You acknowledged the gap with a note, so it is muted
              from the counts and the report.
            </span>
          </li>
        </ul>
      </div>

      <p className="text-xs text-gray-500 dark:text-slate-400">
        The badges above the list collapse both covered verdicts into one &quot;covered&quot;
        count. Download report exports the full breakdown, including a per-adapter view for the
        indexing pipeline owners.
      </p>
    </div>
  );
}
