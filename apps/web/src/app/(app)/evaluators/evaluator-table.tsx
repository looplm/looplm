"use client";

import { useEffect, useRef } from "react";
import type { EvaluatorItem } from "@/lib/api";
import { TypeBadge, SourceBadge, RelevanceBadge, timeAgo } from "./evaluator-badges";

export type SortKey = "name" | "source" | "type" | "relevance" | "affects_pass" | "total_evaluations" | "pass_rate" | "last_seen_at" | "enabled";
export type SortDir = "asc" | "desc";
export type SortEntry = { key: SortKey; dir: SortDir };

export function SortableHeader({
  label,
  sortKey,
  sorts,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: SortKey;
  sorts: SortEntry[];
  onSort: (key: SortKey, shiftKey: boolean) => void;
  className?: string;
}) {
  const idx = sorts.findIndex((s) => s.key === sortKey);
  const active = idx >= 0;
  const multiSort = sorts.length > 1;
  return (
    <th
      className={`px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-700 dark:hover:text-slate-200 transition-colors ${className}`}
      onClick={(e) => onSort(sortKey, e.shiftKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <span className={`text-[10px] ${active ? "text-indigo-500" : "text-gray-300 dark:text-slate-600"}`}>
          {active
            ? `${multiSort ? `${idx + 1}` : ""}${sorts[idx].dir === "asc" ? "\u25B2" : "\u25BC"}`
            : "\u25B4"}
        </span>
      </span>
    </th>
  );
}

interface EvaluatorTableBodyProps {
  sortedEvaluators: EvaluatorItem[];
  selectedIds: Set<string>;
  allSelected: boolean;
  sorts: SortEntry[];
  highlightName?: string;
  toggleSelect: (id: string) => void;
  toggleSelectAll: () => void;
  handleSort: (key: SortKey, shiftKey: boolean) => void;
  handleToggleEnabled: (ev: EvaluatorItem) => void;
  handleDeleteClick: (id: string) => void;
  onEdit: (ev: EvaluatorItem) => void;
}

export function EvaluatorTableBody({
  sortedEvaluators,
  selectedIds,
  allSelected,
  sorts,
  highlightName,
  toggleSelect,
  toggleSelectAll,
  handleSort,
  handleToggleEnabled,
  handleDeleteClick,
  onEdit,
}: EvaluatorTableBodyProps) {
  const highlightRef = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    if (highlightName && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightName]);
  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
            <th className="px-4 py-3 w-10">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleSelectAll}
                className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
              />
            </th>
            <SortableHeader label="Name" sortKey="name" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Source" sortKey="source" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Type" sortKey="type" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Relevance" sortKey="relevance" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Pass/Fail" sortKey="affects_pass" sorts={sorts} onSort={handleSort} className="text-center" />
            <SortableHeader label="Evaluations" sortKey="total_evaluations" sorts={sorts} onSort={handleSort} className="text-center" />
            <SortableHeader label="Pass Rate" sortKey="pass_rate" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Last Seen" sortKey="last_seen_at" sorts={sorts} onSort={handleSort} />
            <SortableHeader label="Enabled" sortKey="enabled" sorts={sorts} onSort={handleSort} className="text-center" />
            <th className="px-4 py-3 font-medium w-24"></th>
          </tr>
        </thead>
        <tbody>
          {sortedEvaluators.map((ev) => (
            <tr
              key={ev.id}
              ref={ev.name === highlightName ? highlightRef : undefined}
              className={`border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30 ${!ev.enabled ? "opacity-50" : ""} ${ev.name === highlightName ? "ring-2 ring-indigo-500 ring-inset bg-indigo-50/50 dark:bg-indigo-950/20" : ""}`}
            >
              <td className="px-4 py-3">
                <input
                  type="checkbox"
                  checked={selectedIds.has(ev.id)}
                  onChange={() => toggleSelect(ev.id)}
                  className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                />
              </td>
              <td className="px-4 py-3">
                <div>
                  <span className="font-medium">{ev.display_name || ev.name}</span>
                  {ev.display_name && ev.display_name !== ev.name && (
                    <span className="ml-1.5 text-xs text-gray-400 dark:text-slate-500 font-mono">{ev.name}</span>
                  )}
                </div>
                {ev.description && (
                  <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5 truncate max-w-xs" title={ev.description}>
                    {ev.description}
                  </p>
                )}
              </td>
              <td className="px-4 py-3">
                <SourceBadge source={ev.source ?? null} />
              </td>
              <td className="px-4 py-3">
                <TypeBadge type={ev.type} />
              </td>
              <td className="px-4 py-3">
                <RelevanceBadge relevance={ev.relevance} />
              </td>
              <td className="px-4 py-3 text-center">
                {ev.affects_pass ? (
                  <span className="text-green-600 dark:text-green-400" title="Affects pass/fail">&#10003;</span>
                ) : (
                  <span className="text-gray-300 dark:text-slate-600">&ndash;</span>
                )}
              </td>
              <td className="px-4 py-3 text-center text-gray-600 dark:text-slate-300">
                {ev.total_evaluations > 0 ? ev.total_evaluations.toLocaleString() : "-"}
              </td>
              <td className="px-4 py-3">
                {ev.pass_rate != null ? (
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden max-w-[80px]">
                      <div
                        className={`h-full rounded-full ${
                          ev.pass_rate >= 0.8
                            ? "bg-green-500"
                            : ev.pass_rate >= 0.5
                            ? "bg-yellow-500"
                            : "bg-red-500"
                        }`}
                        style={{ width: `${ev.pass_rate * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 dark:text-slate-400 w-10">
                      {(ev.pass_rate * 100).toFixed(0)}%
                    </span>
                  </div>
                ) : (
                  <span className="text-gray-300 dark:text-slate-600">-</span>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-gray-500 dark:text-slate-400 whitespace-nowrap">
                {timeAgo(ev.last_seen_at ?? null)}
              </td>
              <td className="px-4 py-3 text-center">
                <button
                  onClick={() => handleToggleEnabled(ev)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                    ev.enabled ? "bg-indigo-600" : "bg-gray-300 dark:bg-slate-600"
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                      ev.enabled ? "translate-x-4.5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </td>
              <td className="px-4 py-3 text-right">
                <div className="flex items-center justify-end gap-1">
                  <button
                    onClick={() => onEdit(ev)}
                    className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                    title="Edit"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => handleDeleteClick(ev.id)}
                    className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                    title="Delete"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
