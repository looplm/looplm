"use client";

/**
 * Chunk quality tab: runs a sampled, read-only analysis of the indexed chunks
 * themselves (size/consistency, duplication/overlap, metadata completeness,
 * parser quality) and renders a scored health report. The run lifecycle lives
 * in `useChunkQuality`; the per-family rendering in `chunk-quality/`.
 */

import { useMemo, useState } from "react";

import type {
  ChunkQualityFinding,
  ChunkQualityResults,
  QualityFamily,
  Severity,
} from "@/lib/api-types/chunk-quality";
import { StatCard } from "@/components/eval-shared";

import {
  BoundaryCard,
  ClaimBoundaryCard,
  CohesionCard,
  RetrievalFrequencyCard,
  StandaloneCard,
} from "./chunk-quality/extended-family-cards";
import { ContentCard, DuplicationCard, MetadataCard, SizeCard } from "./chunk-quality/family-cards";
import { RunConfigDialog } from "./chunk-quality/run-config-dialog";
import { FamilyCard, SeverityChip, scoreTone } from "./chunk-quality/shared";
import { TrendPanel } from "./chunk-quality/trend-panel";
import { useChunkQuality } from "./use-chunk-quality";

const FAMILY_TITLES: Record<QualityFamily, string> = {
  size: "Size & consistency",
  duplication: "Duplication & overlap",
  metadata: "Metadata completeness",
  content: "Content & parser quality",
  boundary: "Boundary quality",
  standalone: "Standalone interpretability",
  cohesion: "Embedding cohesion",
  retrieval_frequency: "Retrieval frequency",
  claim_boundary: "Claim boundaries",
};

const SEVERITY_RANK: Record<Severity, number> = { critical: 0, warn: 1, info: 2 };

function worstSeverity(findings: ChunkQualityFinding[]): Severity | undefined {
  if (findings.some((f) => f.severity === "critical")) return "critical";
  if (findings.some((f) => f.severity === "warn")) return "warn";
  if (findings.some((f) => f.severity === "info")) return "info";
  return undefined;
}

