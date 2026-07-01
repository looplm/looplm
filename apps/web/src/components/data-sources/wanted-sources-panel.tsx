"use client";

/**
 * Wanted-status source registry: declare which sources SHOULD be in the index
 * (CSV import or manual edits), run a gap analysis against what actually is,
 * and export the result as a markdown report for the indexing-pipeline owners.
 */

import { useCallback, useEffect, useState } from "react";

import {
  deleteSourceExpectation,
  listSourceExpectations,
  updateSourceExpectation,
} from "@/lib/api";
import type {
  GapRowResult,
  GapRowStatus,
  SourceExpectation,
} from "@/lib/api-types/source-registry";

import { SourceExpectationList } from "./source-expectation-list";
import { WantedSourcesInfo } from "./wanted-sources-info";
import { WantedSourcesToolbar } from "./wanted-sources-toolbar";
import {
  ALL_BUCKETS,
  bucketOf,
  DEFAULT_BUCKETS,
  type FilterBucket,
  GROUP_DIMENSIONS,
  type Group,
  STATUS_ORDER,
} from "./source-registry-shared";
import { useSourceGapAnalysis } from "./use-source-gap-analysis";

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

  // View controls: which statuses to show, what to cluster by, collapsed groups.
  const [visibleStatuses, setVisibleStatuses] = useState<Set<FilterBucket>>(
    () => new Set(DEFAULT_BUCKETS),
  );
  const [groupBy, setGroupBy] = useState<string>(""); // "" = auto, "none" = flat
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());
  const [showInfo, setShowInfo] = useState(false);

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

  const { run, running, handleImport, handleRun, handleCancel, handleDownloadReport } =
    useSourceGapAnalysis(providerId, loadExpectations, setError, setNotice);

  useEffect(() => {
    loadExpectations();
  }, [loadExpectations]);

  const verdicts: Record<string, GapRowResult> = {};
  for (const row of run?.results?.rows ?? []) verdicts[row.expectation_id] = row;

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

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mt-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <div>
          <div className="flex items-center gap-1.5">
            <h2 className="text-lg font-semibold">Wanted sources</h2>
            <button
              onClick={() => setShowInfo((v) => !v)}
              aria-expanded={showInfo}
              aria-label="How matching works"
              title="How matching works"
              className={`flex h-5 w-5 items-center justify-center rounded-full border text-[11px] font-semibold leading-none transition-colors ${
                showInfo
                  ? "border-indigo-500 bg-indigo-600 text-white"
                  : "border-gray-300 dark:border-slate-600 text-gray-500 dark:text-slate-400 hover:border-indigo-500 hover:text-indigo-600 dark:hover:text-indigo-400"
              }`}
            >
              i
            </button>
          </div>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            The sources that should be retrievable from this index. Import the source list as
            CSV, then run a gap analysis to compare it against what is actually indexed.
          </p>
        </div>
        <WantedSourcesToolbar
          canEdit={canEdit}
          hasExpectations={expectations.length > 0}
          running={running}
          run={run}
          onImport={handleImport}
          onRun={handleRun}
          onCancel={handleCancel}
          onDownloadReport={handleDownloadReport}
        />
      </div>

      {showInfo && (
        <div className="mt-3">
          <WantedSourcesInfo />
        </div>
      )}

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
      {run?.status === "cancelled" && (
        <div className="bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 text-sm rounded-lg px-4 py-2 my-3">
          Gap analysis was stopped before it finished. Run it again to get a full result.
        </div>
      )}
      {run?.status === "failed" && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-2 my-3">
          Gap analysis failed: {run.error}
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
        <SourceExpectationList
          run={run}
          summary={summary}
          visibleStatuses={visibleStatuses}
          toggleStatus={toggleStatus}
          resetStatuses={resetStatuses}
          isDefaultFilter={isDefaultFilter}
          resolvedGroupBy={resolvedGroupBy}
          availableDims={availableDims}
          setGroupBy={setGroupBy}
          groups={groups}
          collapsedGroups={collapsedGroups}
          toggleGroup={toggleGroup}
          verdicts={verdicts}
          expectationsCount={expectations.length}
          shownCount={shownCount}
          canEdit={canEdit}
          onAck={handleAck}
          onUnack={handleUnack}
          onDelete={handleDelete}
        />
      )}
    </div>
  );
}
