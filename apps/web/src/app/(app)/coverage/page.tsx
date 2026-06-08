"use client";

import { useState } from "react";

import { usePermissions } from "@/components/permissions-context";
import { ProviderManager } from "@/components/coverage/provider-manager";
import { CoverageResultsView } from "@/components/coverage/coverage-results";
import { SuggestionList } from "@/components/coverage/suggestion-list";
import { useCoverage } from "./use-coverage";

const READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export default function CoveragePage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("coverage");

  const {
    providers,
    providerId,
    setProviderId,
    partitionKeys,
    keysLoading,
    datasets,
    run,
    analyzing,
    analyze,
    loadProviders,
    loadDatasets,
    acknowledgements,
    addAcknowledgement,
    removeAcknowledgement,
  } = useCoverage();

  const [managerOpen, setManagerOpen] = useState(false);
  const [partitionKey, setPartitionKey] = useState("");
  const [suggest, setSuggest] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [minCovering, setMinCovering] = useState(1);
  const [maxGaps, setMaxGaps] = useState(15);
  const [maxQuestions, setMaxQuestions] = useState(3);

  const inputCls =
    "px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm";
  const running = analyzing && (!run || run.status === "pending" || run.status === "running");

  function handleRun() {
    if (!partitionKey) return;
    analyze({
      partition_key: partitionKey,
      suggest,
      min_covering_cases: minCovering,
      max_gaps_to_suggest: maxGaps,
      max_questions_per_gap: maxQuestions,
    });
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">RAG Coverage</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
            See which slices of your indexed knowledge base have eval coverage — and draft questions
            for the gaps.
          </p>
        </div>
        <button
          onClick={() => setManagerOpen(true)}
          className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
        >
          Manage providers
        </button>
      </div>

      {providers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center">
          <p className="text-sm text-gray-500 dark:text-slate-400">
            No index providers yet. Connect a retrieval index to analyze coverage.
          </p>
          <button
            onClick={() => setManagerOpen(true)}
            className="mt-3 px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500"
          >
            + Add provider
          </button>
        </div>
      ) : (
        <>
          {/* Controls */}
          <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mb-6">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500 dark:text-slate-400">Provider</span>
                <select
                  value={providerId}
                  onChange={(e) => setProviderId(e.target.value)}
                  className={inputCls}
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500 dark:text-slate-400">Partition key</span>
                <select
                  value={partitionKey}
                  onChange={(e) => setPartitionKey(e.target.value)}
                  disabled={keysLoading || partitionKeys.length === 0}
                  className={inputCls}
                >
                  <option value="">{keysLoading ? "Loading…" : "Select…"}</option>
                  {partitionKeys.map((k) => (
                    <option key={k.key} value={k.key}>
                      {k.label}
                      {k.multivalued ? " (multi)" : ""}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 pb-2">
                <input
                  type="checkbox"
                  checked={suggest}
                  onChange={(e) => setSuggest(e.target.checked)}
                  className="rounded"
                />
                <span className="text-sm">Suggest eval questions for gaps</span>
              </label>

              <button
                onClick={handleRun}
                disabled={!partitionKey || running || !canEdit}
                title={canEdit ? undefined : READ_ONLY_TITLE}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {running ? "Analyzing…" : "Run analysis"}
              </button>

              <button
                onClick={() => setShowAdvanced((v) => !v)}
                className="px-2 py-2 text-xs text-gray-500 dark:text-slate-400 hover:underline"
              >
                {showAdvanced ? "Hide advanced" : "Advanced"}
              </button>
            </div>

            {showAdvanced && (
              <div className="mt-3 flex flex-wrap gap-3 pt-3 border-t border-gray-100 dark:border-slate-800">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-gray-500 dark:text-slate-400">Min covering cases</span>
                  <input
                    type="number"
                    min={1}
                    value={minCovering}
                    onChange={(e) => setMinCovering(Math.max(1, Number(e.target.value)))}
                    className={`${inputCls} w-32`}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-gray-500 dark:text-slate-400">Max gaps to suggest</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={maxGaps}
                    onChange={(e) => setMaxGaps(Number(e.target.value))}
                    className={`${inputCls} w-32`}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-gray-500 dark:text-slate-400">Questions per gap</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={maxQuestions}
                    onChange={(e) => setMaxQuestions(Number(e.target.value))}
                    className={`${inputCls} w-32`}
                  />
                </label>
              </div>
            )}
          </div>

          {/* Running state */}
          {running && (
            <div className="flex items-center gap-3 mb-6 text-sm text-gray-500 dark:text-slate-400">
              <span className="inline-block w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              {run?.status === "running" && run.total > 0
                ? `Drafting suggestions… ${run.processed}/${run.total}`
                : "Analyzing coverage…"}
            </div>
          )}

          {/* Results */}
          {run?.results && (
            <div className="mb-6">
              <CoverageResultsView
                results={run.results}
                acknowledgements={acknowledgements}
                canEdit={canEdit}
                onAcknowledge={addAcknowledgement}
                onUndoAcknowledge={removeAcknowledgement}
              />
            </div>
          )}

          {/* Suggestions */}
          {run?.status === "completed" && (
            <SuggestionList
              suggestions={run.suggestions}
              datasets={datasets}
              canEdit={canEdit}
              onDatasetsChanged={loadDatasets}
            />
          )}

          {run?.status === "completed" && run.suggest && run.suggestions.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-slate-400">
              No suggestions generated (no gaps, or no LLM configured — see Settings → General).
            </p>
          )}
        </>
      )}

      <ProviderManager
        open={managerOpen}
        canEdit={canEdit}
        onClose={() => setManagerOpen(false)}
        onChanged={loadProviders}
      />
    </div>
  );
}