export function ChunkQualityTab({ providerId, canEdit }: { providerId: string; canEdit: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const { run, runs, running, handleRun } = useChunkQuality(providerId, setError);

  const results = run?.results ?? null;
  const findingsByFamily = useMemo(() => {
    const map: Record<string, ChunkQualityFinding[]> = {};
    for (const f of results?.findings ?? []) (map[f.family] ??= []).push(f);
    return map;
  }, [results]);

  const sortedFindings = useMemo(
    () =>
      [...(results?.findings ?? [])].sort(
        (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
      ),
    [results],
  );

  const score = results?.summary.score ?? null;
  const tone = score === null ? null : scoreTone(score);
  const analyzedAt = run?.completed_at ? new Date(run.completed_at).toLocaleString() : null;

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-semibold">Chunk quality</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            A sampled, read-only health check of the indexed chunks: sizes, duplication, metadata,
            parser quality, and boundary quality, plus opt-in LLM and retrieval passes. Nothing is
            written back to the index.
          </p>
        </div>
        {canEdit && (
          <button
            onClick={() => setConfigOpen(true)}
            disabled={running}
            className="flex-shrink-0 px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {running ? "Analyzing…" : run ? "Re-run analysis" : "Run analysis"}
          </button>
        )}
      </div>

      {configOpen && (
        <RunConfigDialog
          sampleSize={run?.sample_size || 8000}
          initialConfig={run?.config ?? null}
          onCancel={() => setConfigOpen(false)}
          onStart={(sampleSize, config) => {
            setConfigOpen(false);
            handleRun(sampleSize, config);
          }}
        />
      )}

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {!run && !running && (
        <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center">
          <p className="text-sm text-gray-500 dark:text-slate-400">
            No analysis yet. Run a sampled quality check to score the chunks in this index.
          </p>
        </div>
      )}

      {running && !results && (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-6">
          Sampling and analyzing chunks… this runs in the background and can take a minute.
        </p>
      )}

      {run?.status === "failed" && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3">
          Analysis failed: {run.error ?? "unknown error"}
        </div>
      )}

      <TrendPanel runs={runs} />

      {results && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
            <StatCard
              label="Health score"
              value={score ?? "—"}
              sub={tone?.label}
              accent={score === null ? undefined : score >= 80 ? "green" : score >= 55 ? "amber" : "red"}
            />
            <StatCard label="Chunks sampled" value={results.sample_size.toLocaleString()} sub={`of ${results.total_docs.toLocaleString()}`} />
            <StatCard label="Findings" value={results.summary.findings_total} sub={`${results.summary.critical} critical · ${results.summary.warn} warn`} />
            <StatCard label="Analyzed" value={analyzedAt ? "✓" : running ? "…" : "—"} sub={analyzedAt ?? undefined} />
          </div>

          {sortedFindings.length > 0 && (
            <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mb-5">
              <p className="text-sm font-semibold mb-2">Findings</p>
              <ul className="space-y-2">
                {sortedFindings.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <SeverityChip severity={f.severity} />
                    <div className="min-w-0">
                      <span className="font-medium">{f.title}</span>{" "}
                      <span className="text-gray-500 dark:text-slate-400">{f.message}</span>
                      {f.examples.length > 0 && (
                        <ul className="mt-1 space-y-0.5">
                          {f.examples.map((ex, j) => (
                            <li key={j} className="text-xs text-gray-400 dark:text-slate-500 truncate font-mono">
                              {ex}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <FamilyCard title={FAMILY_TITLES.size} summary={sizeSummary(results)} accent={worstSeverity(findingsByFamily.size ?? [])} defaultOpen>
            <SizeCard size={results.families.size} />
          </FamilyCard>
          <FamilyCard title={FAMILY_TITLES.duplication} summary={dupSummary(results)} accent={worstSeverity(findingsByFamily.duplication ?? [])}>
            <DuplicationCard dup={results.families.duplication} />
          </FamilyCard>
          <FamilyCard title={FAMILY_TITLES.metadata} summary={metaSummary(results)} accent={worstSeverity(findingsByFamily.metadata ?? [])}>
            <MetadataCard meta={results.families.metadata} />
          </FamilyCard>
          <FamilyCard title={FAMILY_TITLES.content} summary={contentSummary(results)} accent={worstSeverity(findingsByFamily.content ?? [])}>
            <ContentCard content={results.families.content} />
          </FamilyCard>
          {results.families.boundary && (
            <FamilyCard title={FAMILY_TITLES.boundary} summary={boundarySummary(results)} accent={worstSeverity(findingsByFamily.boundary ?? [])}>
              <BoundaryCard boundary={results.families.boundary} />
            </FamilyCard>
          )}
          {results.families.standalone && (
            <FamilyCard title={FAMILY_TITLES.standalone} summary={extSummary(results.families.standalone, (f) => `${f.dependent_pct ?? 0}% context-dependent`)} accent={worstSeverity(findingsByFamily.standalone ?? [])}>
              <StandaloneCard standalone={results.families.standalone} usage={results.usage?.standalone} />
            </FamilyCard>
          )}
          {results.families.cohesion && (
            <FamilyCard title={FAMILY_TITLES.cohesion} summary={extSummary(results.families.cohesion, (f) => `${f.high_spread_pct ?? 0}% multi-topic`)} accent={worstSeverity(findingsByFamily.cohesion ?? [])}>
              <CohesionCard cohesion={results.families.cohesion} />
            </FamilyCard>
          )}
          {results.families.retrieval_frequency && (
            <FamilyCard title={FAMILY_TITLES.retrieval_frequency} summary={extSummary(results.families.retrieval_frequency, (f) => `${f.dead_pct ?? 0}% dead`)} accent={worstSeverity(findingsByFamily.retrieval_frequency ?? [])}>
              <RetrievalFrequencyCard freq={results.families.retrieval_frequency} />
            </FamilyCard>
          )}
          {results.families.claim_boundary && (
            <FamilyCard title={FAMILY_TITLES.claim_boundary} summary={extSummary(results.families.claim_boundary, (f) => `${f.cross_boundary_pct ?? 0}% cross-boundary`)} accent={worstSeverity(findingsByFamily.claim_boundary ?? [])}>
              <ClaimBoundaryCard claims={results.families.claim_boundary} usage={results.usage?.claim_boundary} />
            </FamilyCard>
          )}
        </>
      )}
    </div>
  );
}

function extSummary<T extends { available: boolean; reason?: string }>(
  family: T,
  fmt: (f: T) => string,
): string {
  return family.available ? fmt(family) : (family.reason ?? "did not run");
}

function sizeSummary(r: ChunkQualityResults): string {
  const s = r.families.size;
  if (!s.available) return "no body field";
  return `median ${s.tokens?.p50 ?? "—"} tok · ${s.empty_pct ?? 0}% empty`;
}
function dupSummary(r: ChunkQualityResults): string {
  const d = r.families.duplication;
  if (!d.available) return "no body field";
  return `${d.exact_duplicate_pct ?? 0}% exact dup`;
}
function metaSummary(r: ChunkQualityResults): string {
  return `${r.families.metadata.facetable_field_count} fields · ${r.families.metadata.orphans_pct}% orphan`;
}
function contentSummary(r: ChunkQualityResults): string {
  const c = r.families.content;
  if (!c.available) return "no body field";
  return `${c.mojibake_pct ?? 0}% mojibake`;
}
function boundarySummary(r: ChunkQualityResults): string {
  const b = r.families.boundary;
  if (!b?.available) return "no body field";
  return `${b.bad_end_pct ?? 0}% end mid-content`;
}
