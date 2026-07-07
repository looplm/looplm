"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { EvalResultSummary, EvalRunDetail } from "@/lib/api";

type Filter = "all" | "passed" | "failed";

/**
 * Owns all results-view filter state (status, test id, failure pattern, root
 * cause) and derives the chained filtered result lists plus the recomputed
 * stats. Operates over the grader-toggle-recomputed results.
 */
export function useEvalFilters(run: EvalRunDetail | null, computedResults: EvalResultSummary[]) {
  const searchParams = useSearchParams();

  const [filter, setFilter] = useState<Filter>("all");
  const [patternFilter, setPatternFilter] = useState<string[]>([]);
  const [patternMode, setPatternMode] = useState<"include" | "exclude">("include");
  const [rootCauseFilter, setRootCauseFilter] = useState<string[]>([]);
  const [testIdFilter, setTestIdFilter] = useState<string | null>(searchParams.get("test_id"));

  const testIdFiltered = useMemo(() => {
    if (!testIdFilter) return computedResults;
    const q = testIdFilter.toLowerCase();
    return computedResults.filter((r) => r.test_id.toLowerCase().includes(q));
  }, [computedResults, testIdFilter]);

  const patternFiltered = useMemo(() => {
    if (patternFilter.length === 0) return testIdFiltered;
    const set = new Set(patternFilter);
    if (patternMode === "include") {
      // Keep only failed results whose pattern matches.
      return testIdFiltered.filter((r) => r.failure_pattern && set.has(r.failure_pattern));
    }
    // Exclude: drop failed results whose pattern matches; passed tests stay.
    return testIdFiltered.filter((r) => !r.failure_pattern || !set.has(r.failure_pattern));
  }, [testIdFiltered, patternFilter, patternMode]);

  const rootCauseFiltered = useMemo(() => {
    if (rootCauseFilter.length === 0) return patternFiltered;
    const set = new Set(rootCauseFilter);
    // Keep only failed results whose root cause matches (mirrors pattern include mode).
    return patternFiltered.filter((r) => !r.pass && r.root_cause && set.has(r.root_cause));
  }, [patternFiltered, rootCauseFilter]);

  const filteredResults = useMemo(() => {
    if (filter === "all") return rootCauseFiltered;
    // "failed" means a graded quality failure — degraded/errored (non-ok) rows are
    // dead-letter, not failures, and are surfaced via their own badges under "all".
    return rootCauseFiltered.filter((r) =>
      filter === "passed" ? r.pass : !r.pass && (r.execution_status ?? "ok") === "ok"
    );
  }, [rootCauseFiltered, filter]);

  const computedStats = useMemo(() => {
    // Mirror the backend: degraded/errored rows did not run representatively, so they
    // are excluded from the headline pass rate (they persist as DLQ rows).
    const representative = rootCauseFiltered.filter((r) => (r.execution_status ?? "ok") === "ok");
    const total = representative.length;
    const passed = representative.filter((r) => r.pass).length;
    const failed = total - passed;
    return { total, passed, failed, passRate: total > 0 ? passed / total : 0 };
  }, [rootCauseFiltered]);

  const subsetFilterActive = patternFilter.length > 0 || rootCauseFilter.length > 0 || !!testIdFilter;

  const visibleFailingTestIds = useMemo(
    // Quality failures only — degraded/errored rows are retried via the DLQ, not here.
    () => rootCauseFiltered
      .filter((r) => !r.pass && (r.execution_status ?? "ok") === "ok")
      .map((r) => r.test_id),
    [rootCauseFiltered],
  );

  const failurePatternSummary = useMemo(() => {
    const fromRun = run?.metadata?.failure_pattern_summary;
    if (fromRun && typeof fromRun === "object") {
      return fromRun as Record<string, number>;
    }
    return null;
  }, [run]);

  const rootCauseSummary = useMemo(() => {
    const fromRun = run?.metadata?.root_cause_summary;
    if (fromRun && typeof fromRun === "object") {
      return fromRun as Record<string, number>;
    }
    return null;
  }, [run]);

  return {
    filter,
    setFilter,
    patternFilter,
    setPatternFilter,
    patternMode,
    setPatternMode,
    rootCauseFilter,
    setRootCauseFilter,
    testIdFilter,
    setTestIdFilter,
    filteredResults,
    computedStats,
    rootCauseFiltered,
    subsetFilterActive,
    visibleFailingTestIds,
    failurePatternSummary,
    rootCauseSummary,
  };
}

export type { Filter };
