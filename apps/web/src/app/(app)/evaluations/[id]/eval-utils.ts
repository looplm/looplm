import type { EvalGraderResult, EvaluatorItem, GraderResultSummary } from "@/lib/api";

type ResultLike = {
  pass: boolean;
  graders: Record<string, { pass: boolean; skipped?: boolean }>;
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
