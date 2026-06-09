"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getIntegrations,
  getAggregateGraph,
  type Integration,
  type AggregateGraphResponse,
} from "@/lib/api";
import AggregateGraph from "@/components/aggregate-graph";

type TimeRange = "7d" | "30d" | "90d";

function getStartDate(range: TimeRange): string {
  const now = new Date();
  const days = range === "7d" ? 7 : range === "30d" ? 30 : 90;
  now.setDate(now.getDate() - days);
  return now.toISOString();
}

export default function AggregateGraphPage() {
  const router = useRouter();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState<string>("");
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [graphData, setGraphData] = useState<AggregateGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load integrations
  useEffect(() => {
    getIntegrations()
      .then((r) => {
        const filtered = r.data.filter((i) => i.type !== "json_file");
        setIntegrations(filtered);
        if (filtered.length > 0 && !selectedIntegration) {
          setSelectedIntegration(filtered[0].id);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  // Load graph data when integration or time range changes
  useEffect(() => {
    if (!selectedIntegration) return;

    setLoading(true);
    setError(null);

    const params: Record<string, string> = {
      integration_id: selectedIntegration,
      start_after: getStartDate(timeRange),
    };

    getAggregateGraph(params)
      .then((data) => setGraphData(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedIntegration, timeRange]);

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <button onClick={() => router.back()} className="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white">
            &larr; Back
          </button>
          <h1 className="text-3xl font-bold">Execution Graph</h1>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-4 mb-6">
        <select
          value={selectedIntegration}
          onChange={(e) => setSelectedIntegration(e.target.value)}
          className="px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
        >
          <option value="">Select integration</option>
          {integrations.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>

        <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
          {(["7d", "30d", "90d"] as TimeRange[]).map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`px-3 py-1.5 text-sm ${
                timeRange === range
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
              }`}
            >
              {range}
            </button>
          ))}
        </div>

        {graphData && (
          <span className="text-xs text-gray-400 dark:text-slate-500">
            {graphData.total_traces_analyzed} traces analyzed &middot;{" "}
            {graphData.nodes?.length ?? 0} unique steps
          </span>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          Loading execution graph...
        </div>
      ) : !graphData || (graphData.nodes?.length ?? 0) === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          {selectedIntegration
            ? "No traces found for this integration and time range."
            : "Select an integration to view the execution graph."}
        </div>
      ) : (
        <AggregateGraph data={graphData} />
      )}
    </div>
  );
}
