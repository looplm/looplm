"use client";

/**
 * Wanted-status source registry: declare which sources SHOULD be in the index
 * (CSV import or manual edits), run a gap analysis against what actually is,
 * and export the result as a markdown report for the indexing-pipeline owners.
 */

import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  deleteSourceExpectation,
  fetchGapRunReport,
  getGapRun,
  importSourceCsv,
  listGapRuns,
  listSourceExpectations,
  startGapRun,
  updateSourceExpectation,
} from "@/lib/api";
import type {
  GapRowResult,
  GapRowStatus,
  GapRunDetail,
  SourceExpectation,
} from "@/lib/api-types/source-registry";

const STATUS_CHIP: Record<string, { label: string; cls: string }> = {
  covered_url: {
    label: "Covered (URL)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  covered_title: {
    label: "Covered (title)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  review: {
    label: "Review",
    cls: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  },
  missing: {
    label: "Missing",
    cls: "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  },
  acked: {
    label: "Acknowledged",
    cls: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
  },
};

// Status filter buckets. The two "covered" verdicts collapse into one bucket.
type FilterBucket = "covered" | "review" | "missing" | "acked";
const ALL_BUCKETS: FilterBucket[] = ["covered", "review", "missing", "acked"];
const DEFAULT_BUCKETS: FilterBucket[] = ["review", "missing"];

const BUCKET_LABEL: Record<FilterBucket, string> = {
  covered: "covered",
  review: "to review",
  missing: "missing",
  acked: "acknowledged",
};
const BUCKET_CHIP: Record<FilterBucket, string> = {
  covered: STATUS_CHIP.covered_url.cls,
  review: STATUS_CHIP.review.cls,
  missing: STATUS_CHIP.missing.cls,
  acked: STATUS_CHIP.acked.cls,
};

function bucketOf(status: GapRowStatus | null): FilterBucket | null {
  if (!status) return null;
  if (status === "covered_url" || status === "covered_title") return "covered";
  return status;
}

// Dimensions a user can cluster the registry by, in default-preference order.
const GROUP_DIMENSIONS: { key: keyof SourceExpectation; label: string }[] = [
  { key: "sparte", label: "Sparte" },
  { key: "hierarchie", label: "Hierarchie" },
  { key: "typ", label: "Type" },
  { key: "publisher", label: "Publisher" },
  { key: "thema", label: "Thema" },
  { key: "adapter_tag", label: "Adapter" },
];

// Sort order within a group: actionable rows first.
const STATUS_ORDER: Record<string, number> = {
  missing: 0,
  review: 1,
  covered_url: 2,
  covered_title: 2,
  acked: 3,
};

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

/** Compact a URL to `host/…/last-segment` for side-by-side comparison. */
function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    const segments = u.pathname.split("/").filter(Boolean);
    const last = segments[segments.length - 1];
    if (!last) return host;
    return segments.length > 1 ? `${host}/…/${last}` : `${host}/${last}`;
  } catch {
    return url;
  }
}

/** Decode an uploaded CSV: try UTF-8 first, fall back to cp1252 exports. */
async function readCsvFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const utf8 = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  if (!utf8.includes("�")) return utf8;
  return new TextDecoder("windows-1252").decode(buffer);
}

