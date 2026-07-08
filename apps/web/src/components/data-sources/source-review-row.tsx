"use client";

/**
 * One source in the "Source review" tab: a collapsible header (name + business
 * metadata) that lazily loads and lists every indexed chunk of that source in
 * reading order, with completeness signals (gaps/duplicates in the chunk-order
 * sequence) so a reviewer can page through and check coverage.
 */

import { Fragment, useState } from "react";

import { getSourceChunks } from "@/lib/api";
import type {
  SourceChunksResponse,
  SourceExpectation,
  SourceScanResultItem,
} from "@/lib/api-types/source-registry";
import { ErrorNotice } from "@/components/error-notice";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-3.5 h-3.5 flex-shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // clipboard unavailable (e.g. insecure context) — ignore
  }
}

/**
 * A span of text with a copy button that reveals on hover. Clicking the button
 * copies just this text (not the whole row) and does not toggle the row.
 */
function Copyable({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className={`group/copy inline-flex max-w-full items-center gap-1 ${className ?? ""}`}>
      <span className="truncate">{text}</span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void copyText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }}
        title={copied ? "Copied" : "Copy"}
        aria-label={`Copy ${text}`}
        className="flex-shrink-0 text-gray-400 opacity-0 transition-opacity hover:text-indigo-500 focus:opacity-100 group-hover/copy:opacity-100 dark:text-slate-500"
      >
        {copied ? (
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2v-2m-6-12h6a2 2 0 012 2v6m-4-8V3"
            />
          </svg>
        )}
      </button>
    </span>
  );
}

