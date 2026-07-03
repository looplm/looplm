"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type NodeProps,
  type Node,
  type Edge,
  Handle,
  Position,
} from "@xyflow/react";
import type {
  RetrievalPipelineResponse,
  RetrievalPipelineNode,
  RetrievalPipelineEdge,
  RetrievalMetric,
} from "@/lib/api";
import { getLayoutedElements } from "@/lib/graph-utils";
import EditablePipelineEdge from "@/components/editable-pipeline-edge";

// --- Node data ---

interface PipelineNodeData {
  label: string;
  sublabel?: string;
  provider?: string;
  group?: string;
  status: "active" | "no_data";
  description?: string;
  metrics: RetrievalMetric[];
  __isDark?: boolean;
  [key: string]: unknown;
}

const TONE_TEXT: Record<string, string> = {
  good: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-red-600 dark:text-red-400",
  muted: "text-gray-500 dark:text-slate-400",
};

function toneClass(tone?: string | null): string {
  return (tone && TONE_TEXT[tone]) || "text-gray-900 dark:text-white";
}

// Azure-hosted stages (hybrid cluster + reranker) get a distinct accent so it's
// visually clear they share one provider call even though they're separate stages.
function nodeAccent(data: PipelineNodeData, isDark: boolean, selected: boolean) {
  const azure = data.provider === "Azure AI Search";
  const muted = data.status === "no_data";
  let border = isDark ? "#334155" : "#cbd5e1";
  let bg = isDark ? "#0f172a" : "#ffffff";
  if (azure) {
    border = isDark ? "#3b82f6" : "#60a5fa";
    bg = isDark ? "rgba(30,58,138,0.18)" : "rgba(219,234,254,0.55)";
  }
  if (selected) border = "#818cf8";
  return { border, bg, dashed: muted };
}

