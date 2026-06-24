/**
 * Retrieval section types — the aggregate retrieval pipeline flow chart.
 *
 * Hand-written (not derived from schema.gen.ts) so the Retrieval page does not depend on
 * an OpenAPI regeneration. Mirrors app/schemas/retrieval.py.
 */

export interface RetrievalMetric {
  label: string;
  value: string;
  hint?: string | null;
  tone?: "good" | "warn" | "bad" | "muted" | null;
}

export interface RetrievalPipelineNode {
  id: string;
  label: string;
  sublabel?: string | null;
  group?: string | null;
  provider?: string | null;
  status: "active" | "no_data";
  description?: string | null;
  metrics: RetrievalMetric[];
}

export interface RetrievalPipelineEdge {
  source: string;
  target: string;
  label?: string | null;
  kind: "main" | "fallback";
}

export interface RetrievalPipelineResponse {
  available: boolean;
  traces_analyzed: number;
  rag_traces: number;
  nodes: RetrievalPipelineNode[];
  edges: RetrievalPipelineEdge[];
  span_names: Record<string, string>;
}
