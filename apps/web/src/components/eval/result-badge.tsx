import type { ReactNode } from "react";

/**
 * The pass/fail/degraded/error badge for an eval result, shared by the results
 * table and the row modal so the labels, colors, and tooltips stay in sync.
 *
 * A degraded/errored row did not run against a representative target path, so it
 * is not graded and is excluded from the run's pass rate (it lands in the DLQ).
 */
export function ExecutionResultBadge({
  executionStatus,
  pass,
}: {
  executionStatus?: string;
  pass: boolean;
}): ReactNode {
  if (executionStatus === "degraded") {
    return (
      <span
        className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
        title="Ran against degraded (keyword-only) retrieval; not graded and excluded from the pass rate"
      >
        DEGRADED
      </span>
    );
  }
  if (executionStatus === "error") {
    return (
      <span
        className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400"
        title="Failed to run after retries; not graded and excluded from the pass rate"
      >
        ERROR
      </span>
    );
  }
  return pass ? (
    <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
      PASS
    </span>
  ) : (
    <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
      FAIL
    </span>
  );
}

/**
 * Sort rank for the "Result" column so dead-letter rows cluster distinctly from
 * quality failures: error (0) < degraded (1) < fail (2) < pass (3).
 */
export function executionResultRank(executionStatus: string | undefined, pass: boolean): number {
  if (executionStatus === "error") return 0;
  if (executionStatus === "degraded") return 1;
  return pass ? 3 : 2;
}