function PipelineNode({ data, selected }: NodeProps<Node<PipelineNodeData>>) {
  const isDark = data.__isDark ?? true;
  const { border, bg, dashed } = nodeAccent(data, isDark, selected);
  const muted = data.status === "no_data";

  return (
    <div
      className="rounded-lg px-3 py-2.5 min-w-[210px] max-w-[260px] shadow-md cursor-pointer transition-shadow"
      style={{
        background: bg,
        border: `1.5px ${dashed ? "dashed" : "solid"} ${border}`,
        opacity: muted ? 0.7 : 1,
        boxShadow: selected ? "0 0 0 2px rgba(129,140,248,0.3)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />

      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-xs font-semibold text-gray-900 dark:text-white leading-tight">
          {data.label}
        </span>
        {data.provider && (
          <span className="text-[8px] px-1 py-0.5 rounded border border-blue-400/40 text-blue-600 dark:text-blue-300 bg-blue-500/10 font-mono leading-none whitespace-nowrap">
            {data.provider === "Azure AI Search" ? "Azure" : data.provider}
          </span>
        )}
      </div>

      {data.sublabel && (
        <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-1.5 leading-tight">
          {data.sublabel}
        </div>
      )}

      {muted && data.metrics.length === 0 ? (
        <div className="text-[10px] italic text-gray-400 dark:text-slate-500">not logged in traces</div>
      ) : (
        <div className="space-y-0.5">
          {data.metrics.slice(0, 4).map((m, i) => (
            <div key={i} className="flex items-center justify-between gap-2 text-[10px]">
              <span className="text-gray-500 dark:text-slate-400 truncate">{m.label}</span>
              <span className={`font-mono font-medium ${toneClass(m.tone)}`}>{m.value}</span>
            </div>
          ))}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 dark:!bg-slate-500 !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { pipelineNode: PipelineNode };
const edgeTypes = { editable: EditablePipelineEdge };

// --- Detail panel ---

function DetailPanel({ data, onClose }: { data: PipelineNodeData; onClose: () => void }) {
  return (
    <div className="absolute top-3 right-3 z-10 w-[300px] bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg shadow-2xl p-4 text-sm">
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0">
          <div className="font-semibold text-gray-900 dark:text-white">{data.label}</div>
          {data.provider && (
            <div className="text-[10px] text-blue-600 dark:text-blue-300">{data.provider}</div>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 dark:text-slate-500 hover:text-gray-900 dark:hover:text-white ml-2 shrink-0"
          aria-label="Close"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      {data.description && (
        <p className="text-xs text-gray-600 dark:text-slate-300 mb-3 leading-relaxed">{data.description}</p>
      )}

      {data.status === "no_data" && (
        <div className="text-[11px] mb-3 px-2 py-1.5 rounded bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-500/20">
          No signal for this stage in the analyzed traces — it&apos;s part of the pipeline but not observable yet.
        </div>
      )}

      {data.metrics.length > 0 && (
        <div className="space-y-2">
          {data.metrics.map((m, i) => (
            <div key={i}>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 dark:text-slate-400 text-xs">{m.label}</span>
                <span className={`font-mono text-xs font-medium ${toneClass(m.tone)}`}>{m.value}</span>
              </div>
              {m.hint && (
                <div className="text-[10px] text-gray-400 dark:text-slate-500 mt-0.5 leading-snug">{m.hint}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Main ---

const FIT_VIEW_OPTIONS = { padding: 0.18 };
const PRO_OPTIONS = { hideAttribution: true };

export default function RetrievalPipelineGraph({ data }: { data: RetrievalPipelineResponse }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<PipelineNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<PipelineNodeData | null>(null);

  useEffect(() => {
    const dark = isDarkRef.current;
    const rawNodes: Node<PipelineNodeData>[] = (data.nodes ?? []).map((n: RetrievalPipelineNode) => ({
      id: n.id,
      type: "pipelineNode",
      position: { x: 0, y: 0 },
      data: {
        label: n.label,
        sublabel: n.sublabel ?? undefined,
        provider: n.provider ?? undefined,
        group: n.group ?? undefined,
        status: n.status,
        description: n.description ?? undefined,
        metrics: n.metrics ?? [],
        __isDark: dark,
      },
    }));

    const rawEdges: Edge[] = (data.edges ?? []).map((e: RetrievalPipelineEdge, i: number) => {
      const fallback = e.kind === "fallback";
      return {
        id: `re-${i}-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        type: "editable",
        animated: fallback,
        data: { fallback },
        style: {
          stroke: fallback ? (dark ? "#b45309" : "#f59e0b") : dark ? "#475569" : "#cbd5e1",
          strokeWidth: 1.5,
          strokeDasharray: fallback ? "5 4" : undefined,
        },
        label: e.label ?? undefined,
        labelStyle: { fill: dark ? "#94a3b8" : "#64748b", fontSize: 10 },
        labelBgStyle: { fill: dark ? "#0f172a" : "#ffffff", fillOpacity: 0.85 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
      };
    });

    // Fallback edges (e.g. "broaden & retry") loop backward and close a cycle in the
    // otherwise-linear pipeline. Feeding them to the layout engine forces it to break the
    // cycle by reversing an arbitrary edge, which scrambles the vertical ordering. Lay out
    // on the forward edges only, then render all edges (the fallback routes over the result).
    const layoutEdges = rawEdges.filter((_, i) => (data.edges ?? [])[i]?.kind !== "fallback");

    let cancelled = false;
    getLayoutedElements(rawNodes, layoutEdges, "TB").then((layouted) => {
      if (!cancelled) {
        setNodes(layouted.nodes);
        setEdges(rawEdges);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelected(node.data as PipelineNodeData);
  }, []);
  const onPaneClick = useCallback(() => setSelected(null), []);

  return (
    <div className="w-full h-full min-h-[480px] rounded-xl overflow-hidden border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-950 relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={FIT_VIEW_OPTIONS}
        proOptions={PRO_OPTIONS}
        minZoom={0.2}
        maxZoom={1.8}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color={isDark ? "#1e293b" : "#e2e8f0"} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {selected && <DetailPanel data={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
