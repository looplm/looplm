"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  getDatasetsPicker,
  triggerEval,
  triggerSession,
  getExperiments,
  importEvalRun,
  type DatasetPickerItem,
  type Experiment,
} from "@/lib/api";
import Tooltip from "@/components/tooltip";
import { usePermissions } from "@/components/permissions-context";

const EVAL_READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

const tabs = [
  { label: "Runs", href: "/evaluations" },
  { label: "Jobs", href: "/evaluations/jobs" },
  { label: "Experiments", href: "/evaluations/experiments" },
  { label: "Reports", href: "/evaluations/reports" },
  { label: "Test Case History", href: "/evaluations/history" },
];

export default function EvaluationsLayout({ children }: { children: React.ReactNode }) {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("evaluations");
  const pathname = usePathname();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [showTriggerMenu, setShowTriggerMenu] = useState(false);
  const [datasets, setDatasets] = useState<DatasetPickerItem[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [datasetsError, setDatasetsError] = useState<string | null>(null);
  const [selectedDatasets, setSelectedDatasets] = useState<Set<string>>(new Set());
  const [filterMode, setFilterMode] = useState<"as_configured" | "no_filters" | "both">("as_configured");
  const [concurrency, setConcurrency] = useState(5);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExperiments, setSelectedExperiments] = useState<Set<string>>(new Set());
  const [useBatch, setUseBatch] = useState(false);
  const [retrievalOnly, setRetrievalOnly] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hide tabs on detail pages
  const isDetailPage =
    (pathname.startsWith("/evaluations/jobs/") && pathname !== "/evaluations/jobs") ||
    (pathname.startsWith("/evaluations/reports/") && pathname !== "/evaluations/reports") ||
    (pathname.match(/^\/evaluations\/[^/]+$/) && pathname !== "/evaluations" && pathname !== "/evaluations/jobs" && pathname !== "/evaluations/reports" && pathname !== "/evaluations/experiments" && pathname !== "/evaluations/history");

  async function handleOpenTriggerMenu() {
    setShowTriggerMenu(true);
    setDatasetsLoading(true);
    setDatasetsError(null);
    setSelectedDatasets(new Set());
    setSelectedExperiments(new Set());
    try {
      const [datasetsData, experimentsData] = await Promise.all([
        getDatasetsPicker(),
        getExperiments().catch(() => ({ data: [] })),
      ]);
      setDatasets(datasetsData.datasets);
      setSelectedDatasets(new Set(datasetsData.datasets.map((d) => d.id)));
      setExperiments(experimentsData.data);
    } catch (err: any) {
      setDatasetsError(err.message || "Failed to load datasets");
    } finally {
      setDatasetsLoading(false);
    }
  }

  function toggleDataset(id: string) {
    setSelectedDatasets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleAllDatasets() {
    if (selectedDatasets.size === datasets.length) {
      setSelectedDatasets(new Set());
    } else {
      setSelectedDatasets(new Set(datasets.map((d) => d.id)));
    }
  }

  function toggleExperiment(id: string) {
    setSelectedExperiments((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleTriggerEval() {
    if (selectedDatasets.size === 0) return;
    setTriggering(true);
    setError(null);
    try {
      const datasetIds = selectedDatasets.size === datasets.length
        ? undefined  // All datasets = send null
        : Array.from(selectedDatasets);

      if (selectedExperiments.size > 0) {
        // Use session trigger for experiments
        await triggerSession(
          Array.from(selectedExperiments),
          datasetIds,
          concurrency,
          undefined,
          useBatch,
        );
      } else {
        // Legacy single-run trigger
        await triggerEval(datasetIds, concurrency, filterMode, useBatch, retrievalOnly);
      }
      setShowTriggerMenu(false);
      router.push("/evaluations/jobs");
    } catch (err: any) {
      setError(err.message || "Failed to trigger eval");
    } finally {
      setTriggering(false);
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setImporting(true);
    setError(null);
    try {
      const resultsFile = files[0];
      const resultsJson = JSON.parse(await resultsFile.text());
      if (files.length > 1) {
        const testCasesJson = JSON.parse(await files[1].text());
        resultsJson.testCases = testCasesJson.testCases || testCasesJson;
      }
      await importEvalRun(resultsJson);
      router.push("/evaluations");
    } catch (err: any) {
      setError(err.message || "Import failed");
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  const totalSelected = selectedDatasets.size;
  const totalTests = datasets
    .filter((d) => selectedDatasets.has(d.id))
    .reduce((sum, d) => sum + d.test_count - (d.needs_work_count ?? 0), 0);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Evaluations</h1>
        <div className="flex items-center gap-2">
          {/* Run Eval button */}
          <div className="relative">
            <Tooltip content={canEdit ? "Run evaluation on selected datasets" : EVAL_READ_ONLY_TITLE}>
              <button
                onClick={handleOpenTriggerMenu}
                disabled={!canEdit}
                className="p-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                aria-label="Run Eval"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" /></svg>
              </button>
            </Tooltip>
            {showTriggerMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowTriggerMenu(false)} />
                <div className="absolute right-0 top-full mt-1 z-20 w-80 rounded-xl bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 shadow-lg p-3">
                  <p className="text-sm font-medium mb-2">Select Datasets</p>
                  {datasetsLoading ? (
                    <p className="text-xs text-gray-400 dark:text-slate-500">Loading datasets...</p>
                  ) : datasetsError?.includes("NOT_CONFIGURED") ? (
                    <div className="text-xs text-gray-500 dark:text-slate-400">
                      <p className="mb-2">Target API endpoint not configured.</p>
                      <Link
                        href="/settings"
                        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                      >
                        Configure in Settings
                      </Link>
                    </div>
                  ) : datasetsError ? (
                    <p className="text-xs text-red-500">{datasetsError}</p>
                  ) : datasets.length === 0 ? (
                    <div className="text-xs text-gray-500 dark:text-slate-400">
                      <p className="mb-2">No datasets found. Create a dataset first.</p>
                      <Link
                        href="/datasets"
                        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                      >
                        Go to Datasets
                      </Link>
                    </div>
                  ) : (
                    <>
                      {/* Select all checkbox */}
                      <label className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 cursor-pointer border-b border-gray-100 dark:border-slate-800 mb-1">
                        <input
                          type="checkbox"
                          checked={selectedDatasets.size === datasets.length}
                          onChange={toggleAllDatasets}
                          className="rounded border-gray-300 dark:border-slate-600"
                        />
                        <span className="text-sm font-medium">All datasets</span>
                      </label>

                      <div className="space-y-0.5 max-h-48 overflow-y-auto">
                        {datasets.map((d) => (
                          <label
                            key={d.id}
                            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedDatasets.has(d.id)}
                              onChange={() => toggleDataset(d.id)}
                              className="rounded border-gray-300 dark:border-slate-600"
                            />
                            <span className="text-sm">{d.name}</span>
                            <span className="ml-auto text-xs text-gray-400 dark:text-slate-500">
                              {d.test_count - (d.needs_work_count ?? 0)} tests
                              {(d.needs_work_count ?? 0) > 0 && (
                                <span className="text-amber-500 dark:text-amber-400"> · {d.needs_work_count} need work</span>
                              )}
                            </span>
                          </label>
                        ))}
                      </div>

                      {/* Experiments */}
                      {experiments.length > 0 && (
                        <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800">
                          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                            Experiments
                            {selectedExperiments.size > 0 && (
                              <span className="ml-1 text-indigo-600 dark:text-indigo-400">({selectedExperiments.size})</span>
                            )}
                          </p>
                          <div className="space-y-0.5 max-h-32 overflow-y-auto">
                            {experiments.map((exp) => (
                              <label
                                key={exp.id}
                                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 cursor-pointer"
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedExperiments.has(exp.id)}
                                  onChange={() => toggleExperiment(exp.id)}
                                  className="rounded border-gray-300 dark:border-slate-600"
                                />
                                <span className="text-sm">{exp.name}</span>
                                <span className="ml-auto text-xs text-gray-400 dark:text-slate-500">
                                  {Object.keys(exp.variables).length} var{Object.keys(exp.variables).length !== 1 ? "s" : ""}
                                </span>
                              </label>
                            ))}
                          </div>
                          {selectedExperiments.size > 0 && (
                            <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1 px-1">
                              Each experiment runs as a separate eval
                            </p>
                          )}
                        </div>
                      )}

                      {/* Filter mode (hidden when experiments selected) */}
                      {selectedExperiments.size === 0 && (
                        <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800">
                          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">Filters</p>
                          <div className="flex gap-1">
                            {([
                              ["as_configured", "As configured"],
                              ["no_filters", "No filters"],
                              ["both", "Both"],
                            ] as const).map(([value, label]) => (
                              <button
                                key={value}
                                onClick={() => setFilterMode(value)}
                                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                                  filterMode === value
                                    ? "bg-indigo-100 dark:bg-indigo-600/30 text-indigo-700 dark:text-indigo-300"
                                    : "text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Concurrency */}
                      <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800">
                        <div className="flex items-center justify-between mb-1.5">
                          <p className="text-xs font-medium text-gray-500 dark:text-slate-400">Concurrency</p>
                          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">{concurrency}</span>
                        </div>
                        <input
                          type="range"
                          min={1}
                          max={10}
                          value={concurrency}
                          onChange={(e) => setConcurrency(Number(e.target.value))}
                          className="w-full h-1.5 rounded-full appearance-none bg-gray-200 dark:bg-slate-700 accent-indigo-600"
                        />
                        <div className="flex justify-between text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">
                          <span>1</span>
                          <span>10</span>
                        </div>
                      </div>

                      {/* Batch mode toggle */}
                      <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={useBatch}
                            onChange={(e) => setUseBatch(e.target.checked)}
                            className="rounded border-gray-300 dark:border-slate-600"
                          />
                          <span className="text-xs font-medium text-gray-600 dark:text-slate-300">Batch mode</span>
                          <span className="text-[10px] text-gray-400 dark:text-slate-500">50% cost, up to 24h</span>
                        </label>
                      </div>

                      {/* Retrieval-only toggle (hidden for experiment sessions) */}
                      {selectedExperiments.size === 0 && (
                        <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={retrievalOnly}
                              onChange={(e) => setRetrievalOnly(e.target.checked)}
                              className="rounded border-gray-300 dark:border-slate-600"
                            />
                            <span className="text-xs font-medium text-gray-600 dark:text-slate-300">Retrieval only</span>
                            <span className="text-[10px] text-gray-400 dark:text-slate-500">skip generation evaluators</span>
                          </label>
                        </div>
                      )}

                      <div className="mt-3 pt-2 border-t border-gray-100 dark:border-slate-800 flex items-center justify-between">
                        <span className="text-xs text-gray-400 dark:text-slate-500">
                          {totalSelected} dataset{totalSelected !== 1 ? "s" : ""}, {totalTests} test{totalTests !== 1 ? "s" : ""}
                        </span>
                        <button
                          onClick={handleTriggerEval}
                          disabled={triggering || totalSelected === 0}
                          className="px-3 py-1.5 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-500 disabled:opacity-50 transition-colors"
                        >
                          {triggering ? "Starting..." : "Run"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Import JSON button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            multiple
            onChange={handleImport}
            className="hidden"
          />
          <Tooltip content={canEdit ? "Import results JSON, or both results + test-cases JSON files" : EVAL_READ_ONLY_TITLE}>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing || !canEdit}
              className="p-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              aria-label="Import JSON"
            >
              {importing ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M6.34 6.34L3.51 3.51" /></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clipRule="evenodd" /></svg>
              )}
            </button>
          </Tooltip>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm flex items-start justify-between gap-2">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 dark:hover:text-red-200 shrink-0">&times;</button>
        </div>
      )}

      {/* Tab bar — hidden on detail pages */}
      {!isDetailPage && (
        <div className="flex gap-2 mb-6">
          {tabs.map((tab) => {
            const active = tab.href === "/evaluations"
              ? pathname === "/evaluations"
              : pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
                    : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
                }`}
              >
                {tab.label}
              </Link>
            );
          })}
        </div>
      )}

      {children}
    </div>
  );
}
