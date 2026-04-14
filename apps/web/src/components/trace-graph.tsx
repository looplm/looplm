"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import type { TraceTreeNode, TraceDetail } from "@/lib/api";
import StatusBadge from "@/components/status-badge";
import { formatDuration } from "@/lib/format";
import {
  treeToFlow,
  getLayoutedElements,
  getNodeColors,
  getStatusBorderColor,
  RUN_TYPE_COLORS,
  type TraceFlowNodeData,
} from "@/lib/graph-utils";

// --- Custom node component ---

function TraceGraphNode({ data, selected }: NodeProps<Node<TraceFlowNodeData>>) {
  const isDark = (data as any).__isDark ?? true;
  const colors = getNodeColors(data.runType, isDark);
  const statusBorder = getStatusBorderColor(data.status);
  const badgeColors =
    (data.runType && RUN_TYPE_COLORS[data.runType]) ||
    "bg-slate-500/20 text-gray-600 dark:text-slate-300 border-slate-500/30";

  return (
    <div
      className="rounded-lg px-3 py-2 min-w-[180px] max-w-[260px] cursor-pointer shadow-lg transition-shadow"
      style={{
        background: colors.bg,
        border: `1.5px solid ${selected ? "#818cf8" : statusBorder || colors.border}`,
        color: colors.text,
        boxShadow: selected ? "0 0 0 2px rgba(129, 140, 248, 0.3)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />

      <div className="flex items-center gap-1.5 mb-1">
        {data.runType && (
          <span className={`text-[9px] px-1 py-0.5 rounded border font-mono leading-none ${badgeColors}`}>
            {data.runType}
          </span>
        )}
        {data.status && (
          <span
            className="w-2 h-2 rounded-full inline-block"
            style={{
              backgroundColor:
                data.status === "success" ? "#22c55e"
                  : data.status === "failure" ? "#ef4444"
                    : data.status === "degraded" ? "#eab308"
                      : "#64748b",
            }}
          />
        )}
      </div>

      <div className="text-xs font-medium truncate leading-tight" title={data.name}>
        {data.name}
      </div>

      {data.durationMs != null && (
        <div className="text-[10px] opacity-70 mt-0.5">{formatDuration(data.durationMs)}</div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { traceGraphNode: TraceGraphNode };

// --- Floating preview that tracks the node position ---

const PREVIEW_W = 300;
const PREVIEW_H_ESTIMATE = 280;
const GAP = 12;

function FloatingNodePreview({
  nodeId,
  data,
  containerRef,
  onClose,
}: {
  nodeId: string;
  data: TraceFlowNodeData;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onClose: () => void;
}) {
  const { getNode } = useReactFlow();
  const { x: vx, y: vy, zoom } = useViewport();

  const node = getNode(nodeId);
  if (!node) return null;

  const nodeW = node.measured?.width ?? 220;
  const nodeH = node.measured?.height ?? 70;
  const cW = containerRef.current?.clientWidth ?? 1000;
  const cH = containerRef.current?.clientHeight ?? 600;

  // Default: right of node, vertically centered
  let left = (node.position.x + nodeW) * zoom + vx + GAP;
  let top = node.position.y * zoom + vy;

  // Flip to left side if overflowing right
  if (left + PREVIEW_W > cW - 8) {
    left = node.position.x * zoom + vx - PREVIEW_W - GAP;
  }
  // Clamp vertical
  if (top + PREVIEW_H_ESTIMATE > cH - 8) {
    top = cH - PREVIEW_H_ESTIMATE - 8;
  }
  if (top < 8) top = 8;
  if (left < 8) left = 8;

  const badgeColors =
    (data.runType && RUN_TYPE_COLORS[data.runType]) ||
    "bg-slate-500/20 text-gray-600 dark:text-slate-300 border-slate-500/30";

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

        {/* Info rows */}
        <div className="space-y-2 mb-3">
          <div className="flex items-center justify-between">
            <span className="text-gray-500 dark:text-slate-400">Status</span>
            <StatusBadge status={data.status} />
          </div>
          {data.durationMs != null && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Duration</span>
              <span className="text-gray-900 dark:text-white font-mono text-xs">{formatDuration(data.durationMs)}</span>
            </div>
          )}
          {data.startTime && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Started</span>
              <span className="text-gray-600 dark:text-slate-300 text-xs">{new Date(data.startTime).toLocaleString()}</span>
            </div>
          )}
          {data.endTime && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Ended</span>
              <span className="text-gray-600 dark:text-slate-300 text-xs">{new Date(data.endTime).toLocaleString()}</span>
            </div>
          )}
          {data.childCount > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-slate-400">Child runs</span>
              <span className="text-gray-600 dark:text-slate-300 text-xs font-mono">{data.childCount}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-gray-500 dark:text-slate-400">Trace ID</span>
            <span className="text-gray-400 dark:text-slate-500 text-[10px] font-mono truncate ml-2 max-w-[140px]" title={data.traceId}>
              {data.traceId}
            </span>
          </div>
        </div>

        {/* Error */}
        {data.errorMessage && (
          <div className="mb-3 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-300 line-clamp-3">
            {data.errorMessage}
          </div>
        )}

        {/* Link */}
        <Link
          href={`/traces/${data.traceId}`}
          className="block w-full text-center px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded transition-colors"
        >
          View Details &rarr;
        </Link>
      </div>
    </div>
  );
}

// --- Main TraceGraph component ---

interface TraceGraphProps {
  trace: TraceDetail;
  childNodes: TraceTreeNode[];
}

const FIT_VIEW_OPTIONS = { padding: 0.2 };
const PRO_OPTIONS = { hideAttribution: true };

export default function TraceGraph({ trace, childNodes }: TraceGraphProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeData, setSelectedNodeData] = useState<TraceFlowNodeData | null>(null);

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

  const rootNode = useMemo<TraceTreeNode>(
    () => ({
      id: trace.id,
      name: trace.name,
      run_type: trace.run_type,
      status: trace.status,
      duration_ms: trace.duration_ms,
      start_time: trace.start_time,
      end_time: trace.end_time,
      error_message: trace.error_message,
      children: childNodes,
    }),
    [trace, childNodes]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<TraceFlowNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    const { nodes: rawNodes, edges: rawEdges } = treeToFlow(rootNode, isDarkRef.current);
    let cancelled = false;
    getLayoutedElements(rawNodes, rawEdges, "TB").then((layouted) => {
      if (!cancelled) { setNodes(layouted.nodes); setEdges(layouted.edges); }
    });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootNode]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedNodeData(node.data as TraceFlowNodeData);
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
          : "w-full h-[500px] rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-950 relative"
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
            const rt = (node.data as TraceFlowNodeData)?.runType;
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
          <FloatingNodePreview
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