const RESOLUTION_BADGE: Record<string, { label: string; cls: string }> = {
  url: { label: "Matched by URL", cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" },
  title: { label: "Matched by title", cls: "bg-sky-500/15 text-sky-600 dark:text-sky-400" },
  none: { label: "Not in index", cls: "bg-red-500/15 text-red-600 dark:text-red-400" },
};

const RED = "bg-red-500/15 text-red-600 dark:text-red-400";
const AMBER = "bg-amber-500/15 text-amber-600 dark:text-amber-400";

function Badge({ label, cls, title }: { label: string; cls: string; title?: string }) {
  return (
    <span
      title={title}
      className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

/** Header badges derived from the bulk-scan verdict (shown without expanding). */
function ScanBadges({ result, sparse }: { result: SourceScanResultItem; sparse?: boolean }) {
  if (result.execution_status === "error") {
    return <Badge label="Scan error" cls={RED} title={result.error ?? undefined} />;
  }
  if (!result.resolved) {
    return <Badge label="Not in index" cls={RED} />;
  }
  const res = RESOLUTION_BADGE[result.resolution] ?? RESOLUTION_BADGE.url;
  return (
    <>
      {result.missing_chunk_count > 0 && (
        <Badge
          label={`${result.missing_chunk_count} gap${result.missing_chunk_count === 1 ? "" : "s"}`}
          cls={AMBER}
          title="Holes in the chunk-order sequence"
        />
      )}
      {sparse && <Badge label="Few chunks" cls={AMBER} title="Unusually few chunks vs. peers" />}
      <Badge label={res.label} cls={res.cls} />
    </>
  );
}

function metaSegments(e: SourceExpectation): string[] {
  return [e.typ, e.sparte, e.thema, e.publisher].filter((v): v is string => Boolean(v));
}

/** Range-compress a sorted list of ints: [3,4,5,9] → "3–5, 9". */
function compressRanges(nums: number[]): string {
  if (nums.length === 0) return "";
  const out: string[] = [];
  let start = nums[0];
  let prev = nums[0];
  for (let i = 1; i <= nums.length; i++) {
    const n = nums[i];
    if (n === prev + 1) {
      prev = n;
      continue;
    }
    out.push(start === prev ? `${start}` : `${start}–${prev}`);
    start = n;
    prev = n;
  }
  return out.join(", ");
}

function CompletenessBanner({ data }: { data: SourceChunksResponse }) {
  if (!data.ordinal_available) {
    if (data.chunk_count <= 1) return null;
    return (
      <p className="pb-1 text-[11px] text-gray-400 dark:text-slate-500">
        No chunk-order field in this index — chunks are shown in index order, so gaps can not be
        detected automatically.
      </p>
    );
  }
  const hasGaps = data.missing_ordinals.length > 0;
  const hasDupes = data.duplicate_ordinals.length > 0;
  if (!hasGaps && !hasDupes) {
    return (
      <p className="pb-1 text-[11px] text-emerald-600 dark:text-emerald-400">
        ✓ Chunk order is continuous — no missing indices.
      </p>
    );
  }
  return (
    <div className="mb-1 space-y-0.5 rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
      {hasGaps && (
        <p>
          Gap in chunk order — missing index{data.missing_ordinals.length === 1 ? "" : "es"}:{" "}
          {compressRanges(data.missing_ordinals)}
          {data.gaps_truncated ? " …" : ""}
        </p>
      )}
      {hasDupes && <p>Duplicate index{data.duplicate_ordinals.length === 1 ? "" : "es"}: {compressRanges(data.duplicate_ordinals)}</p>}
    </div>
  );
}

function ChunkItem({
  index,
  ordinal,
  title,
  url,
  text,
}: {
  index: number;
  ordinal: string | null;
  title: string | null;
  url: string | null;
  text: string | null;
}) {
  return (
    <div className="border-t border-gray-100 py-2 text-xs first:border-t-0 dark:border-slate-800">
      <div className="flex items-center gap-1.5">
        <span className="flex-shrink-0 font-mono text-[10px] text-gray-400 dark:text-slate-500">
          #{index}
          {ordinal != null && ordinal !== String(index) ? ` (${ordinal})` : ""}
        </span>
        <span className="truncate text-gray-700 dark:text-slate-200">{title || "(untitled)"}</span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 text-indigo-500 hover:text-indigo-400"
            title={url}
          >
            ↗
          </a>
        )}
      </div>
      {text && (
        <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-gray-500 dark:text-slate-400">
          {text}
        </p>
      )}
    </div>
  );
}

export function SourceReviewRow({
  expectation,
  scanResult,
  sparse,
}: {
  expectation: SourceExpectation;
  scanResult?: SourceScanResultItem;
  sparse?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SourceChunksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && data === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        setData(await getSourceChunks(expectation.id));
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    }
  };

  const segments = metaSegments(expectation);
  // Prefer the bulk-scan verdict (available without expanding); fall back to the
  // on-expand fetch's resolution badge once the row has been opened.
  const fallbackBadge = !scanResult && data ? RESOLUTION_BADGE[data.resolution] : null;
  const chunkCount = scanResult?.resolved
    ? scanResult.chunk_count
    : data?.resolved
      ? data.chunk_count
      : null;

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            void toggle();
          }
        }}
        className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-slate-800/50"
      >
        <Chevron open={open} />
        <span className="min-w-0 flex-1">
          <Copyable
            text={expectation.name}
            className="block text-gray-700 dark:text-slate-200"
          />
          {segments.length > 0 && (
            <span className="flex flex-wrap items-center gap-x-1 text-[11px] text-gray-400 dark:text-slate-500">
              {segments.map((s, i) => (
                <Fragment key={i}>
                  {i > 0 && <span aria-hidden>·</span>}
                  <Copyable text={s} />
                </Fragment>
              ))}
            </span>
          )}
        </span>
        {scanResult && <ScanBadges result={scanResult} sparse={sparse} />}
        {fallbackBadge && <Badge label={fallbackBadge.label} cls={fallbackBadge.cls} />}
        {chunkCount != null && (
          <span className="flex-shrink-0 text-xs tabular-nums text-gray-500 dark:text-slate-400">
            {chunkCount.toLocaleString()} chunk{chunkCount === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {open && (
        <div className="border-t border-gray-100 px-4 py-2 dark:border-slate-800">
          {loading && <p className="py-1 text-xs text-gray-400">Loading chunks…</p>}
          {error != null && <ErrorNotice error={error} />}
          {data && !data.resolved && (
            <p className="py-1 text-xs text-gray-400 dark:text-slate-500">
              This source could not be located in the index (no URL-hash hit and no strong title
              match). Run a gap analysis in the Wanted sources tab for the full verdict.
            </p>
          )}
          {data && data.resolved && (
            <>
              <CompletenessBanner data={data} />
              {data.chunks.length === 0 ? (
                <p className="py-1 text-xs text-gray-400">No chunks found.</p>
              ) : (
                data.chunks.map((c) => (
                  <ChunkItem
                    key={c.id || c.index}
                    index={c.index}
                    ordinal={c.ordinal}
                    title={c.title}
                    url={c.url}
                    text={c.text}
                  />
                ))
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
