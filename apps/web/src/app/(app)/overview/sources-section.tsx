"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getIndexFileTypes,
  getIndexSummary,
  type LiveState,
  type SourceDimension,
  type SourcesOverview,
} from "@/lib/api";
import type { IndexFileTypesResponse, IndexSummary } from "@/lib/api-types/index-explorer";
import { MeterBar } from "@/components/charts/meter-bar";
import { Sparkline } from "@/components/charts/sparkline";
import Tooltip from "@/components/tooltip";
import { SectionShell } from "./section-shell";
import { SERIES, SOURCE_DIMENSIONS, SPARK, TIPS } from "./overview-constants";
import { formatNumber, formatRate } from "./overview-format";
import { SourcesDimension, type DimensionRow } from "./sources-dimension";

export interface SourcesSectionProps {
  sources: SourcesOverview | null;
  loading: boolean;
  error: unknown;
}

const idle = <T,>(): LiveState<T> => ({ status: "idle" });

export function SourcesSection({ sources, loading, error }: SourcesSectionProps) {
  const [dimension, setDimension] = useState<SourceDimension>("registry");
  const [registryField, setRegistryField] = useState<string>("typ");
  const [fileTypes, setFileTypes] = useState<Record<string, LiveState<IndexFileTypesResponse>>>({});
  const [summaries, setSummaries] = useState<Record<string, LiveState<IndexSummary>>>({});

  const providers = sources?.providers ?? [];
  const providerIds = providers.map((p) => p.id).join(",");
  const needsLive = dimension === "filetype" || dimension === "provider";

  /**
   * Live index reads happen only when a tab that needs them is opened, and each provider
   * is tracked separately with allSettled, so one dead index shows its own retry row while
   * the others render normally.
   */
  useEffect(() => {
    if (!needsLive || providers.length === 0) return;
    let cancelled = false;

    /**
     * Merge results in keyed by provider id, so a slow provider's response cannot clobber
     * a newer entry for a different one.
     */
    function load<T>(
      current: Record<string, LiveState<T>>,
      setState: React.Dispatch<React.SetStateAction<Record<string, LiveState<T>>>>,
      fetchOne: (providerId: string) => Promise<T>,
    ) {
      const pending = providers.filter((p) => current[p.id]?.status === undefined);
      if (pending.length === 0) return;

      setState((prev) => {
        const next = { ...prev };
        for (const p of pending) next[p.id] = { status: "loading" };
        return next;
      });

      // allSettled, never all: one dead index must not blank the others.
      Promise.allSettled(pending.map((p) => fetchOne(p.id))).then((results) => {
        if (cancelled) return;
        setState((prev) => {
          const next = { ...prev };
          results.forEach((res, i) => {
            next[pending[i].id] =
              res.status === "fulfilled"
                ? { status: "ok", data: res.value }
                : { status: "error", error: res.reason };
          });
          return next;
        });
      });
    }

    if (dimension === "filetype") load(fileTypes, setFileTypes, getIndexFileTypes);
    else load(summaries, setSummaries, getIndexSummary);

    return () => {
      cancelled = true;
    };
  }, [dimension, providerIds, needsLive]);

  const retry = (providerId: string) => {
    if (dimension === "filetype") {
      setFileTypes((prev) => ({ ...prev, [providerId]: idle() }));
      getIndexFileTypes(providerId)
        .then((data) => setFileTypes((p) => ({ ...p, [providerId]: { status: "ok", data } })))
        .catch((err) =>
          setFileTypes((p) => ({ ...p, [providerId]: { status: "error", error: err } })),
        );
    } else {
      setSummaries((prev) => ({ ...prev, [providerId]: idle() }));
      getIndexSummary(providerId)
        .then((data) => setSummaries((p) => ({ ...p, [providerId]: { status: "ok", data } })))
        .catch((err) =>
          setSummaries((p) => ({ ...p, [providerId]: { status: "error", error: err } })),
        );
    }
  };

  // Memoized so the fallback [] does not produce a new array identity every render.
  const dimensions = useMemo(() => sources?.registry?.dimensions ?? [], [sources]);
  const activeDimension = useMemo(
    () => dimensions.find((d) => d.key === registryField) ?? dimensions[0],
    [dimensions, registryField],
  );

  const registryRows: DimensionRow[] = (activeDimension?.values ?? []).map((v) => ({
    key: v.value ?? "__unset__",
    label: v.label,
    count: v.count,
    muted: v.value === null,
    sublabel: `${v.covered} covered, ${v.missing} missing`,
  }));

  const fileTypeRows: DimensionRow[] = providers.flatMap((p) => {
    const state = fileTypes[p.id];
    if (state?.status !== "ok" || !state.data) return [];
    return (state.data.values ?? []).map((v: { value: string; count: number }) => ({
      key: `${p.id}:${v.value}`,
      label: v.value,
      count: v.count,
      sublabel: p.name,
    }));
  });

  const providerRows: DimensionRow[] = providers.map((p) => {
    const state = summaries[p.id];
    return {
      key: p.id,
      label: p.name,
      count: state?.status === "ok" && state.data ? state.data.document_count : p.source_count,
      sublabel: p.type,
    };
  });

  const coverage = sources?.coverage;
  const liveErrors = providers.filter(
    (p) => (dimension === "filetype" ? fileTypes[p.id] : summaries[p.id])?.status === "error",
  );
  const liveLoading = providers.some(
    (p) => (dimension === "filetype" ? fileTypes[p.id] : summaries[p.id])?.status === "loading",
  );

  return (
    <SectionShell
      title="Indexed data sources"
      subtitle="Current index state, not filtered by the selected date range"
      loading={loading}
      error={error}
      empty={providers.length === 0}
      emptyTitle="No index providers connected yet"
      emptyHint="Connect a retrieval index to see how many sources are indexed and of what kind."
      emptyHref="/data-sources"
      emptyCta="Go to Data Sources"
      action={
        <div className="flex items-center gap-1">
          {SOURCE_DIMENSIONS.map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => setDimension(d.key)}
              className={`px-2.5 py-1 text-xs font-medium rounded-full transition-all ${
                dimension === d.key
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-700"
              }`}
            >
              {d.label}
            </button>
          ))}
          {needsLive ? (
            <Tooltip content={TIPS.fileType}>
              <span className="ml-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400">
                Live
              </span>
            </Tooltip>
          ) : null}
        </div>
      }
    >
      {dimension === "registry" ? (
        <div>
          {dimensions.length > 1 ? (
            <select
              value={activeDimension?.key ?? ""}
              onChange={(e) => setRegistryField(e.target.value)}
              className="mb-3 text-xs rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-gray-700 dark:text-slate-200"
            >
              {dimensions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label} ({d.distinct_values})
                </option>
              ))}
            </select>
          ) : null}
          <SourcesDimension
            rows={registryRows}
            unit="sources"
            emptyLabel="No expected sources imported yet"
          />
        </div>
      ) : null}

      {dimension === "coverage" ? (
        coverage?.latest ? (
          <div>
            <MeterBar
              showLegend
              segments={[
                {
                  key: "covered",
                  label: "Covered",
                  value: coverage.latest.covered,
                  className: SERIES.covered,
                },
                {
                  key: "review",
                  label: "Review",
                  value: coverage.latest.review,
                  className: SERIES.review,
                },
                {
                  key: "missing",
                  label: "Missing",
                  value: coverage.latest.missing,
                  className: SERIES.missing,
                },
                {
                  key: "acked",
                  label: "Acknowledged",
                  value: coverage.latest.acked,
                  className: SERIES.acked,
                },
              ]}
            />
            <div className="flex items-center justify-between mt-3">
              <Tooltip content={TIPS.coverage}>
                <span className="text-xs text-gray-500 dark:text-slate-400">
                  {formatRate(coverage.latest.covered_rate)} of{" "}
                  {formatNumber(coverage.latest.total)} sources covered
                </span>
              </Tooltip>
              {coverage.history.length > 1 ? (
                <span className="w-24">
                  <Sparkline
                    data={coverage.history.map((h) => h.covered_rate)}
                    className={SPARK.feedback}
                  />
                </span>
              ) : null}
            </div>
            {coverage.stale && coverage.stale_reason ? (
              <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                {coverage.stale_reason}
              </p>
            ) : null}
            {coverage.history.length === 1 ? (
              <p className="mt-2 text-[10px] text-gray-400 dark:text-slate-500">
                Only one gap analysis on record, so there is no trend yet.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-slate-400">
            Coverage has not been analyzed yet. Run a gap analysis from Data Sources.
          </p>
        )
      ) : null}

      {dimension === "filetype" ? (
        <div>
          {liveLoading ? (
            <div className="space-y-2">
              {providers.map((p) => (
                <div
                  key={p.id}
                  className="h-4 rounded bg-gray-100 dark:bg-slate-800 animate-pulse"
                />
              ))}
            </div>
          ) : (
            <SourcesDimension
              rows={fileTypeRows}
              unit="chunks"
              emptyLabel="This index exposes no file-type field"
            />
          )}
        </div>
      ) : null}

      {dimension === "provider" ? (
        <div>
          <SourcesDimension rows={providerRows} unit="documents" />
          {sources?.by_type?.length ? (
            <p className="mt-3 text-xs text-gray-500 dark:text-slate-400">
              {sources.by_type
                .map((t) => `${t.provider_count} ${t.type.replace(/_/g, " ")}`)
                .join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {liveErrors.length > 0 ? (
        <div className="mt-3 space-y-1">
          {liveErrors.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between gap-2 text-xs text-amber-700 dark:text-amber-400"
            >
              <span className="truncate">Could not read {p.name} from the index</span>
              <button
                type="button"
                onClick={() => retry(p.id)}
                className="font-medium hover:underline shrink-0"
              >
                Retry
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </SectionShell>
  );
}
