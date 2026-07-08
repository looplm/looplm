/**
 * Build a shareable Markdown report of what is missing or incomplete in the
 * retrieval index, from the Source review scan. Rendered client-side from data
 * already loaded by the tab (expectations + per-source verdicts + summary + the
 * client-computed "few chunks" set), so the report needs no extra round trip.
 *
 * The per-source classification mirrors the tab's badge logic
 * (source-review-tab.tsx `isFlagged`/`sparseIds` and source-review-row.tsx badges).
 */

import type {
  SourceExpectation,
  SourceScanResultItem,
  SourceScanSummary,
} from "@/lib/api-types/source-registry";

type Bucket = "error" | "not_indexed" | "incomplete" | "few_chunks" | "ok";

/** Which report bucket a source falls into, given its scan verdict. */
function classify(
  result: SourceScanResultItem | undefined,
  sparse: boolean,
): Bucket | null {
  if (!result) return null; // never scanned — leave out of the report
  if (result.execution_status === "error") return "error";
  if (!result.resolved) return "not_indexed";
  if (result.missing_chunk_count > 0) return "incomplete";
  if (sparse) return "few_chunks";
  return "ok";
}

/** Escape a value for a Markdown table cell (pipes break the table; flatten newlines). */
function cell(s: string): string {
  return s.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
}

/** Metadata suffix for a source, e.g. "(Anwendungshilfe · Strom · BDEW)". */
function meta(e: SourceExpectation): string {
  const parts = [e.typ, e.sparte, e.publisher].filter(Boolean) as string[];
  return parts.length ? ` (${parts.join(" · ")})` : "";
}

// The dimension the breakdown groups by when the tab is set to "Source (Quelle)".
const DEFAULT_GROUP_KEYS: (keyof SourceExpectation)[] = ["publisher", "adapter_tag"];

export function buildSourceReviewReport(opts: {
  expectations: SourceExpectation[];
  results: Map<string, SourceScanResultItem>;
  summary: SourceScanSummary;
  sparseIds: Set<string>;
  providerName?: string;
  groupBy: string;
}): string {
  const { expectations, results, summary, sparseIds, providerName, groupBy } = opts;

  // Classify every scanned source once.
  const scanned = expectations
    .map((e) => ({ e, bucket: classify(results.get(e.id), sparseIds.has(e.id)) }))
    .filter((x): x is { e: SourceExpectation; bucket: Bucket } => x.bucket !== null);

  const inBucket = (b: Bucket) => scanned.filter((x) => x.bucket === b).map((x) => x.e);
  const notIndexed = inBucket("not_indexed");
  const incomplete = inBucket("incomplete");
  const fewChunks = inBucket("few_chunks");
  const errored = inBucket("error");

  // Totals: prefer the backend summary, fall back to the client tally.
  const total = summary.total ?? scanned.length;
  const nNotIndexed = summary.not_indexed ?? notIndexed.length;
  const nIncomplete = summary.incomplete ?? incomplete.length;
  const nErrored = summary.errored ?? errored.length;
  const nOk = summary.ok ?? inBucket("ok").length;

  const lines: string[] = [];
  lines.push(`# What's missing in the index${providerName ? ` — ${providerName}` : ""}`);
  lines.push("");
  lines.push(
    `Generated: ${new Date().toLocaleString()} · ${total} sources scanned · ` +
      `${nNotIndexed} not in index · ${nIncomplete} incomplete · ` +
      `${fewChunks.length} few chunks · ${nErrored} scan errors · ${nOk} ok`,
  );
  lines.push("");

  // Breakdown table, grouped by the tab's current dimension. "none" (per-source)
  // is not a useful grouping for a summary, so fall back to publisher/adapter tag.
  const groupKey: keyof SourceExpectation =
    groupBy !== "none"
      ? (groupBy as keyof SourceExpectation)
      : (DEFAULT_GROUP_KEYS.find((k) => expectations.some((e) => e[k])) ?? "publisher");

  const groups = new Map<string, { notIndexed: number; incomplete: number; few: number; ok: number }>();
  for (const { e, bucket } of scanned) {
    const raw = e[groupKey] as string | null;
    const label = (raw && String(raw).trim()) || "Uncategorized";
    const g = groups.get(label) ?? { notIndexed: 0, incomplete: 0, few: 0, ok: 0 };
    if (bucket === "not_indexed") g.notIndexed += 1;
    else if (bucket === "incomplete") g.incomplete += 1;
    else if (bucket === "few_chunks") g.few += 1;
    else if (bucket === "ok") g.ok += 1;
    // Scan errors are surfaced in their own detail section, not the breakdown table.
    groups.set(label, g);
  }
  if (groups.size > 0) {
    const ordered = [...groups.entries()].sort(
      (a, b) => b[1].notIndexed - a[1].notIndexed || a[0].localeCompare(b[0]),
    );
    lines.push(`## Breakdown by ${groupKey}`);
    lines.push("");
    lines.push("| Group | Not in index | Incomplete | Few chunks | OK |");
    lines.push("|---|---:|---:|---:|---:|");
    for (const [label, g] of ordered) {
      lines.push(`| ${cell(label)} | ${g.notIndexed} | ${g.incomplete} | ${g.few} | ${g.ok} |`);
    }
    lines.push("");
  }

  if (notIndexed.length > 0) {
    lines.push(`## Not in index (${notIndexed.length})`);
    lines.push("");
    for (const e of [...notIndexed].sort((a, b) => a.name.localeCompare(b.name))) {
      lines.push(`- **${e.name}**${meta(e)}`);
    }
    lines.push("");
  }

  if (incomplete.length > 0) {
    lines.push(`## Incomplete (${incomplete.length})`);
    lines.push("");
    for (const e of [...incomplete].sort((a, b) => a.name.localeCompare(b.name))) {
      const n = results.get(e.id)?.missing_chunk_count ?? 0;
      lines.push(`- **${e.name}**${meta(e)} — ${n} missing chunk${n === 1 ? "" : "s"}`);
    }
    lines.push("");
  }

  if (fewChunks.length > 0) {
    lines.push(`## Few chunks (${fewChunks.length})`);
    lines.push("");
    for (const e of [...fewChunks].sort((a, b) => a.name.localeCompare(b.name))) {
      const n = results.get(e.id)?.chunk_count ?? 0;
      lines.push(`- **${e.name}**${meta(e)} — ${n} chunk${n === 1 ? "" : "s"}`);
    }
    lines.push("");
  }

  if (errored.length > 0) {
    lines.push(`## Scan errors (${errored.length})`);
    lines.push("");
    for (const e of [...errored].sort((a, b) => a.name.localeCompare(b.name))) {
      const err = results.get(e.id)?.error ?? "unknown error";
      lines.push(`- **${e.name}**${meta(e)} — ${err}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}
