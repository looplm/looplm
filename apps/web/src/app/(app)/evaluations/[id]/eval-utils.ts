import type { EvalGraderResult, EvaluatorItem, GraderResultSummary } from "@/lib/api";

type ResultLike = {
  pass: boolean;
  graders: Record<string, { pass: boolean; skipped?: boolean | null }>;
};

export function recomputePass(result: ResultLike, disabledGraders: Set<string>): boolean {
  if (!result.pass) {
    const graders = result.graders || {};
    const allGradersPassing = Object.entries(graders).every(
      ([name, g]) => disabledGraders.has(name) || g.skipped || g.pass
    );
    return allGradersPassing;
  }
  return true;
}

/** Split text into logical segments: paragraphs, numbered items, sentences */
export function splitSegments(text: string): { text: string; blockBreak: boolean }[] {
  // First split on double newlines (paragraphs) and numbered list items
  const blocks = text.split(/\n{2,}|(?=\n?\d+\.\s)/);
  const segments: { text: string; blockBreak: boolean }[] = [];

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;
    // Split block into sentences, but keep numbered items intact
    const sentences = trimmed
      .split(/(?<=[.!?])\s+(?![.!?])/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    sentences.forEach((s, i) => {
      segments.push({ text: s, blockBreak: i === 0 && segments.length > 0 });
    });
  }

  return segments;
}

/** Check if a sentence appears (case-insensitive substring) in the target text */
export function sentenceFoundIn(sentence: string, target: string): boolean {
  return target.toLowerCase().includes(sentence.toLowerCase());
}

/** Sort grader entries by: affects_pass first, then relevance (core > important > minor), then name */
export function sortGraderEntries<G extends GraderResultSummary | EvalGraderResult>(
  entries: [string, G][],
  evaluatorMap: Record<string, EvaluatorItem>
): [string, G][] {
  const relevanceOrder: Record<string, number> = { core: 0, important: 1, minor: 2 };
  return [...entries].sort(([nameA], [nameB]) => {
    const metaA = evaluatorMap[nameA];
    const metaB = evaluatorMap[nameB];
    const apA = metaA?.affects_pass ? 0 : 1;
    const apB = metaB?.affects_pass ? 0 : 1;
    if (apA !== apB) return apA - apB;
    const relA = relevanceOrder[metaA?.relevance ?? "minor"] ?? 2;
    const relB = relevanceOrder[metaB?.relevance ?? "minor"] ?? 2;
    if (relA !== relB) return relA - relB;
    return nameA.localeCompare(nameB);
  });
}

/** Sort grader detail cards: failed (affects_pass first) > skipped > passed */
export function sortGraderDetails<G extends GraderResultSummary | EvalGraderResult>(
  entries: [string, G][],
  evaluatorMap: Record<string, EvaluatorItem>
): [string, G][] {
  const relevanceOrder: Record<string, number> = { core: 0, important: 1, minor: 2 };
  return [...entries].sort(([nameA, gA], [nameB, gB]) => {
    const statusA = gA.skipped ? 1 : gA.pass ? 2 : 0;
    const statusB = gB.skipped ? 1 : gB.pass ? 2 : 0;
    if (statusA !== statusB) return statusA - statusB;
    const metaA = evaluatorMap[nameA];
    const metaB = evaluatorMap[nameB];
    const apA = metaA?.affects_pass ? 0 : 1;
    const apB = metaB?.affects_pass ? 0 : 1;
    if (apA !== apB) return apA - apB;
    const relA = relevanceOrder[metaA?.relevance ?? "minor"] ?? 2;
    const relB = relevanceOrder[metaB?.relevance ?? "minor"] ?? 2;
    if (relA !== relB) return relA - relB;
    return nameA.localeCompare(nameB);
  });
}

export function passRateTextColor(passRate: number): string {
  if (passRate === 0) return "text-red-600 dark:text-red-400";
  if (passRate === 1) return "text-green-600 dark:text-green-400";
  return "text-amber-600 dark:text-amber-400";
}

/** Get display name for a grader, falling back to the raw name */
export function graderDisplayName(name: string, evaluatorMap: Record<string, EvaluatorItem>): string {
  return evaluatorMap[name]?.display_name || name;
}

/** Display metadata for a root-cause category (label, badge classes, short blurb). */
export interface RootCauseStyle {
  label: string;
  badge: string;
  description: string;
}

const ROOT_CAUSE_STYLES: Record<string, RootCauseStyle> = {
  retrieval: {
    label: "Retrieval",
    badge: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400",
    description: "The retrieved context didn't contain what was needed to answer.",
  },
  generation: {
    label: "Generation",
    badge: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
    description: "Context was sufficient, but the model's answer mishandled it.",
  },
  task_spec: {
    label: "Task / spec",
    badge: "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400",
    description: "Answer looks grounded — likely an ambiguous question, ground-truth mismatch, or grader calibration issue.",
  },
  indeterminate: {
    label: "Indeterminate",
    badge: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
    description: "Couldn't attribute the failure — often no retrieval context was captured.",
  },
};

export function rootCauseStyle(category: string | null | undefined): RootCauseStyle | null {
  if (!category) return null;
  return ROOT_CAUSE_STYLES[category] ?? {
    label: category,
    badge: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
    description: "",
  };
}

export { formatScoreValue, formatScoreLabel } from "@/components/compare-runs-badges";
