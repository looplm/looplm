"use client";

import { useEffect, useState } from "react";

import { getIndexTree } from "@/lib/api";
import type {
  IndexTreeDocument,
  IndexTreeGroupNode,
  IndexTreeSection,
} from "@/lib/api-types/index-explorer";

type DocSort = "url" | "title";
type PathStep = { key: string; value: string };

const ERR_CLS =
  "text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1";

function fmt(n: number): string {
  return n.toLocaleString();
}

function displayValue(value: string): string {
  return value.trim() === "" ? "(empty)" : value;
}

function Bar({ fraction }: { fraction: number }) {
  const pct = Math.max(2, Math.round(fraction * 100));
  return (
    <div className="h-1.5 w-24 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden flex-shrink-0">
      <div className="h-full rounded-full bg-indigo-500/70" style={{ width: `${pct}%` }} />
    </div>
  );
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

function DocumentLeaves({
  docs,
  total,
}: {
  docs: IndexTreeDocument[];
  total: number;
}) {
  const [sort, setSort] = useState<DocSort>("url");

  if (docs.length === 0) {
    return <p className="text-xs text-gray-400 dark:text-slate-500 py-1">No documents.</p>;
  }

  const sorted = [...docs].sort((a, b) => {
    const av = (sort === "url" ? a.url : a.title) || "";
    const bv = (sort === "url" ? b.url : b.title) || "";
    return av.localeCompare(bv);
  });

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-gray-400 dark:text-slate-500 pb-1">
        <span>
          Showing {docs.length}
          {total > docs.length ? ` of ${fmt(total)}` : ""} documents
        </span>
        <label className="flex items-center gap-1">
          <span>Sort by</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as DocSort)}
            className="bg-transparent border border-gray-200 dark:border-slate-700 rounded px-1 py-0.5"
          >
            <option value="url">URL</option>
            <option value="title">Title</option>
          </select>
        </label>
      </div>
      {sorted.map((d) => (
        <div key={d.id} className="text-xs py-0.5">
          <div className="flex items-center gap-1.5">
            <span className="text-gray-400 dark:text-slate-600">•</span>
            <span className="text-gray-700 dark:text-slate-200 truncate">
              {d.title || d.id || "(untitled)"}
            </span>
            {d.url && (
              <a
                href={d.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-500 hover:text-indigo-400 flex-shrink-0"
                title={d.url}
              >
                ↗
              </a>
            )}
          </div>
          {d.url && (
            <div className="pl-4 text-[11px] text-gray-400 dark:text-slate-500 truncate">
              {d.url}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Render one level's distribution(s). Multiple sections (parallel fields) get
 *  a small "By <label>" header each; a single section renders bare. */
function TreeSections({
  providerId,
  levels,
  basePath,
  sections,
  depth,
}: {
  providerId: string;
  levels: string[][];
  basePath: PathStep[];
  sections: IndexTreeSection[];
  depth: number;
}) {
  const labeled = sections.length > 1;
  return (
    <>
      {sections.map((sec) => {
        const max = Math.max(1, ...sec.groups.map((g) => g.doc_count));
        return (
          <div key={sec.key} className={labeled ? "mt-2 first:mt-0" : ""}>
            {labeled && (
              <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500 px-1 pb-0.5">
                By {sec.label}
              </div>
            )}
            <div className={labeled ? "pl-2" : ""}>
              {sec.groups.length === 0 ? (
                <p className="text-xs text-gray-400 dark:text-slate-500 py-1 px-1">
                  No values.
                </p>
              ) : (
                sec.groups.map((g) => (
                  <GroupNode
                    key={`${sec.key}:${g.value}@${depth}`}
                    providerId={providerId}
                    levels={levels}
                    path={[...basePath, { key: sec.key, value: g.value }]}
                    node={g}
                    maxSiblingCount={max}
                    depth={depth}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}

function GroupNode({
  providerId,
  levels,
  path,
  node,
  maxSiblingCount,
  depth,
}: {
  providerId: string;
  levels: string[][];
  path: PathStep[]; // root → this node, inclusive
  node: IndexTreeGroupNode;
  maxSiblingCount: number;
  depth: number;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sections, setSections] = useState<IndexTreeSection[] | null>(null);
  const [docs, setDocs] = useState<IndexTreeDocument[] | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && sections === null && docs === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        const resp = await getIndexTree({ providerId, levels, path });
        if (resp.level === "group") setSections(resp.sections);
        else setDocs(resp.documents);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div>
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2 py-1 text-left text-sm text-gray-700 dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800/50 rounded px-1"
      >
        <Chevron open={open} />
        <span className="flex-1 truncate font-medium">{displayValue(node.value)}</span>
        <Bar fraction={node.doc_count / maxSiblingCount} />
        <span className="text-xs tabular-nums text-gray-500 dark:text-slate-400 w-16 text-right">
          {fmt(node.doc_count)}
        </span>
      </button>

      {open && (
        <div className="pl-4 ml-1.5 border-l border-gray-200/70 dark:border-slate-700/70">
          {loading && (
            <p className="text-xs text-gray-400 dark:text-slate-500 py-1">Loading…</p>
          )}
          {error && <p className={ERR_CLS}>{error}</p>}
          {sections !== null && (
            <TreeSections
              providerId={providerId}
              levels={levels}
              basePath={path}
              sections={sections}
              depth={depth + 1}
            />
          )}
          {docs !== null && <DocumentLeaves docs={docs} total={node.doc_count} />}
        </div>
      )}
    </div>
  );
}

export function IndexTree({
  providerId,
  levels,
}: {
  providerId: string;
  levels: string[][];
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sections, setSections] = useState<IndexTreeSection[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSections([]);
    getIndexTree({ providerId, levels, path: [] })
      .then((resp) => {
        if (cancelled) return;
        setSections(resp.level === "group" ? resp.sections : []);
      })
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [providerId, levels]);

  if (loading) {
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading index…</p>;
  }
  if (error) {
    return <p className={ERR_CLS}>{error}</p>;
  }
  const hasValues = sections.some((s) => s.groups.length > 0);
  if (!hasValues) {
    return (
      <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
        No values found for this grouping.
      </p>
    );
  }

  return (
    <div className="rounded-lg bg-gray-50/60 dark:bg-slate-900/40 p-3">
      <TreeSections
        providerId={providerId}
        levels={levels}
        basePath={[]}
        sections={sections}
        depth={0}
      />
    </div>
  );
}
