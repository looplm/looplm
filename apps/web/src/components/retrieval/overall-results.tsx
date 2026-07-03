"use client";

import { useState } from "react";
import { type RetrievalRunMetrics, type RetrievalTargets } from "@/lib/api";
import { EXPLAIN, METRICS, PERK_METRICS, type MetricDef } from "@/components/retrieval/constants";
import { Info, MetricCard } from "@/components/retrieval/metric-card";
import { RecallCurve } from "@/components/retrieval/recall-curve";
import { RetrieverSelector } from "@/components/retrieval/retriever-selector";
import { PerCaseResults, ReliabilityBanner, SliceBreakdown } from "@/components/retrieval/retrieval-table";

// The "Overall" retrieval-quality result: the single best-available ranking scored against the
// gold, as metric cards + incomplete-judging cross-checks + slice breakdown + recall curve and a
// per-case table. Presentational; the parent owns fetching and the @k selection (`activeK`).
export function OverallResults({
  overall,
  targets,
  activeK,
  source,
  retrieverLabel,
  retrieverNote,
  retriever,
  goldSource,
}: {
  overall: RetrievalRunMetrics;
  targets: RetrievalTargets | null;
  activeK: number;
  source: "urls" | "labels";
  // The selected retriever's label + one-line description (labels path), shown in the method note.
  retrieverLabel?: string;
  retrieverNote?: string;
  // The selected retriever value + gold source — passed to the per-case diagnosis (labels path).
  retriever?: string;
  goldSource?: "human" | "ai" | "both";
}) {
  const lk = String(activeK);
  const cardValue = (m: MetricDef): number | null | undefined => m.value(overall, lk);

  // Which per-k metric the curve + per-case table show (default recall).
  const [metricKey, setMetricKey] = useState("recall");
  const metric = PERK_METRICS.find((m) => m.key === metricKey) ?? PERK_METRICS[0];
  const metricTarget = targets ? metric.target(targets) ?? null : null;

  return (
    <>
      <div className="text-xs text-gray-400 dark:text-slate-500 mb-3">
        {overall.evaluated_cases} of {overall.total_cases} cases have{" "}
        {source === "labels" ? "relevance labels" : "ground-truth URLs"}
      </div>

      {/* Which retrieval method these numbers reflect — the Overall view collapses to a single
          ranking; the by-stage comparison below scores each method separately. */}
      <div className="flex items-start gap-2 rounded-lg bg-gray-50 dark:bg-slate-800/40 border border-gray-100 dark:border-slate-800 px-3 py-2 mb-3 text-xs text-gray-500 dark:text-slate-400">
        <Info text={EXPLAIN.method} />
        {source === "labels" ? (
          <span>
            <span className="font-medium text-gray-600 dark:text-slate-300">
              {retrieverLabel ?? "Method"}:
            </span>{" "}
            {retrieverNote ?? "the live index's best-available ranking."} Pick a retriever above; see
            the By stage comparison below to compare them side by side.
          </span>
        ) : (
          <span>
            <span className="font-medium text-gray-600 dark:text-slate-300">Method:</span>{" "}
            your app&apos;s final logged retrieval order, which is post-rerank. A
            before-vs-after-rerank split is not available on this path.
          </span>
        )}
      </div>

      <ReliabilityBanner count={overall.evaluated_cases} source={source} />

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        {METRICS.map((m) => (
          <MetricCard
            key={m.key}
            label={m.label(activeK)}
            value={cardValue(m)}
            target={targets ? targets[m.key] : null}
            kind={m.kind}
            hint={m.hint}
            accent={m.accent}
            info={m.info}
          />
        ))}
      </div>

      {/* Incomplete-judgment-safe metrics: only on the human-label path, where the pool is partly
          judged. Shown without targets — they're a robustness cross-check. */}
      {source === "labels" && overall.bpref != null && (
        <div className="mb-4">
          <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-2">
            Robust to incomplete judging
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard
              label="bpref"
              value={overall.bpref}
              target={null}
              kind="pct"
              hint="ignores unjudged"
              accent="violet"
              info={EXPLAIN.bpref}
            />
            <MetricCard
              label={`cNDCG@${activeK}`}
              value={overall.condensed_ndcg_at_k?.[lk]}
              target={null}
              kind="pct"
              hint="judged-only ranking"
              accent="violet"
              info={EXPLAIN.cndcg}
            />
          </div>
        </div>
      )}

      {overall.slices && overall.slices.length > 0 && (
        <SliceBreakdown slices={overall.slices} largestK={activeK} />
      )}

      <div className="flex items-center justify-end mb-2">
        <RetrieverSelector
          label="Metric"
          title="Which metric the chart and per-case table show"
          options={PERK_METRICS.map((m) => ({ value: m.key, label: m.label }))}
          value={metricKey}
          onChange={setMetricKey}
        />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
        <RecallCurve
          recall={metric.agg(overall)}
          ks={overall.ks}
          target={metricTarget}
          label={metric.label}
          info={metric.info}
        />
        <PerCaseResults
          cases={overall.cases}
          largestK={activeK}
          lk={lk}
          metricLabel={metric.label}
          perCase={metric.perCase}
          metricTarget={metricTarget}
          metricInfo={metric.info}
          ratio={metric.ratio ? (c) => metric.ratio!(c, lk, activeK) : null}
          ratioHeader={metric.ratioHeader}
          ratioInfo={metric.ratioInfo}
          diagnose={source === "labels" && retriever ? { retriever, goldSource: goldSource ?? "human" } : null}
        />
      </div>
    </>
  );
}
