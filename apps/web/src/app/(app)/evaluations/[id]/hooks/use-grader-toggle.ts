"use client";

import { useCallback, useMemo, useState } from "react";
import type { EvalRunDetail } from "@/lib/api";
import { recomputePass } from "../eval-utils";

/**
 * Tracks which graders are toggled off and recomputes per-result pass values
 * accordingly. Returns the disabled set, a toggle callback, and the recomputed
 * results list.
 */
export function useGraderToggle(run: EvalRunDetail | null) {
  const [disabledGraders, setDisabledGraders] = useState<Set<string>>(new Set());

  const toggleGrader = useCallback((name: string) => {
    setDisabledGraders((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const computedResults = useMemo(() => {
    if (!run) return [];
    if (disabledGraders.size === 0) return run.results;
    return run.results.map((r) => ({
      ...r,
      pass: recomputePass(r, disabledGraders),
    }));
  }, [run, disabledGraders]);

  return { disabledGraders, toggleGrader, computedResults };
}
