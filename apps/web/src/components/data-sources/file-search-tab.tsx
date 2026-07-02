"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getIndexFileChunks,
  getIndexFileTypes,
  getIndexTree,
  searchIndexFiles,
} from "@/lib/api";
import type {
  IndexFileChunk,
  IndexFileMatch,
  IndexFileTypeValue,
  IndexTreeDocument,
} from "@/lib/api-types/index-explorer";
import { ErrorNotice } from "@/components/error-notice";

const CARD_CLS =
  "rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900";

function fmt(n: number): string {
  return n.toLocaleString();
}

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

function KindBadge({ kind }: { kind: IndexFileMatch["kind"] }) {
  const label = kind === "attachment" ? "Attachment" : "Page";
  const cls =
    kind === "attachment"
      ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
      : "bg-sky-500/15 text-sky-600 dark:text-sky-400";
  return (
    <span className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
      {label}
    </span>
  );
}

/** A retrieved chunk / sampled doc row: text snippet + optional external link. */
function ChunkRow({
  index,
  ordinal,
  title,
  url,
  snippet,
}: {
  index?: number;
  ordinal?: string | null;
  title: string | null;
  url: string | null;
  snippet: string | null;
}) {
  return (
    <div className="border-t border-gray-100 dark:border-slate-800 py-2 text-xs first:border-t-0">
      <div className="flex items-center gap-1.5">
        {index != null && (
          <span className="flex-shrink-0 font-mono text-[10px] text-gray-400 dark:text-slate-500">
            #{index}
            {ordinal != null && ordinal !== String(index) ? ` (${ordinal})` : ""}
          </span>
        )}
        <span className="truncate text-gray-700 dark:text-slate-200">
          {title || "(untitled)"}
        </span>
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
      {snippet && (
        <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-gray-500 dark:text-slate-400">
          {snippet}
        </p>
      )}
    </div>
  );
}

// ── Section A: file types in the index ──────────────────────────────────────

function FileTypeRow({
  providerId,
  field,
  value,
  count,
  fraction,
}: {
  providerId: string;
  field: string;
  value: string;
  count: number;
  fraction: number;
}) {
  const [open, setOpen] = useState(false);
  const [docs, setDocs] = useState<IndexTreeDocument[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && docs === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        const res = await getIndexTree({
          providerId,
          levels: [[field]],
          path: [{ key: field, value }],
          limit: 8,
        });
        setDocs(res.documents);
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    }
  };

  const pct = Math.max(2, Math.round(fraction * 100));
  return (
    <div>
      <button
        onClick={toggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-slate-800/50"
      >
        <Chevron open={open} />
        <span className="truncate text-gray-700 dark:text-slate-200">
          {value.trim() === "" ? "(empty)" : value}
        </span>
        <div className="ml-auto flex flex-shrink-0 items-center gap-2">
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-800">
            <div className="h-full rounded-full bg-indigo-500/70" style={{ width: `${pct}%` }} />
          </div>
          <span className="w-16 text-right text-xs tabular-nums text-gray-500 dark:text-slate-400">
            {fmt(count)}
          </span>
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-100 px-4 py-2 dark:border-slate-800">
          {loading && <p className="py-1 text-xs text-gray-400">Loading examples…</p>}
          {error != null && <ErrorNotice error={error} />}
          {docs != null && docs.length === 0 && (
            <p className="py-1 text-xs text-gray-400">No example chunks.</p>
          )}
          {docs?.map((d) => (
            <ChunkRow key={d.id} title={d.title} url={d.url} snippet={d.snippet} />
          ))}
        </div>
      )}
    </div>
  );
}

function FileTypesSection({ providerId }: { providerId: string }) {
  const [field, setField] = useState<string | null>(null);
  const [values, setValues] = useState<IndexFileTypeValue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getIndexFileTypes(providerId)
      .then((res) => {
        if (cancelled) return;
        setField(res.field);
        setValues(res.values);
      })
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [providerId]);

  if (loading) return <p className="py-4 text-sm text-gray-400">Loading file types…</p>;
  if (error != null) return <ErrorNotice error={error} />;
  if (field === null || values.length === 0) return null; // no type dimension: hide

  const max = Math.max(...values.map((v) => v.count), 1);
  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold">File types in this index</h2>
      <p className="mb-3 text-sm text-gray-500 dark:text-slate-400">
        Grouped by <code className="text-xs">{field}</code>. Expand a type to preview a few of its
        chunks.
      </p>
      <div className={`${CARD_CLS} divide-y divide-gray-100 dark:divide-slate-800`}>
        {values.map((v) => (
          <FileTypeRow
            key={v.value}
            providerId={providerId}
            field={field}
            value={v.value}
            count={v.count}
            fraction={v.count / max}
          />
        ))}
      </div>
    </section>
  );
}

