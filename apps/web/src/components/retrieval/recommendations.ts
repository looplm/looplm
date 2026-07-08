import type {
  ByStageMetricsResponse,
  RetrievalRunMetrics,
  RetrievalTargets,
  StageMetrics,
} from "@/lib/api";
import { dec, pct, statusOf } from "./constants";

// Turns the already-computed retrieval metrics into "here is what to fix" guidance. Pure and
// deterministic — no I/O, no LLM. The relationships between the metrics and the pipeline are
// mathematical (recall is a ceiling set upstream, reranking only reorders, precision@k is capped by
// pool size), so rules are more reliable here than generated prose. When By-stage data is present
// (labels path) the rules attribute a problem to a specific pipeline step; otherwise they fall back
// to critiquing the selected retriever against its targets.

export type Severity = "high" | "medium" | "low" | "good";
// Which pipeline step the fix belongs to. Ordered as the funnel flows.
export type Stage = "index" | "retrieval" | "rerank" | "cutoff" | "labels";
export type ActionKind = "diagnose" | "labeling" | "byStage";

export interface Recommendation {
  id: string;
  severity: Severity;
  stage: Stage;
  title: string;
  detail: string;
  // Optional in-page action the panel wires up (scroll/link).
  action?: { label: string; kind: ActionKind };
  // The metrics this finding is derived from, shown as small tags so the "why" is legible.
  basis: string[];
}

export interface RecommendationInput {
  overall: RetrievalRunMetrics | null; // the selected retriever
  byStage: ByStageMetricsResponse | null; // null on the URLs path or before By-stage loads
  targets: RetrievalTargets | null;
  k: number;
  source: "urls" | "labels";
}

const SEV_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2, good: 3 };
const STAGE_ORDER: Record<Stage, number> = {
  index: 0,
  retrieval: 1,
  rerank: 2,
  cutoff: 3,
  labels: 4,
};

const STAGE_LABEL: Record<Stage, string> = {
  index: "Indexing",
  retrieval: "Retrieval",
  rerank: "Reranking",
  cutoff: "Cutoff",
  labels: "Labeling",
};

export function stageLabel(s: Stage): string {
  return STAGE_LABEL[s];
}

const num = (v: number | null | undefined): number | null =>
  v == null || Number.isNaN(v) ? null : v;

