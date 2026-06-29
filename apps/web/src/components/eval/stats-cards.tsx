"use client";

import type { EvalRunDetail } from "@/lib/api";
import { StatCard } from "@/components/eval-shared";

interface StatsCardsProps {
  run: EvalRunDetail;
  computedStats: { total: number; passed: number; failed: number; passRate: number };
  disabledGraders: Set<string>;
}

export function StatsCards({ run, computedStats, disabledGraders }: StatsCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard label="Total" value={computedStats.total} />
      <StatCard label="Passed" value={computedStats.passed} accent={computedStats.passed > 0 ? "green" : undefined} />
      <StatCard label="Failed" value={computedStats.failed} accent={computedStats.failed > 0 ? "red" : undefined} />
      <StatCard
        label="Pass Rate"
        value={`${(computedStats.passRate * 100).toFixed(1)}%`}
        sub={disabledGraders.size > 0 ? "recomputed" : undefined}
        accent={computedStats.passRate === 1 ? "green" : computedStats.passRate === 0 && computedStats.total > 0 ? "red" : "amber"}
      />
      {typeof run.metadata?.filter_mode === "string" && run.metadata.filter_mode !== "as_configured" && (
        <StatCard
          label="Filter Mode"
          value={run.metadata.filter_mode === "no_filters" ? "No Filters" : String(run.metadata.filter_mode)}
          accent="amber"
        />
      )}
      {typeof run.metadata?.avg_turns_to_pass === "number" && (
        <StatCard
          label="Avg Turns to Pass"
          value={`${(run.metadata.avg_turns_to_pass as number).toFixed(1)}`}
          sub={`${run.metadata.multi_turn_test_count ?? 0} multi-turn tests`}
          accent="amber"
        />
      )}
    </div>
  );
}
