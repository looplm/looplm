"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getRetrievalPipeline,
  type AnalyticsFilters,
  type RetrievalPipelineResponse,
} from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import RetrievalPipelineGraph from "@/components/retrieval-pipeline-graph";
import RetrievalMetricsPanel from "@/components/retrieval-metrics-panel";

export default function PipelinePage() {
  const { startDate, endDate, environment, userFilterMode, filteredUsers } =
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
  }, [startDate, endDate, environment, userFilterMode, filteredUsers]);

  const [data, setData] = useState<RetrievalPipelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRetrievalPipeline(filters)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold">Pipeline</h1>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-1 max-w-3xl">
          Your RAG pipeline, painted from traces — query through retrieval to grounded
          answer. Each node is a stage; click one for its stats. Hybrid search (keyword +
          vector + RRF) and the semantic reranker run inside one Azure AI Search call but
          are shown as the distinct stages they are. Dashed nodes are part of the pipeline
          but not yet observable in the traces.
        </p>
      </div>

      {data && data.available && (
        <div className="flex items-center gap-4 mb-4 text-xs text-gray-400 dark:text-slate-500">
          <span>{data.rag_traces} RAG requests</span>
          <span>&middot;</span>
          <span>{data.traces_analyzed} traces analyzed</span>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          Reconstructing retrieval pipeline...
        </div>
      ) : !data || !data.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No RAG traces found for the selected filters. Sync traces from a retrieval app, or
          configure the retrieval span names in settings.
        </div>
      ) : (
        <RetrievalPipelineGraph data={data} />
      )}

      <RetrievalMetricsPanel />
    </div>
  );
}
