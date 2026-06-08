"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  analyzeRequestClusters,
  getRequestClusters,
  getLatestRequestClusters,
  stopRequestClusters,
  getRetrievalSources,
  getRetrievalActivity,
  type AnalyticsFilters,
  type RequestClustersResponse,
  type RetrievalSource,
  type RetrievalActivityPoint,
} from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import { HeatmapMatrix } from "./heatmap-matrix";

export default function AnalyticsPage() {
  const { startDate, endDate, environment, userFilterMode, filteredUsers, traceNames } =
    useGlobalFilters();

  const filters = useMemo<AnalyticsFilters>(() => {
    const f: AnalyticsFilters = {};
    if (startDate) f.from_date = new Date(startDate).toISOString();
    if (endDate) f.to_date = new Date(endDate).toISOString();
    if (environment && environment !== "all") f.environment = environment;
    if (filteredUsers.length > 0) {
      if (userFilterMode === "exclude") f.exclude_user_ids = filteredUsers;
      else f.include_user_ids = filteredUsers;
    }
    return f;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startDate, endDate, environment, userFilterMode, filteredUsers, traceNames]);

  // --- Request clusters (async LLM analysis) ---
  const [clusters, setClusters] = useState<RequestClustersResponse | null>(null);
  const [clustersId, setClustersId] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(true);

  const running = clusters ? ["pending", "running"].includes(clusters.status) : false;

  useEffect(() => {
    setLoadingLatest(true);
    getLatestRequestClusters()
      .then((data) => {
        setClusters(data);
        if (["pending", "running"].includes(data.status)) setClustersId(data.id);
      })
      .catch(() => setClusters(null))
      .finally(() => setLoadingLatest(false));
  }, []);

  async function handleAnalyze() {
    setTriggering(true);
    try {
      const { analysis_id } = await analyzeRequestClusters({ ...filters, limit: 300 });
      setClustersId(analysis_id);
      setClusters(await getRequestClusters(analysis_id));
    } catch (err: any) {
      toast.error("Analysis failed", { description: err.message });
    } finally {
      setTriggering(false);
    }
  }

  async function handleStop() {
    if (!clustersId || !running) return;
    try {
      await stopRequestClusters(clustersId);
      setClusters((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
      toast.success("Analysis stopped");
    } catch (err: any) {
      toast.error("Failed to stop analysis", { description: err.message });
    }
  }

  // Poll while running
  useEffect(() => {
    if (!clustersId || !running) return;
    const interval = setInterval(async () => {
      try {
        const updated = await getRequestClusters(clustersId);
        setClusters(updated);
        if (updated.status === "completed") {
          clearInterval(interval);
          toast.success(`Identified ${updated.themes.length} request types from ${updated.total_requests} requests`);
        } else if (updated.status === "failed") {
          clearInterval(interval);
          toast.error("Analysis failed", { description: updated.error || "Unknown error" });
        } else if (updated.status === "cancelled") {
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [clustersId, running]);

  // --- Retrieval insights ---
  const [sources, setSources] = useState<RetrievalSource[] | null>(null);
  const [activity, setActivity] = useState<RetrievalActivityPoint[] | null>(null);

  const loadRetrieval = useCallback(() => {
    setSources(null);
    setActivity(null);
    getRetrievalSources(filters).then(setSources).catch(() => setSources([]));
    getRetrievalActivity(filters).then(setActivity).catch(() => setActivity([]));
  }, [filters]);

  useEffect(() => {
    loadRetrieval();
  }, [loadRetrieval]);

  const hasClusters = clusters?.status === "completed" && clusters.themes.length > 0;

  return (
    <div>
      <h1 className="text-3xl font-bold mb-2">Analytics</h1>
      <p className="text-gray-500 dark:text-slate-400 mb-8">
        Discover what users ask for most, how those request types succeed or fail, and what your retrieval layer pulls in.
      </p>

      {/* Request types × outcome */}
      <section className="mb-10">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Request types &times; outcome</h2>
          {running ? (
            <button
              onClick={handleStop}
              className="px-3 py-1.5 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-300 text-sm hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
            >
              Stop ({clusters?.processed_requests ?? 0}/{clusters?.total_requests ?? 0})
            </button>
          ) : (
            <button
              onClick={handleAnalyze}
              disabled={triggering}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {triggering ? "Starting..." : hasClusters ? "Re-analyze" : "Analyze request types"}
            </button>
          )}
        </div>

        {running && clusters && (
          <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-200 dark:border-indigo-900/50">
            <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <span className="text-sm text-indigo-700 dark:text-indigo-300">
              {clusters.status === "pending"
                ? "Starting analysis..."
                : `Clustering requests... ${clusters.processed_requests} of ${clusters.total_requests}`}
            </span>
            {clusters.total_requests > 0 && (
              <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                  style={{ width: `${Math.round((clusters.processed_requests / clusters.total_requests) * 100)}%` }}
                />
              </div>
            )}
          </div>
        )}

        {clusters?.status === "failed" && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-900/50 text-sm text-red-700 dark:text-red-300">
            Analysis failed: {clusters.error || "Unknown error"}
          </div>
        )}

        {loadingLatest ? (
          <p className="text-gray-500 dark:text-slate-400">Loading...</p>
        ) : hasClusters ? (
          <>
            {clusters?.completed_at && (
              <p className="text-xs text-gray-400 dark:text-slate-500 mb-3">
                Last analyzed {new Date(clusters.completed_at).toLocaleString()} ({clusters.total_requests} requests)
              </p>
            )}
            <HeatmapMatrix themes={clusters!.themes} />
          </>
        ) : !running ? (
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
            Cluster user requests into intent themes to see which request types are succeeding or failing. Uses the current date/environment filters.
          </div>
        ) : null}
      </section>

      {/* Retrieval insights */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h2 className="text-lg font-semibold mb-3">Top retrieved sources</h2>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
            {sources === null ? (
              <p className="text-sm text-gray-400 dark:text-slate-500">Loading...</p>
            ) : sources.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-slate-500">No retrieval sources in this window.</p>
            ) : (
              <ul className="space-y-2">
                {sources.map((s) => {
                  const max = sources[0].count || 1;
                  return (
                    <li key={s.url} className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm text-gray-700 dark:text-slate-200 hover:text-indigo-500 hover:underline truncate block"
                          title={s.url}
                        >
                          {s.label || s.domain || s.url}
                        </a>
                        {s.domain && s.label !== s.domain && (
                          <p className="text-xs text-gray-400 dark:text-slate-500 truncate">{s.domain}</p>
                        )}
                        <div className="mt-1 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                          <div className="h-full bg-indigo-500" style={{ width: `${(s.count / max) * 100}%` }} />
                        </div>
                      </div>
                      <span className="flex-shrink-0 text-xs text-gray-400 dark:text-slate-500 w-8 text-right">{s.count}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold mb-3">Retrieval activity</h2>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
            <RetrievalActivity points={activity} />
          </div>
        </div>
      </section>
    </div>
  );
}

function RetrievalActivity({ points }: { points: RetrievalActivityPoint[] | null }) {
  const [hover, setHover] = useState<number | null>(null);
  if (points === null) return <p className="text-sm text-gray-400 dark:text-slate-500">Loading...</p>;
  if (points.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500">No retrieval spans in this window.</p>;

  const max = Math.max(1, ...points.map((p) => p.count));
  const totals = points.reduce(
    (acc, p) => ({ count: acc.count + p.count, tin: acc.tin + p.tokens_in, tout: acc.tout + p.tokens_out }),
    { count: 0, tin: 0, tout: 0 },
  );

  return (
    <div>
      <div className="flex gap-[3px] items-end h-32 mb-2">
        {points.map((p, i) => (
          <div
            key={p.date}
            className="flex-1 relative flex flex-col justify-end"
            style={{ minWidth: 4 }}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            {hover === i && (
              <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                <div className="font-medium mb-1">{p.date}</div>
                <div>{p.count} retrievals</div>
                <div>{p.avg_latency_ms} ms avg</div>
                <div>{p.tokens_in + p.tokens_out} tokens</div>
              </div>
            )}
            <div
              className="w-full rounded-t-sm bg-indigo-500 transition-opacity"
              style={{
                height: `${Math.round((p.count / max) * 100)}%`,
                minHeight: p.count > 0 ? 4 : 0,
                opacity: hover === null || hover === i ? 1 : 0.4,
              }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-gray-400 dark:text-slate-500">
        <span>{totals.count} retrievals</span>
        <span>{(totals.tin + totals.tout).toLocaleString()} tokens</span>
      </div>
    </div>
  );
}
