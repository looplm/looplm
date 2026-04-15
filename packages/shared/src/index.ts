// LoopLM shared types and utilities

export interface Trace {
  id: string;
  source: "langfuse" | "langsmith";
  sourceTraceId: string;
  outcome: "success" | "failure" | "degraded" | "pending";
  failureType?: "prompt" | "retrieval" | "tool" | "context_overflow" | "model_limitation";
  spans: Span[];
  metadata: Record<string, unknown>;
  createdAt: string;
  analyzedAt?: string;
}

export interface Span {
  id: string;
  name: string;
  type: "llm" | "tool" | "retrieval" | "chain" | "custom";
  input?: unknown;
  output?: unknown;
  startTime: string;
  endTime?: string;
  status: "ok" | "error";
  metadata?: Record<string, unknown>;
}

export interface FixSuggestion {
  id: string;
  traceId: string;
  type: "prompt_rewrite" | "tool_config" | "knowledge_base";
  title: string;
  description: string;
  diff?: string;
  impactEstimate?: {
    similarFailures: number;
    totalFailures: number;
  };
  confidence: number;
}

export interface ConnectorConfig {
  type: "langfuse" | "langsmith";
  name: string;
  credentials: Record<string, string>;
  syncIntervalMinutes: number;
}
