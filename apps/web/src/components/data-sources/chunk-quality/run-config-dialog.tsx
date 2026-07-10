"use client";

/**
 * Run configuration for a chunk-quality analysis: the base families always run
 * and are free; each extended pass is opt-in with its own sample cap because it
 * spends LLM/embedding budget or depends on traces / gold datasets.
 */

import { useEffect, useState } from "react";

import { getDatasets } from "@/lib/api";
import type { ChunkQualityRunConfig } from "@/lib/api-types/chunk-quality";
import { DEFAULT_RUN_CONFIG } from "@/lib/api-types/chunk-quality";

type Passes = ChunkQualityRunConfig["passes"];

function estimateCalls(sampleSize: number): string {
  // Rough: ~15 chunks per judged batch at default budgets.
  return `~${Math.max(1, Math.ceil(sampleSize / 15))} LLM calls`;
}

export function RunConfigDialog({
  sampleSize: initialSampleSize,
  initialConfig,
  onStart,
  onCancel,
}: {
  sampleSize: number;
  initialConfig: ChunkQualityRunConfig | null;
  onStart: (sampleSize: number, config: ChunkQualityRunConfig) => void;
  onCancel: () => void;
}) {
  const [sampleSize, setSampleSize] = useState(initialSampleSize);
  const [passes, setPasses] = useState<Passes>(
    () => structuredClone(initialConfig?.passes ?? DEFAULT_RUN_CONFIG.passes),
  );
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  useEffect(() => {
    getDatasets()
      .then((res) => setDatasets(res.data.map((d) => ({ id: d.id, name: d.name }))))
      .catch(() => setDatasets([]));
  }, []);

  const update = <K extends keyof Passes>(key: K, patch: Partial<Passes[K]>) =>
    setPasses((p) => ({ ...p, [key]: { ...p[key], ...patch } }));

  const numInput = (value: number, onChange: (v: number) => void, min: number, max: number) => (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
      className="w-24 px-2 py-1 rounded border border-gray-200 dark:border-slate-700 bg-transparent text-sm"
    />
  );

  const datasetSelect = (value: string | null, onChange: (v: string | null) => void) => (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="px-2 py-1 rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm max-w-[14rem]"
    >
      <option value="">All datasets</option>
      {datasets.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
        </option>
      ))}
    </select>
  );

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onCancel} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
          <div className="p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">Configure quality run</h2>
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
              The base checks (size, duplication, metadata, content, boundaries) always run and are
              free. Extended passes are opt-in.
            </p>
          </div>

          <div className="p-4 space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Chunks to sample</p>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  The index sample all families analyze (100 to 50000).
                </p>
              </div>
              {numInput(sampleSize, setSampleSize, 100, 50000)}
            </div>

            <PassRow
              title="Standalone interpretability"
              description="An LLM judges whether each chunk is understandable without its surrounding document. Runs LLM calls and incurs cost."
              hint={passes.standalone.enabled ? estimateCalls(passes.standalone.sample_size) : undefined}
              enabled={passes.standalone.enabled}
              onToggle={(v) => update("standalone", { enabled: v })}
            >
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Chunks to judge
                {numInput(
                  passes.standalone.sample_size,
                  (v) => update("standalone", { sample_size: v }),
                  20,
                  500,
                )}
              </label>
            </PassRow>

            <PassRow
              title="Embedding cohesion"
              description="Embeds each chunk's sentences and flags chunks whose sentences point in unrelated directions (multi-topic chunks). Runs embedding calls and incurs cost."
              enabled={passes.cohesion.enabled}
              onToggle={(v) => update("cohesion", { enabled: v })}
            >
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Chunks to score
                {numInput(
                  passes.cohesion.sample_size,
                  (v) => update("cohesion", { sample_size: v }),
                  20,
                  400,
                )}
              </label>
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Max sentences per chunk
                {numInput(
                  passes.cohesion.max_sentences,
                  (v) => update("cohesion", { max_sentences: v }),
                  5,
                  50,
                )}
              </label>
            </PassRow>

            <PassRow
              title="Retrieval frequency"
              description="Counts how often each sampled chunk shows up in retrieval results, surfacing dead chunks (never retrieved) and hot generic chunks. Free."
              enabled={passes.retrieval_frequency.enabled}
              onToggle={(v) => update("retrieval_frequency", { enabled: v })}
            >
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Source
                <select
                  value={passes.retrieval_frequency.source}
                  onChange={(e) =>
                    update("retrieval_frequency", {
                      source: e.target.value as "traces" | "probe",
                    })
                  }
                  className="px-2 py-1 rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm"
                >
                  <option value="traces">Synced traces</option>
                  <option value="probe">Keyword probe over a dataset</option>
                </select>
              </label>
              {passes.retrieval_frequency.source === "traces" ? (
                <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                  Window (days)
                  {numInput(
                    passes.retrieval_frequency.window_days,
                    (v) => update("retrieval_frequency", { window_days: v }),
                    1,
                    365,
                  )}
                </label>
              ) : (
                <>
                  <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                    Dataset
                    {datasetSelect(passes.retrieval_frequency.dataset_id, (v) =>
                      update("retrieval_frequency", { dataset_id: v }),
                    )}
                  </label>
                  <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                    Max queries
                    {numInput(
                      passes.retrieval_frequency.max_queries,
                      (v) => update("retrieval_frequency", { max_queries: v }),
                      10,
                      300,
                    )}
                  </label>
                </>
              )}
            </PassRow>

            <PassRow
              title="Claim boundaries"
              description="Decomposes gold answers into atomic claims and checks whether each claim's evidence fits in a single labeled chunk or is split across boundaries. Needs labeled relevant chunks. Runs LLM calls and incurs cost."
              hint={
                passes.claim_boundary.enabled
                  ? `~${passes.claim_boundary.max_cases * 2} LLM calls`
                  : undefined
              }
              enabled={passes.claim_boundary.enabled}
              onToggle={(v) => update("claim_boundary", { enabled: v })}
            >
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Dataset
                {datasetSelect(passes.claim_boundary.dataset_id, (v) =>
                  update("claim_boundary", { dataset_id: v }),
                )}
              </label>
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-slate-300">
                Max cases
                {numInput(
                  passes.claim_boundary.max_cases,
                  (v) => update("claim_boundary", { max_cases: v }),
                  5,
                  200,
                )}
              </label>
            </PassRow>
          </div>

          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800">
            <button
              onClick={onCancel}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => onStart(sampleSize, { passes })}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
            >
              Run analysis
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function PassRow({
  title,
  description,
  hint,
  enabled,
  onToggle,
  children,
}: {
  title: string;
  description: string;
  hint?: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-gray-100 dark:border-slate-800 p-3">
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
          className="mt-0.5"
        />
        <span className="min-w-0">
          <span className="text-sm font-medium flex items-center gap-2">
            {title}
            {hint && (
              <span className="text-[11px] font-normal text-gray-400 dark:text-slate-500">
                {hint}
              </span>
            )}
          </span>
          <span className="block text-xs text-gray-500 dark:text-slate-400">{description}</span>
        </span>
      </label>
      {enabled && <div className="mt-2 ml-7 flex flex-wrap gap-x-6 gap-y-2">{children}</div>}
    </div>
  );
}
