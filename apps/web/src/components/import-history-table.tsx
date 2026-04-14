"use client";

import type { JsonImportItem } from "@/lib/api";

const ENTITY_TYPE_LABELS: Record<string, string> = {
  traces: "Traces",
  feedback: "Feedback",
  evaluations: "Evaluations",
  datasets: "Datasets",
  prompts: "Prompts",
};

const STATUS_COLORS: Record<string, string> = {
  success: "text-green-500",
  partial: "text-amber-500",
  error: "text-red-500",
};

interface ImportHistoryTableProps {
  imports: JsonImportItem[];
  importFilter: string;
  importPage: number;
  importTotalPages: number;
  onFilterChange: (filter: string) => void;
  onPageChange: (page: number) => void;
}

export function ImportHistoryTable({
  imports,
  importFilter,
  importPage,
  importTotalPages,
  onFilterChange,
  onPageChange,
}: ImportHistoryTableProps) {
  return (
    <div className="mt-12">
      <h2 className="text-xl font-bold mb-4">Import History</h2>
      <div className="flex gap-3 mb-4">
        <select
          value={importFilter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300"
        >
          <option value="all">All Types</option>
          {Object.entries(ENTITY_TYPE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      {imports.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400 text-sm">
          No imports yet. Use the &quot;Import JSON&quot; buttons on individual data pages.
        </div>
      ) : (
        <>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Filename</th>
                  <th className="px-4 py-3 font-medium text-center">Records</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {imports.map((imp) => (
                  <tr key={imp.id} className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {new Date(imp.created_at).toLocaleString("de-DE", {
                        day: "2-digit", month: "2-digit", year: "2-digit",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
                        {ENTITY_TYPE_LABELS[imp.entity_type] || imp.entity_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-slate-200 max-w-xs truncate text-xs">
                      {imp.filename}
                    </td>
                    <td className="px-4 py-3 text-center">{imp.record_count}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-medium ${STATUS_COLORS[imp.status] || "text-gray-500"}`}>
                        {imp.status}
                      </span>
                      {imp.error_message && (
                        <span className="ml-2 text-xs text-red-400" title={imp.error_message}>
                          {imp.error_message.length > 40 ? imp.error_message.slice(0, 40) + "..." : imp.error_message}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {importTotalPages > 1 && (
            <div className="flex items-center justify-center gap-4 mt-4">
              <button
                disabled={importPage <= 1}
                onClick={() => onPageChange(Math.max(1, importPage - 1))}
                className="px-3 py-1 bg-gray-100 dark:bg-slate-800 rounded text-sm disabled:opacity-50"
              >
                Prev
              </button>
              <span className="text-sm text-gray-500 dark:text-slate-400">
                Page {importPage} of {importTotalPages}
              </span>
              <button
                disabled={importPage >= importTotalPages}
                onClick={() => onPageChange(Math.min(importTotalPages, importPage + 1))}
                className="px-3 py-1 bg-gray-100 dark:bg-slate-800 rounded text-sm disabled:opacity-50"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
