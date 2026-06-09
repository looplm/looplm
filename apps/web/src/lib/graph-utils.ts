/**
 * Shared utilities for graph visualization components.
 * Provides ELK layout, color mappings, and tree-to-flow converters.
 */

import type { Node, Edge } from "@xyflow/react";
import type { TraceTreeNode } from "./api";

// Lazily initialize ELK via dynamic import and persist across HMR.
// Using import() instead of require() creates a code-splitting boundary
// so Turbopack doesn't eagerly process elk.bundled.js on every rebuild.
const g = globalThis as unknown as { __elkPromise?: Promise<any> };
function getElk(): Promise<any> {
  if (!g.__elkPromise) {
    g.__elkPromise = import("elkjs/lib/elk.bundled.js").then(
      (mod) => new mod.default()
    );
  }
  return g.__elkPromise;
}

// --- Node colors per run_type (bg, border, text for React Flow nodes) ---

export const RUN_TYPE_NODE_COLORS: Record<
  string,
  { bg: string; border: string; text: { light: string; dark: string } }
> = {
  llm: { bg: "#7c3aed20", border: "#7c3aed", text: { dark: "#c4b5fd", light: "#6d28d9" } },
  tool: { bg: "#3b82f620", border: "#3b82f6", text: { dark: "#93c5fd", light: "#1d4ed8" } },
  retriever: { bg: "#22c55e20", border: "#22c55e", text: { dark: "#86efac", light: "#15803d" } },
  chain: { bg: "#eab30820", border: "#eab308", text: { dark: "#fde047", light: "#a16207" } },
  agent: { bg: "#f9731620", border: "#f97316", text: { dark: "#fdba74", light: "#c2410c" } },
};

const DEFAULT_NODE_COLORS = {
  bg: "#64748b20",
  border: "#64748b",
  text: { dark: "#cbd5e1", light: "#374151" },
};

export function getNodeColors(runType?: string, isDark = true) {
  const entry = (runType && RUN_TYPE_NODE_COLORS[runType]) || DEFAULT_NODE_COLORS;
  return { bg: entry.bg, border: entry.border, text: isDark ? entry.text.dark : entry.text.light };
}

// --- Status border colors ---

export const STATUS_BORDER_COLORS: Record<string, string> = {
  success: "#22c55e",
  failure: "#ef4444",
  degraded: "#eab308",
};

export function getStatusBorderColor(status?: string): string | undefined {
  return status ? STATUS_BORDER_COLORS[status] : undefined;
}

// --- Tailwind class-based run type colors (matching existing badge style) ---

export const RUN_TYPE_COLORS: Record<string, string> = {
  llm: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  tool: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  retriever: "bg-green-500/20 text-green-300 border-green-500/30",
  chain: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  agent: "bg-orange-500/20 text-orange-300 border-orange-500/30",
};

// --- ELK layout ---

const NODE_WIDTH = 220;
const NODE_HEIGHT = 70;

export async function getLayoutedElements<N extends Node = Node>(
  nodes: N[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB"
): Promise<{ nodes: N[]; edges: Edge[] }> {
  const elk = await getElk();

  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": direction === "TB" ? "DOWN" : "RIGHT",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.crossingMinimization.greedySwitch.type": "TWO_SIDED",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.spacing.nodeNode": "80",
      "elk.spacing.edgeNode": "40",
      "elk.layered.spacing.nodeNodeBetweenLayers": "100",
      "elk.layered.thoroughness": "20",
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: node.measured?.width ?? NODE_WIDTH,
      height: node.measured?.height ?? NODE_HEIGHT,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  };

  const layouted = await elk.layout(elkGraph);

  const positionMap = new Map<string, { x: number; y: number }>();
  for (const child of layouted.children ?? []) {
    positionMap.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }

  const layoutedNodes = nodes.map((node) => ({
    ...node,
    position: positionMap.get(node.id) ?? { x: 0, y: 0 },
  })) as N[];

  return { nodes: layoutedNodes, edges };
}

// --- Tree to React Flow conversion ---

export interface TraceFlowNodeData {
  label: string;
  name: string;
  runType?: string;
  status?: string;
  durationMs?: number;
  traceId: string;
  startTime?: string;
  endTime?: string;
  errorMessage?: string;
  childCount: number;
  [key: string]: unknown;
}

export function treeToFlow(root: TraceTreeNode, isDark = true): {
  nodes: Node<TraceFlowNodeData>[];
  edges: Edge[];
} {
  const nodes: Node<TraceFlowNodeData>[] = [];
  const edges: Edge[] = [];
  const edgeStroke = isDark ? "#475569" : "#cbd5e1";

  function walk(node: TraceTreeNode, parentId?: string) {
    const nodeId = node.id;

    nodes.push({
      id: nodeId,
      type: "traceGraphNode",
      position: { x: 0, y: 0 },
      data: {
        label: node.name || "unnamed",
        name: node.name || "unnamed",
        runType: node.run_type ?? undefined,
        status: node.status ?? undefined,
        durationMs: node.duration_ms ?? undefined,
        traceId: node.id,
        startTime: node.start_time,
        endTime: node.end_time ?? undefined,
        errorMessage: node.error_message ?? undefined,
        childCount: node.children?.length ?? 0,
        __isDark: isDark,
      },
    });

    if (parentId) {
      edges.push({
        id: `e-${parentId}-${nodeId}`,
        source: parentId,
        target: nodeId,
        type: "smoothstep",
        animated: false,
        style: { stroke: edgeStroke, strokeWidth: 1.5 },
      });
    }

    for (const child of node.children ?? []) {
      walk(child, nodeId);
    }
  }

  walk(root);
  return { nodes, edges };
}
