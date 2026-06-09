"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTheme } from "next-themes";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  Panel,
  useNodesState,
  useEdgesState,
  useReactFlow,
  useViewport,
  type NodeProps,
  type Node,
  type Edge,
  Handle,
  Position,
} from "@xyflow/react";
import type { AggregateGraphResponse } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import {
  getLayoutedElements,
  getNodeColors,
  RUN_TYPE_COLORS,
} from "@/lib/graph-utils";

// --- Custom aggregate node data ---

interface AggregateNodeData {
  label: string;
  name: string;
  runType?: string;
  executionCount: number;
  avgDurationMs?: number;
  failureCount: number;
  successCount: number;
  [key: string]: unknown;
}

// --- Custom node component ---

function AggregateNode({ data, selected }: NodeProps<Node<AggregateNodeData>>) {
  const isDark = (data as any).__isDark ?? true;
  const colors = getNodeColors(data.runType, isDark);
  const badgeColors =
    (data.runType && RUN_TYPE_COLORS[data.runType]) ||
    "bg-slate-500/20 text-gray-600 dark:text-slate-300 border-slate-500/30";

  const failureRate =
    data.executionCount > 0
      ? ((data.failureCount / data.executionCount) * 100).toFixed(0)
      : "0";

  return (
    <div
      className="rounded-lg px-3 py-2.5 min-w-[200px] max-w-[280px] shadow-lg cursor-pointer transition-shadow"
      style={{
        background: colors.bg,
        border: `1.5px solid ${selected ? "#818cf8" : colors.border}`,
        color: colors.text,
        boxShadow: selected ? "0 0 0 2px rgba(129, 140, 248, 0.3)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />

      <div className="flex items-center gap-1.5 mb-1.5">
        {data.runType && (
          <span className={`text-[9px] px-1 py-0.5 rounded border font-mono leading-none ${badgeColors}`}>
            {data.runType}
          </span>
        )}
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100/60 dark:bg-slate-800/60 text-gray-600 dark:text-slate-300 font-mono">
          {data.executionCount}x
        </span>
      </div>

      <div className="text-xs font-medium truncate leading-tight mb-1.5" title={data.name}>
        {data.name}
      </div>

      <div className="flex items-center gap-2 text-[10px] opacity-80">
        {data.avgDurationMs != null && (
          <span>avg {formatDuration(data.avgDurationMs)}</span>
        )}
        {data.failureCount > 0 && (
          <span className="text-red-400">{failureRate}% fail</span>
        )}
      </div>

      {data.executionCount > 0 && data.failureCount > 0 && (
        <div className="mt-1.5 h-1 rounded-full bg-gray-200/50 dark:bg-slate-700/50 overflow-hidden">
          <div
            className="h-full rounded-full bg-red-500/70"
            style={{ width: `${failureRate}%` }}
          />
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { aggregateNode: AggregateNode };

// --- Floating preview that tracks node position ---

const PREVIEW_W = 300;
const PREVIEW_H_ESTIMATE = 300;
const GAP = 12;

function FloatingAggregatePreview({
  nodeId,
  data,
  containerRef,
  onClose,
}: {
  nodeId: string;
  data: AggregateNodeData;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onClose: () => void;
}) {
  const { getNode } = useReactFlow();
  const { x: vx, y: vy, zoom } = useViewport();

  const node = getNode(nodeId);
  if (!node) return null;

  const nodeW = node.measured?.width ?? 220;
  const cW = containerRef.current?.clientWidth ?? 1000;
  const cH = containerRef.current?.clientHeight ?? 600;

  // Default: right of node
  let left = (node.position.x + nodeW) * zoom + vx + GAP;
  let top = node.position.y * zoom + vy;

  // Flip to left if overflowing
  if (left + PREVIEW_W > cW - 8) {
    left = node.position.x * zoom + vx - PREVIEW_W - GAP;
  }
  if (top + PREVIEW_H_ESTIMATE > cH - 8) {
    top = cH - PREVIEW_H_ESTIMATE - 8;
  }
  if (top < 8) top = 8;
  if (left < 8) left = 8;

  const badgeColors =
    (data.runType && RUN_TYPE_COLORS[data.runType]) ||
    "bg-slate-500/20 text-gray-600 dark:text-slate-300 border-slate-500/30";

  const failureRate =
    data.executionCount > 0
      ? ((data.failureCount / data.executionCount) * 100).toFixed(1)
      : "0";
  const successRate =
    data.executionCount > 0
      ? ((data.successCount / data.executionCount) * 100).toFixed(1)
      : "0";

  return (
    <div
      className="absolute z-10 pointer-events-auto"
      style={{ left, top, width: PREVIEW_W }}
    >
      <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg shadow-2xl p-4 text-sm">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2 min-w-0">
            {data.runType && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono shrink-0 ${badgeColors}`}>
                {data.runType}
              </span>
            )}
            <span className="font-medium text-gray-900 dark:text-white truncate" title={data.name}>
              {data.name}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 dark:text-slate-500 hover:text-gray-900 dark:hover:text-white ml-2 shrink-0"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Stats */}
        <div className="space-y-2 mb-3">
          <div className="flex items-center justify-between">
            <span className="text-gray-500 dark:text-slate-400">Total executions</span>
            <span className="text-gray-900 dark:text-white font-mono text-xs font-medium">{data.executionCount}</span>
          </div>
          {data.avgDurationMs != null && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Avg duration</span>
              <span className="text-gray-900 dark:text-white font-mono text-xs">{formatDuration(data.avgDurationMs)}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-gray-500 dark:text-slate-400">Successful</span>
            <span className="text-green-400 font-mono text-xs">
              {data.successCount} <span className="text-gray-400 dark:text-slate-500">({successRate}%)</span>
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-500 dark:text-slate-400">Failed</span>
            <span className="text-red-400 font-mono text-xs">
              {data.failureCount} <span className="text-gray-400 dark:text-slate-500">({failureRate}%)</span>
            </span>
          </div>

          {/* Stacked bar */}
          {data.executionCount > 0 && (
            <div>
              <div className="h-2 rounded-full bg-gray-200/50 dark:bg-slate-700/50 overflow-hidden flex mt-1">
                <div className="h-full bg-green-500/70" style={{ width: `${successRate}%` }} />
                <div className="h-full bg-red-500/70" style={{ width: `${failureRate}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">
                <span>success</span>
                <span>failure</span>
              </div>
            </div>
          )}

          {data.runType && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Run type</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${badgeColors}`}>
                {data.runType}
              </span>
            </div>
          )}
        </div>

        {/* Link */}
        <Link
          href={`/traces?search=${encodeURIComponent(data.name)}`}
          className="block w-full text-center px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded transition-colors"
        >
          View Matching Traces &rarr;
        </Link>
      </div>
    </div>
  );
}

// --- Main component ---

interface AggregateGraphProps {
  data: AggregateGraphResponse;
}

const FIT_VIEW_OPTIONS = { padding: 0.2 };
const PRO_OPTIONS = { hideAttribution: true };

export default function AggregateGraph({ data }: AggregateGraphProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeData, setSelectedNodeData] = useState<AggregateNodeData | null>(null);

  // Escape: close preview first, then fullscreen
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedNodeId) {
          setSelectedNodeId(null);
          setSelectedNodeData(null);
        } else if (isFullscreen) {
          setIsFullscreen(false);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isFullscreen, selectedNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<AggregateNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    const dark = isDarkRef.current;
    const rawNodes: Node<AggregateNodeData>[] = (data.nodes ?? []).map((n) => ({
      id: n.id,
      type: "aggregateNode",
      position: { x: 0, y: 0 },
      data: {
        label: n.name,
        name: n.name,
        runType: n.run_type ?? undefined,
        executionCount: n.execution_count,
        avgDurationMs: n.avg_duration_ms ?? undefined,
        failureCount: n.failure_count,
        successCount: n.success_count,
        __isDark: dark,
      },
    }));

    const maxWeight = Math.max(1, ...(data.edges ?? []).map((e) => e.weight));
    const rawEdges: Edge[] = (data.edges ?? []).map((e, i) => {
      const thickness = 1 + (e.weight / maxWeight) * 4;
      return {
        id: `ae-${i}-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        style: { stroke: dark ? "#475569" : "#cbd5e1", strokeWidth: thickness },
        label: e.weight > 1 ? `${e.weight}x` : undefined,
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
  }, [data]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedNodeData(node.data as AggregateNodeData);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedNodeData(null);
  }, []);

  return (
    <div
      ref={containerRef}
      className={
        isFullscreen
          ? "fixed inset-0 z-50 bg-gray-50 dark:bg-slate-950"
          : "w-full h-[600px] rounded-xl overflow-hidden border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-950 relative"
      }
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={FIT_VIEW_OPTIONS}
        minZoom={0.1}
        maxZoom={2}
        proOptions={PRO_OPTIONS}
        colorMode={isDark ? "dark" : "light"}
      >
        <Controls className="!bg-gray-100 dark:!bg-slate-800 !border-gray-200 dark:!border-slate-700 !shadow-lg [&>button]:!bg-gray-100 dark:[&>button]:!bg-slate-800 [&>button]:!border-gray-200 dark:[&>button]:!border-slate-700 [&>button]:!text-gray-600 dark:[&>button]:!text-slate-300 [&>button:hover]:!bg-gray-200 dark:[&>button:hover]:!bg-slate-700" />
        <MiniMap
          className="!bg-white dark:!bg-slate-900 !border-gray-200 dark:!border-slate-700"
          nodeColor={(node) => {
            const rt = (node.data as AggregateNodeData)?.runType;
            return getNodeColors(rt, isDark).border;
          }}
          maskColor={isDark ? "rgba(0, 0, 0, 0.6)" : "rgba(0, 0, 0, 0.1)"}
        />
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
        {selectedNodeId && selectedNodeData && (
          <FloatingAggregatePreview
            nodeId={selectedNodeId}
            data={selectedNodeData}
            containerRef={containerRef}
            onClose={() => { setSelectedNodeId(null); setSelectedNodeData(null); }}
          />
        )}
      </ReactFlow>
    </div>
  );
}