function median(nums: (number | null | undefined)[]): number | null {
  const xs = nums.filter((n): n is number => n != null && !Number.isNaN(n)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
}

// A metric "meets" its target when it renders as green on the cards (same rounding as statusOf).
const meets = (value: number | null, target: number | null | undefined): boolean =>
  statusOf(value, target ?? null) === "good";

export function buildRecommendations(input: RecommendationInput): Recommendation[] {
  const { overall, byStage, targets, k, source } = input;
  if (!overall || !overall.available || !targets) return [];

  const lk = String(k);
  const recall = num(overall.recall_at_k[lk]);
  const prec = num(overall.precision_at_k[lk]);
  const ndcg = num(overall.ndcg_at_k[lk]);
  const mrr = num(overall.mrr);
  const hit = num(overall.hit_rate_at_k[lk]);
  const bpref = num(overall.bpref);
  const hitHigh = hit != null && hit >= 0.9;
  const recallOk = meets(recall, targets.recall) || hitHigh;

  const recs: Recommendation[] = [];

  // --- Ranking: the right chunks are retrieved but ranked below the cutoff. -----------------
  const rankingWeak =
    (ndcg != null && !meets(ndcg, targets.ndcg)) || (mrr != null && !meets(mrr, targets.mrr));
  if (recallOk && rankingWeak) {
    recs.push({
      id: "found-but-buried",
      severity: "high",
      stage: "rerank",
      title: "Relevant chunks are found but ranked too low",
      detail:
        `Recall@${k} is ${pct(recall)} and hit-rate ${pct(hit)}, but nDCG@${k} is ${pct(ndcg)} ` +
        `and MRR ${dec(mrr)}. The right chunks are in the pool — they're just below the cutoff. ` +
        `This is a ranking problem: the lever is the semantic reranker and where you cut, not ` +
        `indexing or retrieval breadth.`,
      action: { label: "Compare by stage", kind: "byStage" },
      basis: [`Recall@${k}`, `Hit-rate@${k}`, `nDCG@${k}`, "MRR"],
    });
  }

  // --- Coverage: some relevant chunks are never retrieved (a ceiling reranking can't lift). ---
  if (recall != null && !meets(recall, targets.recall) && !hitHigh) {
    recs.push({
      id: "recall-ceiling",
      severity: "high",
      stage: "index",
      title: "Not all relevant chunks are being retrieved",
      detail:
        `Recall@${k} is ${pct(recall)}, below the ${pct(targets.recall)} target` +
        (hit != null ? `, and hit-rate is ${pct(hit)}` : "") +
        `. Reranking can't fix this — the missing chunks were never pulled. The fix is upstream: ` +
        `indexing (chunking, embeddings, coverage) or retrieval breadth (query expansion, hybrid). ` +
        `Use per-case Diagnose to see whether misses are not-in-index / missing-embedding / ` +
        `bad-chunk (indexer) versus buried (ranking).`,
      action: { label: "Diagnose worst cases", kind: "diagnose" },
      basis: [`Recall@${k}`, `Hit-rate@${k}`],
    });
  }

  // --- Cutoff: precision@k is capped by how few chunks are relevant per query. ----------------
  const medRel = median(overall.cases?.map((c) => c.relevant_count ?? c.expected_count));
  if (prec != null && !meets(prec, targets.precision) && recallOk && medRel != null && medRel / k < 0.5) {
    const cap = medRel / k;
    recs.push({
      id: "precision-cutoff-artifact",
      severity: "medium",
      stage: "cutoff",
      title: `Precision@${k} is capped by how few chunks are relevant`,
      detail:
        `Most queries have only ~${Math.round(medRel)} relevant chunk${medRel < 1.5 ? "" : "s"}, so ` +
        `precision@${k} can't exceed about ${pct(cap)} however good the ranking is. Read precision ` +
        `at the depth you actually feed the model${k > 10 ? " (try @10 or lower)" : ""}. With recall ` +
        `${pct(recall)} and hit-rate ${pct(hit)} healthy, low precision here is the cutoff depth, ` +
        `not retrieval.`,
      basis: [`Precision@${k}`, `Recall@${k}`],
    });
  }

  // --- Cross-stage rules (need By-stage data). ------------------------------------------------
  if (byStage?.available) {
    const stage = (v: string): StageMetrics | null =>
      byStage.stages.find((s) => s.stage === v) ?? null;
    const recallOf = (v: string): number | null => num(stage(v)?.recall_at_k?.[lk]);
    const ndcgOf = (v: string): number | null => num(stage(v)?.ndcg_at_k?.[lk]);

    // Is the semantic reranker improving the ranking over plain RRF?
    const semNdcg = ndcgOf("semantic");
    const hybNdcg = ndcgOf("hybrid");
    if (semNdcg != null && hybNdcg != null) {
      const lift = semNdcg - hybNdcg;
      if (lift <= 0.01) {
        recs.push({
          id: "reranker-not-helping",
          severity: "medium",
          stage: "rerank",
          title: "The reranker isn't improving on RRF",
          detail:
            `The semantic reranker's nDCG@${k} (${pct(semNdcg)}) is no better than RRF ` +
            `(${pct(hybNdcg)}). It isn't reordering usefully — check that it's enabled, that ` +
            `rerankerScore is applied, and where the score cutoff sits. The threshold sweep under ` +
            `By stage shows the precision/recall trade at each cutoff.`,
          action: { label: "Compare by stage", kind: "byStage" },
          basis: [`nDCG@${k} (Reranked)`, `nDCG@${k} (RRF)`],
        });
      } else if (lift >= 0.05) {
        recs.push({
          id: "reranker-earning-keep",
          severity: "good",
          stage: "rerank",
          title: "The reranker is earning its keep",
          detail:
            `The semantic reranker lifts nDCG@${k} from ${pct(hybNdcg)} (RRF) to ${pct(semNdcg)}. ` +
            `Reranking is pulling the good chunks toward the top.`,
          basis: [`nDCG@${k} (Reranked)`, `nDCG@${k} (RRF)`],
        });
      }
    }

    // Which retrieval arm carries the signal — where to invest and what to keep fresh.
    const vec = recallOf("vector");
    const kw = recallOf("keyword");
    if (vec != null && kw != null && Math.max(vec, kw) > 0 && Math.abs(vec - kw) >= 0.15) {
      const dense = vec > kw;
      recs.push({
        id: "dominant-arm",
        severity: "low",
        stage: "retrieval",
        title: dense
          ? "Dense retrieval carries most of the signal"
          : "Keyword retrieval carries most of the signal",
        detail: dense
          ? `Dense (vector) recall@${k} is ${pct(vec)} versus sparse (keyword) ${pct(kw)}. Most ` +
            `relevant chunks are found semantically — make sure the hybrid/agentic path weights the ` +
            `vector arm and keep embeddings fresh.`
          : `Sparse (keyword) recall@${k} is ${pct(kw)} versus dense (vector) ${pct(vec)}. Matches ` +
            `are lexical — check embedding quality/coverage and query expansion, and don't ` +
            `under-weight the keyword arm in fusion.`,
        basis: [`Recall@${k} (Dense)`, `Recall@${k} (Sparse)`],
      });
    }

    // Is the agentic (multi-query) path adding coverage over single-query retrieval?
    const ag = recallOf("agentic");
    const single = [recallOf("semantic"), recallOf("hybrid")]
      .filter((x): x is number => x != null)
      .reduce((m, x) => Math.max(m, x), Number.NEGATIVE_INFINITY);
    if (ag != null && Number.isFinite(single) && ag <= single + 0.01) {
      recs.push({
        id: "agentic-no-gain",
        severity: "low",
        stage: "retrieval",
        title: "The agentic path isn't adding coverage",
        detail:
          `Agentic (multi-query) recall@${k} is ${pct(ag)}, no better than single-query retrieval ` +
          `(${pct(single)}). Query planning isn't surfacing new chunks — review how sub-queries are ` +
          `generated and how their results are merged.`,
        basis: [`Recall@${k} (Agentic)`, `Recall@${k} (single-query)`],
      });
    }
  }

  // --- Reliability: how far to trust these numbers (labels path only). ------------------------
  if (source === "labels") {
    if (overall.evaluated_cases < 50) {
      recs.push({
        id: "few-cases",
        severity: "low",
        stage: "labels",
        title: "Results are directional — judge more cases",
        detail:
          `Only ${overall.evaluated_cases} case${overall.evaluated_cases === 1 ? "" : "s"} have ` +
          `relevance labels. Aim for 50+ before trusting these numbers. Label more candidates on ` +
          `the Labeling page.`,
        action: { label: "Open Labeling", kind: "labeling" },
        basis: ["Judged cases"],
      });
    } else if (bpref != null && recall != null && recall - bpref >= 0.15) {
      recs.push({
        id: "incomplete-judging",
        severity: "low",
        stage: "labels",
        title: "Judging is still incomplete",
        detail:
          `Recall@${k} (${pct(recall)}) and bpref (${pct(bpref)}) diverge — many retrieved chunks ` +
          `are still unjudged, so the graded scores may shift as you label more. Treat the rankings ` +
          `as provisional.`,
        action: { label: "Open Labeling", kind: "labeling" },
        basis: [`Recall@${k}`, "bpref"],
      });
    }
  }

  // --- All clear. Only when nothing actionable fired and every target is green. ----------------
  const hasActionable = recs.some((r) => r.severity === "high" || r.severity === "medium");
  const allGreen =
    meets(recall, targets.recall) &&
    meets(ndcg, targets.ndcg) &&
    meets(mrr, targets.mrr) &&
    meets(hit, targets.hit_rate) &&
    meets(prec, targets.precision);
  if (!hasActionable && allGreen) {
    recs.push({
      id: "all-targets-met",
      severity: "good",
      stage: "rerank",
      title: `All targets met at @${k}`,
      detail:
        `Every target is green at @${k}. To push further, tighten the targets or evaluate at a ` +
        `stricter cutoff.`,
      basis: [`Recall@${k}`, `nDCG@${k}`, "MRR", `Hit-rate@${k}`, `Precision@${k}`],
    });
  }

  recs.sort(
    (a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || STAGE_ORDER[a.stage] - STAGE_ORDER[b.stage],
  );
  return recs;
}