export function WantedSourcesPanel({
  providerId,
  canEdit,
}: {
  providerId: string;
  canEdit: boolean;
}) {
  const [expectations, setExpectations] = useState<SourceExpectation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [run, setRun] = useState<GapRunDetail | null>(null);
  const [running, setRunning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // View controls: which statuses to show, what to cluster by, collapsed groups.
  const [visibleStatuses, setVisibleStatuses] = useState<Set<FilterBucket>>(
    () => new Set(DEFAULT_BUCKETS),
  );
  const [groupBy, setGroupBy] = useState<string>(""); // "" = auto, "none" = flat
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());

  const verdicts: Record<string, GapRowResult> = {};
  for (const row of run?.results?.rows ?? []) verdicts[row.expectation_id] = row;

  const loadExpectations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await listSourceExpectations(providerId);
      setExpectations(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  const loadLatestRun = useCallback(async () => {
    try {
      const { data } = await listGapRuns(providerId);
      const latest = data[0];
      if (!latest) return;
      const detail = await getGapRun(latest.id);
      setRun(detail);
      if (detail.status === "pending" || detail.status === "running") {
        setRunning(true);
      }
    } catch {
      // No runs yet is fine.
    }
  }, [providerId]);

  useEffect(() => {
    setRun(null);
    setNotice(null);
    loadExpectations();
    loadLatestRun();
  }, [loadExpectations, loadLatestRun]);

  // Poll while a run is active.
  useEffect(() => {
    if (!running || !run) return;
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getGapRun(run.id);
        setRun(detail);
        if (detail.status === "completed" || detail.status === "failed") {
          setRunning(false);
        }
      } catch {
        setRunning(false);
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [running, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleImport(file: File) {
    setError(null);
    setNotice(null);
    try {
      const csvText = await readCsvFile(file);
      const result = await importSourceCsv(providerId, csvText, false);
      setNotice(
        `Imported: ${result.created} new, ${result.updated} updated` +
          (result.skipped_rows ? `, ${result.skipped_rows} rows skipped (no link)` : "") +
          (result.warnings.length ? ` — ${result.warnings.length} warning(s)` : ""),
      );
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRun() {
    setError(null);
    try {
      const { run_id } = await startGapRun(providerId);
      const detail = await getGapRun(run_id);
      setRun(detail);
      setRunning(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDownloadReport() {
    if (!run) return;
    try {
      const markdown = await fetchGapRunReport(run.id);
      const blob = new Blob([markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `source-gap-report-${run.completed_at?.slice(0, 10) ?? "latest"}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleAck(expectation: SourceExpectation) {
    const note = window.prompt(
      "Why is this source intentionally not indexed? (empty input cancels)",
      expectation.ack_note ?? "",
    );
    if (!note) return;
    try {
      await updateSourceExpectation(expectation.id, { ack_note: note });
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleUnack(expectation: SourceExpectation) {
    try {
      await updateSourceExpectation(expectation.id, { ack_note: "" });
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDelete(expectation: SourceExpectation) {
    if (!window.confirm(`Remove "${expectation.name}" from the wanted sources?`)) return;
    try {
      await deleteSourceExpectation(expectation.id);
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const summary = run?.results?.summary;
  const hasRun = run?.status === "completed";

  const effectiveStatus = (e: SourceExpectation): GapRowStatus | null =>
    e.ack_note ? "acked" : (verdicts[e.id]?.status ?? null);

  const toggleStatus = (b: FilterBucket) =>
    setVisibleStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(b)) next.delete(b);
      else next.add(b);
      return next;
    });
  const isDefaultFilter =
    visibleStatuses.size === DEFAULT_BUCKETS.length &&
    DEFAULT_BUCKETS.every((b) => visibleStatuses.has(b));
  const resetStatuses = () =>
    setVisibleStatuses(new Set(isDefaultFilter ? ALL_BUCKETS : DEFAULT_BUCKETS));

  const toggleGroup = (key: string) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Status filter only applies once a run has produced verdicts; before that
  // (and for rows added after the run) every source stays visible.
  const isVisible = (e: SourceExpectation): boolean => {
    if (!hasRun) return true;
    const bucket = bucketOf(effectiveStatus(e));
    if (!bucket) return true;
    return visibleStatuses.has(bucket);
  };

  // Dimensions that actually carry values on the current expectations.
  const availableDims = GROUP_DIMENSIONS.filter((d) =>
    expectations.some((e) => e[d.key]),
  );
  const resolvedGroupBy =
    groupBy === "none"
      ? "none"
      : groupBy && availableDims.some((d) => d.key === groupBy)
        ? groupBy
        : (availableDims[0]?.key ?? "none");

  // Cluster sources into (optionally collapsible) groups. Badge counts cover the
  // whole group; only visible rows are listed, and empty groups are dropped.
  type Group = {
    key: string;
    label: string;
    items: SourceExpectation[];
    counts: Record<FilterBucket, number>;
  };
  const groups: Group[] = (() => {
    const flat = resolvedGroupBy === "none";
    const map = new Map<string, SourceExpectation[]>();
    for (const e of expectations) {
      const raw = flat ? "" : (e[resolvedGroupBy as keyof SourceExpectation] as string | null);
      const key = flat ? "__all__" : (raw && String(raw).trim()) || "__uncat__";
      const bucket = map.get(key);
      if (bucket) bucket.push(e);
      else map.set(key, [e]);
    }
    const out: Group[] = [];
    for (const [key, items] of map) {
      const counts: Record<FilterBucket, number> = {
        covered: 0,
        review: 0,
        missing: 0,
        acked: 0,
      };
      for (const e of items) {
        const b = bucketOf(effectiveStatus(e));
        if (b) counts[b] += 1;
      }
      const visibleItems = items
        .filter(isVisible)
        .sort(
          (a, b) =>
            (STATUS_ORDER[effectiveStatus(a) ?? "z"] ?? 9) -
            (STATUS_ORDER[effectiveStatus(b) ?? "z"] ?? 9),
        );
      if (visibleItems.length === 0) continue;
      out.push({
        key,
        label: key === "__all__" ? "" : key === "__uncat__" ? "Uncategorized" : key,
        items: visibleItems,
        counts,
      });
    }
    out.sort(
      (a, b) =>
        b.counts.missing + b.counts.review - (a.counts.missing + a.counts.review),
    );
    return out;
  })();
  const shownCount = groups.reduce((n, g) => n + g.items.length, 0);
  const colCount = canEdit ? 4 : 3;

  const renderRow = (e: SourceExpectation) => {
    const verdict = verdicts[e.id];
    const status = e.ack_note ? "acked" : verdict?.status;
    const chip = status ? STATUS_CHIP[status] : null;
    const detail = e.ack_note ? `Acknowledged: ${e.ack_note}` : verdict?.detail;
    return (
      <tr
        key={e.id}
        className="border-b border-gray-50 dark:border-slate-800/50 align-top"
      >
        <td className="py-2 pr-3 max-w-[24rem]">
          <span className="font-medium">{e.name}</span>
          {e.adapter_tag && (
            <div className="mt-0.5">
              <code className="text-[11px] bg-gray-100 dark:bg-slate-800 rounded px-1.5 py-0.5">
                {e.adapter_tag}
              </code>
            </div>
          )}
          <div className="mt-1 space-y-0.5 text-xs">
            {([
              ["HTML", e.html_url],
              ["PDF", e.pdf_url],
            ] as const).map(([label, url]) =>
              url ? (
                <div key={label} className="flex items-baseline gap-1.5">
                  <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500 w-8 flex-shrink-0">
                    {label}
                  </span>
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    title={url}
                    className="text-indigo-600 dark:text-indigo-400 hover:underline truncate"
                  >
                    ↗ {shortUrl(url)}
                  </a>
                </div>
              ) : null,
            )}
          </div>
        </td>
        <td className="py-2 pr-3 text-xs max-w-[20rem]">
          {/* Only a real match counts; `missing` rows still carry a sub-threshold
              near-miss in matched_url/title, which would contradict the status. */}
          {(status === "covered_url" || status === "covered_title" || status === "review") &&
          (verdict?.matched_url || verdict?.matched_title) ? (
            <a
              href={verdict.matched_url ?? undefined}
              target="_blank"
              rel="noreferrer"
              title={verdict.matched_url ?? undefined}
              className="block truncate text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              ↗ {verdict.matched_title ?? shortUrl(verdict.matched_url!)}
            </a>
          ) : (
            <span className="text-gray-400 dark:text-slate-500">—</span>
          )}
        </td>
        <td className="py-2 pr-3 max-w-[16rem]">
          {chip ? (
            <span className={`inline-block px-2 py-1 rounded-full text-xs ${chip.cls}`}>
              {chip.label}
            </span>
          ) : (
            <span className="text-xs text-gray-400 dark:text-slate-500">not analyzed</span>
          )}
          {detail && (
            <span className="block mt-1 text-xs text-gray-500 dark:text-slate-400">
              {detail}
            </span>
          )}
        </td>
        {canEdit && (
          <td className="py-2 whitespace-nowrap text-xs">
            {e.ack_note ? (
              <button
                onClick={() => handleUnack(e)}
                className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
              >
                Un-ack
              </button>
            ) : (
              <button
                onClick={() => handleAck(e)}
                title="Mark this gap as intentional"
                className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
              >
                Ack
              </button>
            )}
            <button
              onClick={() => handleDelete(e)}
              className="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 px-1.5 py-1"
            >
              ×
            </button>
          </td>
        )}
      </tr>
    );
  };

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mt-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <div>
          <h2 className="text-lg font-semibold">Wanted sources</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            The sources that should be retrievable from this index. Import the source list as
            CSV, then run a gap analysis to compare it against what is actually indexed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canEdit && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleImport(f);
                  e.target.value = "";
                }}
              />
              <button
                onClick={() => fileRef.current?.click()}
                className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
              >
                Import CSV
              </button>
            </>
          )}
          {canEdit && expectations.length > 0 && (
            <button
              onClick={handleRun}
              disabled={running}
              className="px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {running
                ? `Analyzing… ${run?.processed ?? 0}/${run?.total ?? expectations.length}`
                : "Run gap analysis"}
            </button>
          )}
          {run?.status === "completed" && (
            <button
              onClick={handleDownloadReport}
              className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
            >
              Download report
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-2 my-3">
          {error}
        </div>
      )}
      {notice && (
        <div className="bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 text-sm rounded-lg px-4 py-2 my-3">
          {notice}
        </div>
      )}
      {run?.status === "failed" && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-2 my-3">
          Gap analysis failed: {run.error}
        </div>
      )}

      {summary && run?.status === "completed" && (
        <div className="flex flex-wrap items-center gap-2 my-3 text-xs">
          {ALL_BUCKETS.map((b) => {
            const active = visibleStatuses.has(b);
            const count =
              b === "covered"
                ? summary.covered
                : b === "review"
                  ? summary.review
                  : b === "missing"
                    ? summary.missing
                    : summary.acked;
            return (
              <button
                key={b}
                onClick={() => toggleStatus(b)}
                aria-pressed={active}
                title={active ? `Hide ${BUCKET_LABEL[b]}` : `Show ${BUCKET_LABEL[b]}`}
                className={`px-2 py-1 rounded-full transition ${BUCKET_CHIP[b]} ${
                  active ? "ring-1 ring-current/40" : "opacity-40 hover:opacity-70"
                }`}
              >
                {count} {BUCKET_LABEL[b]}
              </button>
            );
          })}
          <button
            onClick={resetStatuses}
            className="px-2 py-1 text-gray-500 dark:text-slate-400 hover:underline"
          >
            {isDefaultFilter ? "Show all" : "Only gaps"}
          </button>
          {run.completed_at && (
            <span className="px-2 py-1 text-gray-400 dark:text-slate-500">
              analyzed {new Date(run.completed_at).toLocaleString()}
            </span>
          )}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading…</p>
      ) : expectations.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
          No wanted sources defined yet.{" "}
          {canEdit ? "Import the source list as CSV to get started." : ""}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 mt-3 mb-1 text-xs">
            <label className="flex items-center gap-1.5 text-gray-500 dark:text-slate-400">
              <span>Cluster by</span>
              <select
                value={resolvedGroupBy}
                onChange={(ev) => setGroupBy(ev.target.value)}
                className="bg-transparent border border-gray-200 dark:border-slate-700 rounded px-1.5 py-1"
              >
                {availableDims.map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.label}
                  </option>
                ))}
                <option value="none">None (flat list)</option>
              </select>
            </label>
            <span className="text-gray-400 dark:text-slate-500">
              Showing {shownCount} of {expectations.length} sources
            </span>
          </div>

          {groups.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
              No sources match the current filters.
            </p>
          ) : (
            <div className="overflow-x-auto mt-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 dark:text-slate-400 border-b border-gray-100 dark:border-slate-800">
                    <th className="py-2 pr-3 font-medium">Wanted source (CSV)</th>
                    <th className="py-2 pr-3 font-medium">In index</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    {canEdit && <th className="py-2 font-medium" />}
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => {
                    const flat = g.key === "__all__";
                    const collapsed = collapsedGroups.has(g.key);
                    return (
                      <Fragment key={g.key}>
                        {!flat && (
                          <tr className="bg-gray-50/70 dark:bg-slate-800/40 border-b border-gray-100 dark:border-slate-800">
                            <td colSpan={colCount} className="px-1 py-1.5">
                              <button
                                onClick={() => toggleGroup(g.key)}
                                aria-expanded={!collapsed}
                                className="w-full flex items-center gap-2 text-left"
                              >
                                <Chevron open={!collapsed} />
                                <span className="font-medium text-sm">{g.label}</span>
                                <span className="text-xs text-gray-400 dark:text-slate-500">
                                  ({g.items.length})
                                </span>
                                <span className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
                                  {g.counts.missing > 0 && (
                                    <span
                                      className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.missing.cls}`}
                                    >
                                      {g.counts.missing} missing
                                    </span>
                                  )}
                                  {g.counts.review > 0 && (
                                    <span
                                      className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.review.cls}`}
                                    >
                                      {g.counts.review} review
                                    </span>
                                  )}
                                  {g.counts.covered > 0 && (
                                    <span
                                      className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.covered_url.cls}`}
                                    >
                                      {g.counts.covered} covered
                                    </span>
                                  )}
                                  {g.counts.acked > 0 && (
                                    <span
                                      className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.acked.cls}`}
                                    >
                                      {g.counts.acked} ack
                                    </span>
                                  )}
                                </span>
                              </button>
                            </td>
                          </tr>
                        )}
                        {(flat || !collapsed) && g.items.map((e) => renderRow(e))}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
