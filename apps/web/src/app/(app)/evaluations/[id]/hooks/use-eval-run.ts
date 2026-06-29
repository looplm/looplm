"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getEvalRun,
  getEvaluators,
  type EvalRunDetail,
  type EvaluatorItem,
} from "@/lib/api";

/**
 * Loads the eval run + evaluator metadata for a run id, and derives the
 * grader name ordering used across the results view. Returns the same values
 * the page previously computed inline.
 */
export function useEvalRun(id: string) {
  const [run, setRun] = useState<EvalRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluatorMap, setEvaluatorMap] = useState<Record<string, EvaluatorItem>>({});

  useEffect(() => {
    setLoading(true);
    Promise.all([getEvalRun(id), getEvaluators()])
      .then(([evalRun, evalResponse]) => {
        setRun(evalRun);
        const map: Record<string, EvaluatorItem> = {};
        for (const ev of evalResponse.data) {
          map[ev.name] = ev;
        }
        setEvaluatorMap(map);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const allGraderNames = useMemo(() => {
    if (!run) return [];
    const entries = Object.entries(run.grader_summary);
    const relevanceOrder: Record<string, number> = { core: 0, important: 1, minor: 2 };
    entries.sort(([nameA], [nameB]) => {
      const metaA = evaluatorMap[nameA];
      const metaB = evaluatorMap[nameB];
      const apA = metaA?.affects_pass ? 0 : 1;
      const apB = metaB?.affects_pass ? 0 : 1;
      if (apA !== apB) return apA - apB;
      // Then by source (custom first, then ragas, then others)
      const sourceOrder: Record<string, number> = { custom: 0, ragas: 1, langfuse: 2, discovered: 3 };
      const srcA = sourceOrder[metaA?.source ?? "custom"] ?? 99;
      const srcB = sourceOrder[metaB?.source ?? "custom"] ?? 99;
      if (srcA !== srcB) return srcA - srcB;
      const relA = relevanceOrder[metaA?.relevance ?? "minor"] ?? 2;
      const relB = relevanceOrder[metaB?.relevance ?? "minor"] ?? 2;
      if (relA !== relB) return relA - relB;
      return nameA.localeCompare(nameB);
    });
    return entries.map(([name]) => name);
  }, [run, evaluatorMap]);

  return { run, setRun, loading, evaluatorMap, allGraderNames };
}