// ── Section B: filename search ──────────────────────────────────────────────

function FileMatchRow({
  providerId,
  match,
}: {
  providerId: string;
  match: IndexFileMatch;
}) {
  const [open, setOpen] = useState(false);
  const [chunks, setChunks] = useState<IndexFileChunk[] | null>(null);
  const [ordinalAvailable, setOrdinalAvailable] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && chunks === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        const res = await getIndexFileChunks({
          providerId,
          fileKey: match.key,
          fileValue: match.value,
          kind: match.kind,
          label: match.label,
        });
        setChunks(res.documents);
        setOrdinalAvailable(res.ordinal_available);
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div>
      <button
        onClick={toggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-slate-800/50"
      >
        <Chevron open={open} />
        <KindBadge kind={match.kind} />
        <span className="truncate text-gray-700 dark:text-slate-200">{match.label}</span>
        {match.url && (
          <a
            href={match.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="flex-shrink-0 text-indigo-500 hover:text-indigo-400"
            title={match.url}
          >
            ↗
          </a>
        )}
        <span className="ml-auto flex-shrink-0 text-xs tabular-nums text-gray-500 dark:text-slate-400">
          {fmt(match.chunk_count)} chunk{match.chunk_count === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <div className="border-t border-gray-100 px-4 py-2 dark:border-slate-800">
          {loading && <p className="py-1 text-xs text-gray-400">Loading chunks…</p>}
          {error != null && <ErrorNotice error={error} />}
          {chunks != null && !ordinalAvailable && chunks.length > 1 && (
            <p className="pb-1 text-[11px] text-gray-400 dark:text-slate-500">
              No chunk-order field in this index — chunks are shown in index order.
            </p>
          )}
          {chunks != null && chunks.length === 0 && (
            <p className="py-1 text-xs text-gray-400">No chunks found.</p>
          )}
          {chunks?.map((c) => (
            <ChunkRow
              key={c.id || c.index}
              index={c.index}
              ordinal={c.ordinal}
              title={c.title}
              url={c.url}
              snippet={c.snippet}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FileSearchSection({ providerId }: { providerId: string }) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<IndexFileMatch[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const runSearch = useCallback(
    async (q: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await searchIndexFiles({ providerId, q });
        setMatches(res.data);
      } catch (e) {
        setError(e);
        setMatches(null);
      } finally {
        setLoading(false);
      }
    },
    [providerId],
  );

  // Debounce: search 300ms after the user stops typing.
  useEffect(() => {
    const q = query.trim();
    if (q === "") {
      setMatches(null);
      setError(null);
      return;
    }
    const id = setTimeout(() => runSearch(q), 300);
    return () => clearTimeout(id);
  }, [query, runSearch]);

  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold">Find a file</h2>
      <p className="mb-3 text-sm text-gray-500 dark:text-slate-400">
        Search by attachment filename or page title, then open a file to see all its chunks in
        reading order.
      </p>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. invoice_2024.pdf or Employee Handbook"
        className="mb-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
      {loading && <p className="py-2 text-sm text-gray-400">Searching…</p>}
      {error != null && <ErrorNotice error={error} />}
      {matches != null && matches.length === 0 && !loading && (
        <p className="py-2 text-sm text-gray-400">No files match “{query.trim()}”.</p>
      )}
      {matches != null && matches.length > 0 && (
        <div className={`${CARD_CLS} divide-y divide-gray-100 dark:divide-slate-800`}>
          {matches.map((m) => (
            <FileMatchRow key={`${m.kind}:${m.key}:${m.value}`} providerId={providerId} match={m} />
          ))}
        </div>
      )}
    </section>
  );
}

export function FileSearchTab({ providerId }: { providerId: string }) {
  return (
    <div className="space-y-8">
      <FileSearchSection providerId={providerId} />
      <FileTypesSection providerId={providerId} />
    </div>
  );
}
