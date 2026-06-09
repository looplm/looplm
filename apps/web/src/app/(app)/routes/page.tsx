"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { useTheme } from "next-themes";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import {
  getIntegrations,
  getRouteAnalysis,
  type Integration,
  type RouteAnalysisResponse,
  type RouteNode,
} from "@/lib/api";
import { getLayoutedElements } from "@/lib/graph-utils";

interface BottleneckNode {
  node_id: string;
  name: string;
  run_type?: string;
  call_count: number;
  avg_latency_ms: number;
  error_rate: number;
  bottleneck_score: number;
  reason: string;
}

function computeBottlenecks(nodes: RouteNode[], limit = 10): BottleneckNode[] {
  if (nodes.length === 0) return [];
  const maxLatency = Math.max(1, ...nodes.map((n) => n.avg_latency_ms ?? 0));
  const maxCalls = Math.max(1, ...nodes.map((n) => n.call_count));

  const results: BottleneckNode[] = [];
  for (const node of nodes) {
    const lat = node.avg_latency_ms ?? 0;
    const latScore = lat / maxLatency;
    const freqScore = node.call_count / maxCalls;
    const errorScore = node.error_rate;
    const score = latScore * 0.4 + freqScore * 0.3 + errorScore * 0.3;

    const reasons: string[] = [];
    if (latScore > 0.7) reasons.push(`high latency (${Math.round(lat)}ms avg)`);
    if (freqScore > 0.7) reasons.push(`high frequency (${node.call_count} calls)`);
    if (errorScore > 0.1) reasons.push(`high error rate (${(node.error_rate * 100).toFixed(1)}%)`);

    if (reasons.length > 0) {
      results.push({
        node_id: node.id,
        name: node.name,
        run_type: node.run_type ?? undefined,
        call_count: node.call_count,
        avg_latency_ms: lat,
        error_rate: node.error_rate,
        bottleneck_score: Math.round(score * 10000) / 10000,
        reason: reasons.join("; "),
      });
    }
  }
  results.sort((a, b) => b.bottleneck_score - a.bottleneck_score);
  return results.slice(0, limit);
}

interface RouteNodeData {
  label: string;
  name: string;
  runType?: string;
  callCount: number;
  avgLatencyMs?: number;
  errorRate: number;
  [key: string]: unknown;
}

function latencyColor(ms: number | undefined, maxMs: number): string {
  if (ms == null || maxMs === 0) return "#22c55e";
  const ratio = ms / maxMs;
  if (ratio < 0.33) return "#22c55e";
  if (ratio < 0.66) return "#eab308";
  return "#ef4444";
}

