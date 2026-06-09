"use client";

import { useEffect, useState } from "react";

import { getIndexTree } from "@/lib/api";
import type { IndexTreeDocument, IndexTreeGroupNode } from "@/lib/api-types/index-explorer";

type DocSort = "url" | "title";

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

function GroupNode({
  providerId,
  groupBy,
  path,
  node,
  maxSiblingCount,
  depth,
}: {
  providerId: string;
  groupBy: string[];
  path: string[]; // values from root to this node, inclusive
  node: IndexTreeGroupNode;
  maxSiblingCount: number;
  depth: number;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [children, setChildren] = useState<IndexTreeGroupNode[] | null>(null);
  const [docs, setDocs] = useState<IndexTreeDocument[] | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && children === null && docs === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        const resp = await getIndexTree({ providerId, groupBy, path });
        if (resp.level === "group") setChildren(resp.groups);
        else setDocs(resp.documents);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    }
  }

  const childMax = children
    ? Math.max(1, ...children.map((c) => c.doc_count))
    : 1;

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
          {children?.map((c) => (
            <GroupNode
              key={`${c.value}@${depth + 1}`}
              providerId={providerId}
              groupBy={groupBy}
              path={[...path, c.value]}
              node={c}
              maxSiblingCount={childMax}
              depth={depth + 1}
            />
          ))}
          {docs !== null && <DocumentLeaves docs={docs} total={node.doc_count} />}
        </div>
      )}
    </div>
  );
}

export function IndexTree({
  providerId,
  groupBy,
}: {
  providerId: string;
  groupBy: string[];
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [roots, setRoots] = useState<IndexTreeGroupNode[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setRoots([]);
    getIndexTree({ providerId, groupBy, path: [] })
      .then((resp) => {
        if (cancelled) return;
        setRoots(resp.level === "group" ? resp.groups : []);
      })
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [providerId, groupBy]);

  if (loading) {
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading index…</p>;
  }
  if (error) {
    return <p className={ERR_CLS}>{error}</p>;
  }
  if (roots.length === 0) {
    return (
      <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
        No values found for this grouping.
      </p>
    );
  }

  const max = Math.max(1, ...roots.map((r) => r.doc_count));

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-3">
      {roots.map((r) => (
        <GroupNode
          key={`${r.value}@0`}
          providerId={providerId}
          groupBy={groupBy}
          path={[r.value]}
          node={r}
          maxSiblingCount={max}
          depth={0}
        />
      ))}
    </div>
  );
}
