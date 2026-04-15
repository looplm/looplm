"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { buildApiUrl } from "./api";
import {
  type RunsState,
  type RunsResponse,
  type FiltersState,
  DEFAULT_FILTERS,
  formatTimestamp,
  formatDuration,
  extractInput,
  extractOutput,
  extractModel,
  groupRunsByTrace,
  copyToClipboard,
} from "./langsmith-utils";

export default function LangsmithRuns() {
  const [state, setState] = useState<RunsState>({ state: "loading" });
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const load = useCallback((cursor?: string) => {
    const params: Record<string, string> = { limit: "50" };
    if (cursor) params.cursor = cursor;
    const url = buildApiUrl("/api/v1/langsmith/runs", params);

    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        return res.json() as Promise<RunsResponse>;
      })
      .then((data) => {
        setState((prev) => {
          if (prev.state === "ready") {
            return {
              state: "ready",
              data,
              items: [...prev.items, ...data.runs],
            };
          }
          return { state: "ready", data, items: data.runs };
        });
      })
      .catch((err) =>
        setState({ state: "error", message: err.message || "Request failed" })
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runTypes = useMemo(() => {
    if (state.state !== "ready") return [];
    const types = new Set<string>();
    state.items.forEach((run) => {
      if (run.run_type) types.add(run.run_type);
    });
    return ["all", ...Array.from(types).sort()];
  }, [state]);

  const traces = useMemo(() => {
    if (state.state !== "ready") return [];
    const grouped = groupRunsByTrace(state.items);
    const search = filters.search.trim().toLowerCase();

    return grouped.filter((trace) => {
      if (filters.errorsOnly && !trace.hasError) return false;
      if (filters.runType !== "all") {
        const matchesType = trace.runs.some(
          (run) => run.run_type === filters.runType
        );
        if (!matchesType) return false;
      }
      if (!search) return true;
      const haystack = [
        trace.id,
        trace.root?.name,
        ...trace.runs.map((run) => run.name),
        ...trace.llmRuns.map((run) => extractInput(run)),
        ...trace.llmRuns.map((run) => extractOutput(run)),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(search);
    });
  }, [state, filters]);

  const handleCopy = useCallback((value: string, label: string) => {
    copyToClipboard(value).then((success) => {
      setCopyStatus(success ? `${label} copied` : `Failed to copy ${label}`);
      window.setTimeout(() => setCopyStatus(null), 1500);
    });
  }, []);

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Recent Traces</h2>
          <p className="text-sm text-gray-500 dark:text-slate-400">
            Grouped by trace to review LLM inputs and outputs at a glance.
          </p>
        </div>
        {state.state === "ready" && (
          <div className="text-xs text-gray-400 dark:text-slate-500">
            {state.items.length} runs loaded
          </div>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-2 text-gray-600 dark:text-slate-300">
          <input
            type="checkbox"
            className="accent-indigo-500"
            checked={filters.errorsOnly}
            onChange={(event) =>
              setFilters((prev) => ({
                ...prev,
                errorsOnly: event.target.checked,
              }))
            }
          />
          Errors only
        </label>
        <label className="flex items-center gap-2 text-gray-600 dark:text-slate-300">
          Run type
          <select
            className="bg-gray-50 dark:bg-slate-950 border border-gray-100 dark:border-slate-800 rounded-md px-2 py-1"
            value={filters.runType}
            onChange={(event) =>
              setFilters((prev) => ({
                ...prev,
                runType: event.target.value,
              }))
            }
          >
            {runTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <input
          type="search"
          placeholder="Search trace, run, or prompt"
          className="flex-1 min-w-[220px] bg-gray-50 dark:bg-slate-950 border border-gray-100 dark:border-slate-800 rounded-md px-3 py-1 text-gray-700 dark:text-slate-200"
          value={filters.search}
          onChange={(event) =>
            setFilters((prev) => ({ ...prev, search: event.target.value }))
          }
        />
        {copyStatus && (
          <div className="text-xs text-gray-500 dark:text-slate-400">{copyStatus}</div>
        )}
      </div>

      {state.state === "loading" && (
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-4">Loading traces…</p>
      )}
      {state.state === "error" && (
        <p className="text-sm text-red-300 mt-4">Error: {state.message}</p>
      )}
      {state.state === "ready" && traces.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-4">No runs found.</p>
      )}
      {state.state === "ready" && traces.length > 0 && (
        <div className="mt-4 space-y-4">
          {traces.map((trace) => {
            const rootInput = trace.root ? extractInput(trace.root) : "—";
            const rootOutput = trace.root ? extractOutput(trace.root) : "—";

            return (
              <div
                key={trace.id}
                className="border border-gray-100 dark:border-slate-800 rounded-lg p-4 bg-gray-50/40 dark:bg-slate-950/40"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-gray-800 dark:text-slate-100">
                      {trace.root?.name || "Trace"}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                      {formatTimestamp(trace.startTime)}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                      <span className="font-mono text-gray-600 dark:text-slate-300 break-all">
                        Trace ID: {trace.id}
                      </span>
                      <button
                        className="px-2 py-1 rounded-md bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-200"
                        onClick={() => handleCopy(trace.id, "Trace ID")}
                      >
                        Copy
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-1 rounded-full bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200">
                      {trace.runs.length} runs
                    </span>
                    <span className="px-2 py-1 rounded-full bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200">
                      {trace.llmRuns.length} LLM calls
                    </span>
                    {trace.hasError && (
                      <span className="px-2 py-1 rounded-full bg-red-900/40 text-red-200">
                        Errors
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-900/60 p-3">
                    <div className="text-gray-500 dark:text-slate-400">Trace input</div>
                    <div className="text-gray-700 dark:text-slate-200 mt-1">
                      {rootInput}
                    </div>
                  </div>
                  <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-900/60 p-3">
                    <div className="text-gray-500 dark:text-slate-400">Trace output</div>
                    <div className="text-gray-700 dark:text-slate-200 mt-1">
                      {rootOutput}
                    </div>
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  {trace.llmRuns.length === 0 && (
                    <p className="text-xs text-gray-500 dark:text-slate-400">
                      No LLM calls captured in this trace.
                    </p>
                  )}
                  {trace.llmRuns.slice(0, 4).map((run, index) => {
                    const model = extractModel(run);
                    const duration = formatDuration(run);

                    return (
                      <div
                        key={`${run.id ?? "llm"}-${index}`}
                        className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-900/60 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                          <span className="font-semibold text-gray-700 dark:text-slate-200">
                            {run.name || "LLM call"}
                          </span>
                          <span>{run.run_type || "llm"}</span>
                          {model && (
                            <span className="px-2 py-1 rounded-full bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200">
                              {model}
                            </span>
                          )}
                          {duration && (
                            <span className="px-2 py-1 rounded-full bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200">
                              {duration}
                            </span>
                          )}
                          {run.error && (
                            <span className="text-red-300">Error</span>
                          )}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                          <span className="font-mono text-gray-600 dark:text-slate-300 break-all">
                            Run ID: {run.id || "unknown"}
                          </span>
                          {run.id && (
                            <button
                              className="px-2 py-1 rounded-md bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-200"
                              onClick={() => handleCopy(run.id!, "Run ID")}
                            >
                              Copy
                            </button>
                          )}
                        </div>
                        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                          <div>
                            <div className="text-gray-500 dark:text-slate-400">Input</div>
                            <div className="text-gray-700 dark:text-slate-200 mt-1">
                              {extractInput(run)}
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500 dark:text-slate-400">Output</div>
                            <div className="text-gray-700 dark:text-slate-200 mt-1">
                              {extractOutput(run)}
                            </div>
                          </div>
                        </div>
                        {run.error && (
                          <div className="mt-2 text-xs text-red-300">
                            Error: {run.error}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {trace.llmRuns.length > 4 && (
                    <div className="text-xs text-gray-500 dark:text-slate-400">
                      {trace.llmRuns.length - 4} more LLM calls in this trace.
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {state.state === "ready" && state.data.next_cursor && (
        <button
          className="mt-4 px-3 py-2 text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
          onClick={() => load(state.data.next_cursor ?? undefined)}
        >
          Load more
        </button>
      )}
    </div>
  );
}
