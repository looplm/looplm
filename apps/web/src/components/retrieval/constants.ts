import type { RetrievalCaseMetrics, RetrievalRunMetrics, RetrievalTargets } from "@/lib/api";

export function pct(x: number | null | undefined): string {
  return x == null ? "-" : `${Math.round(x * 100)}%`;
}

export function dec(x: number | null | undefined): string {
  return x == null ? "-" : x.toFixed(2);
}

// Plain-language explanations shown on the info icons (kept simple, no jargon).
export const EXPLAIN = {
  recall:
    "Of all the documents that should have been found, this is the share that showed up in the top results. Higher is better.",
  ndcg:
    "Checks whether the most useful documents are ranked near the top, not just present somewhere. 100% means the best ones sit at the very top.",
  mrr:
    "Looks at how high the first correct document appears. 1.00 means it was always the very first result, 0.50 means usually second, and so on.",
  hit:
    "The share of questions where at least one correct document appeared in the top results. It does not care how many were found, only that one was there.",
  precision:
    "Of the documents that were returned, this is the share that were actually relevant. Higher means less noise in the results.",
  recallCurve:
    "How many of the correct documents appear as you widen the window from the top 1 result out to the deepest cutoff shown. The bars normally rise as k grows.",
  expected: "How many documents this question was expected to find (the ground truth).",
  retrieved: "How many documents the search actually returned for this question.",
  caseRecall: "The share of the expected documents that were found for this single question.",
  firstHit: "The position of the first correct document in the results. Lower is better. A dash means none were found.",
  targets: "Set the score you want each metric to reach. Cards turn green when they hit the goal, amber when close, and red when below.",
  bpref:
    "A recall-style score that ignores chunks nobody has judged yet, so it stays fair when only part of the pool is labeled. Best used while judging is still incomplete.",
  cndcg:
    "Like nDCG, but it only counts chunks that have actually been judged — so unlabeled chunks don't distort the ranking score during incomplete judging.",
  method:
    "Which retrieval method produced these numbers. The Overall view scores a single ranking; use By stage to compare each retrieval method (sparse, dense, RRF, reranked) side by side.",
};

export type Accent = "indigo" | "violet" | "sky" | "emerald" | "amber";

export const ACCENT: Record<Accent, { text: string; bar: string }> = {
  indigo: { text: "text-indigo-600 dark:text-indigo-400", bar: "bg-indigo-500" },
  violet: { text: "text-violet-600 dark:text-violet-400", bar: "bg-violet-500" },
  sky: { text: "text-sky-600 dark:text-sky-400", bar: "bg-sky-500" },
  emerald: { text: "text-emerald-600 dark:text-emerald-400", bar: "bg-emerald-500" },
  amber: { text: "text-amber-600 dark:text-amber-400", bar: "bg-amber-500" },
};

export type Status = "good" | "warn" | "bad" | "none";

export const STATUS: Record<Exclude<Status, "none">, { bar: string; text: string }> = {
  good: { bar: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  warn: { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  bad: { bar: "bg-red-500", text: "text-red-600 dark:text-red-400" },
};

export function statusOf(value: number | null | undefined, target: number | null | undefined): Status {
  if (value == null || target == null || target <= 0) return "none";
  const r = value / target;
  return r >= 1 ? "good" : r >= 0.85 ? "warn" : "bad";
}

// One descriptor per metric, to DRY the cards and the targets editor.
export type MetricKind = "pct" | "dec";
export interface MetricDef {
  key: keyof RetrievalTargets;
  accent: Accent;
  label: (k: number) => string;
  hint: string;
  info: string;
  kind: MetricKind;
  value: (m: RetrievalRunMetrics, lk: string) => number | null | undefined;
}

export const METRICS: MetricDef[] = [
  { key: "recall", accent: "indigo", label: (k) => `Recall@${k}`, hint: "docs found", info: EXPLAIN.recall, kind: "pct", value: (m, lk) => m.recall_at_k[lk] },
  { key: "ndcg", accent: "violet", label: (k) => `nDCG@${k}`, hint: "ranking quality", info: EXPLAIN.ndcg, kind: "pct", value: (m, lk) => m.ndcg_at_k[lk] },
  { key: "mrr", accent: "sky", label: () => "MRR", hint: "first hit rank", info: EXPLAIN.mrr, kind: "dec", value: (m) => m.mrr },
  { key: "hit_rate", accent: "emerald", label: (k) => `Hit-rate@${k}`, hint: "≥1 relevant", info: EXPLAIN.hit, kind: "pct", value: (m, lk) => m.hit_rate_at_k[lk] },
  { key: "precision", accent: "amber", label: (k) => `Precision@${k}`, hint: "of retrieved", info: EXPLAIN.precision, kind: "pct", value: (m, lk) => m.precision_at_k[lk] },
];

export const fmt = (kind: MetricKind, v: number | null | undefined) => (kind === "pct" ? pct(v) : dec(v));

// Which retriever the Overall block reflects. Real pipeline stages (matching the By-stage table)
// plus "best" — the live index's best-available ranking. Default selection is "agentic".
export const RETRIEVERS: { value: string; label: string }[] = [
  { value: "keyword", label: "Sparse" },
  { value: "vector", label: "Dense" },
  { value: "hybrid", label: "RRF" },
  { value: "semantic", label: "Reranked" },
  { value: "agentic", label: "Agentic" },
  { value: "best", label: "Best available" },
];

export const DEFAULT_RETRIEVER = "agentic";

// Per-k metrics selectable for the recall curve + per-case table. Each maps to the aggregate and
// per-case @k dicts and its target threshold, so one selector re-points both the chart and the
// table. (precision/hit-rate are only stored per case on runs computed after they were added.)
export interface PerKMetric {
  key: string;
  label: string;
  agg: (m: RetrievalRunMetrics) => Record<string, number>;
  perCase: (c: RetrievalCaseMetrics) => Record<string, number>;
  target: (t: RetrievalTargets) => number | null | undefined;
}

export const PERK_METRICS: PerKMetric[] = [
  { key: "recall", label: "Recall", agg: (m) => m.recall_at_k, perCase: (c) => c.recall_at_k, target: (t) => t.recall },
  { key: "precision", label: "Precision", agg: (m) => m.precision_at_k, perCase: (c) => c.precision_at_k ?? {}, target: (t) => t.precision },
  { key: "ndcg", label: "nDCG", agg: (m) => m.ndcg_at_k, perCase: (c) => c.ndcg_at_k, target: (t) => t.ndcg },
  { key: "hit_rate", label: "Hit-rate", agg: (m) => m.hit_rate_at_k, perCase: (c) => c.hit_rate_at_k ?? {}, target: (t) => t.hit_rate },
];

export const RETRIEVER_NOTES: Record<string, string> = {
  keyword: "keyword / BM25 lexical search only.",
  vector: "dense vector (embedding) similarity only.",
  hybrid: "reciprocal-rank fusion (RRF) of sparse + dense.",
  semantic: "the semantic reranker's final ranking.",
  agentic: "the agentic retrieval path (multi-query planning).",
  best: "your live index's best-available ranking. It prefers the semantic reranker, falling back to hybrid (RRF), vector, then keyword.",
};
