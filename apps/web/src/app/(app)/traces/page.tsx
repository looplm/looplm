"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  getTraces,
  getThreads,
  importTraces,
  type TraceListItem,
  type ThreadListResponse,
} from "@/lib/api";
import TraceFilters, {
  type TraceFilterValues,
  EMPTY_FILTERS,
} from "@/components/trace-filters";
import { useGlobalFilters } from "@/components/global-filters-context";
import ResizableHeader from "@/components/resizable-header";
import { TraceRow, ThreadGroup, RunTreeGroup } from "./trace-table-rows";
import { usePermissions } from "@/components/permissions-context";

type ViewMode = "flat" | "runs" | "threads";

export default function TracesPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("traces");
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("traces-view-mode");
      if (saved === "flat" || saved === "runs" || saved === "threads") return saved;
    }
    return "flat";
  });
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [threadData, setThreadData] = useState<ThreadListResponse | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [filters, setFilters] = useState<TraceFilterValues>(EMPTY_FILTERS);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const globalFilters = useGlobalFilters();

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const json = JSON.parse(text);
      const traces = Array.isArray(json) ? json : json.traces || [];
      await importTraces({ traces, filename: file.name });
      toast.success("Traces imported successfully");
      load();
    } catch (err: any) {
      toast.error("Import failed", { description: err.message });
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // Default widths
  const [colWidths, setColWidths] = useState({
    name: 250,
    thread: 150,
    user: 130,
    input: 250,
    status: 100,
    duration: 100,
    time: 180,
    error: 150,
  });

  const handleResize = (col: keyof typeof colWidths, newWidth: number) => {
    setColWidths((prev) => ({ ...prev, [col]: newWidth }));
  };

  const load = () => {
    setError(null);
    const params: Record<string, string> = { page: String(page), per_page: "50" };

    // Multi-value filters: send comma-separated + mode
    if (filters.status.length > 0) {
      params.status = filters.status.join(",");
      if (filters.statusMode === "exclude") params.status_mode = "exclude";
    }
    if (filters.search.length > 0) {
      params.search = filters.search.join(",");
      if (filters.searchMode === "exclude") params.search_mode = "exclude";
    }
    if (filters.name.length > 0) {
      params.name = filters.name.join(",");
      if (filters.nameMode === "exclude") params.name_mode = "exclude";
    }
    if (filters.threadId.length > 0) {
      params.thread_id = filters.threadId.join(",");
      if (filters.threadIdMode === "exclude") params.thread_id_mode = "exclude";
    }

    // Global filters: date range + environment
    if (globalFilters.startDate) params.start_after = new Date(globalFilters.startDate).toISOString();
    if (globalFilters.endDate) params.start_before = new Date(globalFilters.endDate).toISOString();
    if (globalFilters.environment && globalFilters.environment !== "all") {
      params.environment = globalFilters.environment;
    }
    if (globalFilters.filteredUsers.length > 0) {
      const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
      params[key] = globalFilters.filteredUsers.join(",");
    }

    if (viewMode === "flat") {
      getTraces(params)
        .then((r) => {
          setTraces(r.data);
          setTotalPages(r.pagination.total_pages);
        })
        .catch((e) => setError(e.message));
    } else if (viewMode === "runs") {
      getTraces({ ...params, root_only: "true" })
        .then((r) => {
          setTraces(r.data);
          setTotalPages(r.pagination.total_pages);
        })
        .catch((e) => setError(e.message));
    } else {
      getThreads(params)
        .then((r) => {
          setThreadData(r);
          setTotalPages(r.pagination.total_pages);
        })
        .catch((e) => setError(e.message));
    }
  };

  useEffect(() => { localStorage.setItem("traces-view-mode", viewMode); }, [viewMode]);

  useEffect(() => { load(); }, [page, viewMode, filters, globalFilters.startDate, globalFilters.endDate, globalFilters.environment, globalFilters.userFilterMode, globalFilters.filteredUsers, globalFilters.traceNames]);

  const isEmpty = viewMode === "threads"
    ? !threadData || (threadData.data.length === 0 && threadData.standalone_traces.length === 0)
    : traces.length === 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold">Traces</h1>
        <div className="flex items-center gap-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImport}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={!canEdit}
            title={!canEdit ? "Read-only access. Ask an admin to grant write permission." : undefined}
            className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Import JSON
          </button>
          <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
            <button
              onClick={() => { setViewMode("flat"); setPage(1); }}
              className={`px-3 py-1.5 text-sm ${viewMode === "flat" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
            >
              Flat
            </button>
            <button
              onClick={() => { setViewMode("runs"); setPage(1); }}
              className={`px-3 py-1.5 text-sm ${viewMode === "runs" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
            >
              Runs
            </button>
            <button
              onClick={() => { setViewMode("threads"); setPage(1); }}
              className={`px-3 py-1.5 text-sm ${viewMode === "threads" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
            >
              Threads
            </button>
          </div>
          <Link
            href="/traces/graph"
            className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 rounded-lg border border-gray-200 dark:border-slate-700"
          >
            Graph
          </Link>
        </div>
      </div>

      <TraceFilters
        onFilterChange={useCallback((f: TraceFilterValues) => {
          setFilters(f);
          setPage(1);
        }, [])}
      />

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {isEmpty ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No traces found. Sync an integration to see traces here.
        </div>
      ) : (
        <>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
            <table className="w-full text-sm table-fixed">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400">
                  <ResizableHeader width={colWidths.name} onResize={(w) => handleResize("name", w)} className="text-left py-3 px-4">Name</ResizableHeader>
                  <ResizableHeader width={colWidths.thread} onResize={(w) => handleResize("thread", w)} className="text-left py-3 px-4">Thread ID</ResizableHeader>
                  <ResizableHeader width={colWidths.user} onResize={(w) => handleResize("user", w)} className="text-left py-3 px-4">User ID</ResizableHeader>
                  <ResizableHeader width={colWidths.input} onResize={(w) => handleResize("input", w)} className="text-left py-3 px-4">Input</ResizableHeader>
                  <ResizableHeader width={colWidths.status} onResize={(w) => handleResize("status", w)} className="text-left py-3 px-4">Status</ResizableHeader>
                  <ResizableHeader width={colWidths.duration} onResize={(w) => handleResize("duration", w)} className="text-right py-3 px-4">Duration</ResizableHeader>
                  <ResizableHeader width={colWidths.time} onResize={(w) => handleResize("time", w)} className="text-left py-3 px-4">Time</ResizableHeader>
                  <ResizableHeader width={colWidths.error} onResize={(w) => handleResize("error", w)} className="text-left py-3 px-4">Error</ResizableHeader>
                </tr>
              </thead>
              <tbody>
                {viewMode === "flat" ? (
                  traces.map((t) => <TraceRow key={t.id} t={t} widths={colWidths} />)
                ) : viewMode === "runs" ? (
                  traces.map((t) => <RunTreeGroup key={t.id} trace={t} widths={colWidths} />)
                ) : threadData && (
                  <>
                    {(threadData.order ?? []).map((item) => {
                      if (item.type === "thread") {
                        const thread = threadData.data.find((t) => t.thread_id === item.id);
                        return thread ? <ThreadGroup key={thread.thread_id} thread={thread} widths={colWidths} /> : null;
                      }
                      const trace = threadData.standalone_traces.find((t) => t.id === item.id);
                      return trace ? <TraceRow key={trace.id} t={trace} widths={colWidths} /> : null;
                    })}
                  </>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-4 mt-6">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-3 py-1 bg-gray-100 dark:bg-slate-800 rounded text-sm disabled:opacity-50">&larr; Prev</button>
              <span className="text-sm text-gray-500 dark:text-slate-400">Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(page + 1)} className="px-3 py-1 bg-gray-100 dark:bg-slate-800 rounded text-sm disabled:opacity-50">Next &rarr;</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