function RouteNodeComponent({ data, selected }: NodeProps<Node<RouteNodeData>>) {
  const color = latencyColor(data.avgLatencyMs, (data as any).__maxLatency ?? 1000);
  const isDark = (data as any).__isDark;
  return (
    <div
      className="rounded-lg px-3 py-2 min-w-[180px] max-w-[260px] shadow-lg"
      style={{
        background: isDark ? "#1e293b" : "#ffffff",
        border: `2px solid ${selected ? "#818cf8" : color}`,
        color: isDark ? "#e2e8f0" : "#1f2937",
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />
      <div className="text-xs font-medium truncate mb-1">{data.name}</div>
      <div className="flex gap-2 text-[10px] opacity-80">
        <span>{data.callCount}x</span>
        {data.avgLatencyMs != null && <span>{Math.round(data.avgLatencyMs)}ms</span>}
        {data.errorRate > 0 && <span className="text-red-400">{(data.errorRate * 100).toFixed(0)}% err</span>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { routeNode: RouteNodeComponent };
const FIT_VIEW_OPTIONS = { padding: 0.2 };
const PRO_OPTIONS = { hideAttribution: true };

export default function RoutesPage() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;

  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState("");
  const [routeData, setRouteData] = useState<RouteAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen) setIsFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isFullscreen]);

  useEffect(() => {
    getIntegrations().then((r) => {
      const filtered = r.data.filter((i) => i.type !== "json_file");
      setIntegrations(filtered);
      if (filtered.length > 0) setSelectedIntegration(filtered[0].id);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedIntegration) return;
    setLoading(true);
    setError(null);
    getRouteAnalysis(selectedIntegration)
      .then((rd) => setRouteData(rd))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedIntegration]);

  const bottlenecks = useMemo(
    () => (routeData ? computeBottlenecks(routeData.nodes ?? []) : []),
    [routeData]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<RouteNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Only re-layout when routeData changes, not on isDark changes
  useEffect(() => {
    if (!routeData) { setNodes([]); setEdges([]); return; }
    const dark = isDarkRef.current;
    const maxLat = Math.max(1, ...(routeData.nodes ?? []).map((n) => n.avg_latency_ms ?? 0));
    const maxFreq = Math.max(1, ...(routeData.edges ?? []).map((e) => e.frequency));

    const rawNodes: Node<RouteNodeData>[] = (routeData.nodes ?? []).map((n) => ({
      id: n.id,
      type: "routeNode",
      position: { x: 0, y: 0 },
      data: {
        label: n.name,
        name: n.name,
        runType: n.run_type ?? undefined,
        callCount: n.call_count,
        avgLatencyMs: n.avg_latency_ms ?? undefined,
        errorRate: n.error_rate,
        __maxLatency: maxLat,
        __isDark: dark,
      } as RouteNodeData,
    }));

    const rawEdges: Edge[] = (routeData.edges ?? []).map((e, i) => {
      const thickness = 1 + (e.frequency / maxFreq) * 6;
      return {
        id: `re-${i}`,
        source: e.source,
        target: e.target,
        type: "default",
        style: { stroke: dark ? "#475569" : "#cbd5e1", strokeWidth: thickness },
        label: e.frequency > 1 ? `${e.frequency}x` : undefined,
        labelStyle: { fill: dark ? "#94a3b8" : "#64748b", fontSize: 10 },
        labelBgStyle: { fill: dark ? "#0f172a" : "#ffffff", fillOpacity: 0.8 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
      };
    });

    let cancelled = false;
    getLayoutedElements(rawNodes, rawEdges, "TB").then((layouted) => {
      if (!cancelled) { setNodes(layouted.nodes); setEdges(layouted.edges); }
    });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeData]);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Route Frequency Analysis</h1>

      <div className="flex items-center gap-4 mb-6">
        <select
          value={selectedIntegration}
          onChange={(e) => setSelectedIntegration(e.target.value)}
          className="px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
        >
          <option value="">Select integration</option>
          {integrations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
        {routeData && (
          <span className="text-xs text-gray-400 dark:text-slate-500">
            {routeData.total_traces} traces · {routeData.nodes?.length ?? 0} nodes · {routeData.edges?.length ?? 0} edges
          </span>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">Loading...</div>
      ) : routeData && (routeData.nodes?.length ?? 0) > 0 ? (
        <div
          className={
            isFullscreen
              ? "fixed inset-0 z-50 bg-gray-50 dark:bg-slate-950"
              : "w-full h-[500px] rounded-xl overflow-hidden border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-950 mb-6 relative"
          }
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={FIT_VIEW_OPTIONS}
            minZoom={0.1}
            maxZoom={2}
            proOptions={PRO_OPTIONS}
            colorMode={isDark ? "dark" : "light"}
          >
            <Controls className="!bg-gray-100 dark:!bg-slate-800 !border-gray-200 dark:!border-slate-700 !shadow-lg [&>button]:!bg-gray-100 dark:[&>button]:!bg-slate-800 [&>button]:!border-gray-200 dark:[&>button]:!border-slate-700 [&>button]:!text-gray-600 dark:[&>button]:!text-slate-300 [&>button:hover]:!bg-gray-200 dark:[&>button:hover]:!bg-slate-700" />
            <MiniMap className="!bg-white dark:!bg-slate-900 !border-gray-200 dark:!border-slate-700" maskColor={isDark ? "rgba(0,0,0,0.6)" : "rgba(0,0,0,0.1)"} />
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color={isDark ? "#334155" : "#d1d5db"} />
            <Panel position="top-right" className="flex items-center gap-2">
              {isFullscreen && (
                <span className="text-[10px] text-gray-400 dark:text-slate-500 mr-1">Esc to close</span>
              )}
              <button
                onClick={() => setIsFullscreen((f) => !f)}
                className="p-1.5 rounded bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {isFullscreen ? (
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
                )}
              </button>
            </Panel>
          </ReactFlow>
        </div>
      ) : (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          {selectedIntegration ? "No route data found." : "Select an integration."}
        </div>
      )}

      {bottlenecks.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold mb-4">Bottleneck Nodes</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bottlenecks.map((b) => (
              <div key={b.node_id} className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">{b.name}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-300">
                    score: {(b.bottleneck_score * 100).toFixed(0)}
                  </span>
                </div>
                <div className="text-xs text-gray-500 dark:text-slate-400 space-y-1">
                  <div>{b.call_count} calls · {Math.round(b.avg_latency_ms)}ms avg · {(b.error_rate * 100).toFixed(1)}% errors</div>
                  <div className="text-amber-400">{b.reason}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
