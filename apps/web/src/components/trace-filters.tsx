"use client";

import { useState, useEffect } from "react";
import {
  getTraceNames,
  getTraceThreadIds,
  getTraceStatuses,
} from "@/lib/api";
import FilterComboBox from "@/components/filter-combo-box";

type FilterMode = "include" | "exclude";

export interface TraceFilterValues {
  search: string[];
  searchMode: FilterMode;
  name: string[];
  nameMode: FilterMode;
  threadId: string[];
  threadIdMode: FilterMode;
  status: string[];
  statusMode: FilterMode;
}

export const EMPTY_FILTERS: TraceFilterValues = {
  search: [],
  searchMode: "include",
  name: [],
  nameMode: "include",
  threadId: [],
  threadIdMode: "include",
  status: [],
  statusMode: "include",
};

interface TraceFiltersProps {
  onFilterChange: (filters: TraceFilterValues) => void;
}

export default function TraceFilters({ onFilterChange }: TraceFiltersProps) {
  const [filters, setFilters] = useState<TraceFilterValues>(EMPTY_FILTERS);

  // Suggestion options from API
  const [nameOptions, setNameOptions] = useState<string[]>([]);
  const [threadIdOptions, setThreadIdOptions] = useState<string[]>([]);
  const [statusOptions, setStatusOptions] = useState<string[]>([]);

  useEffect(() => {
    getTraceNames().then(setNameOptions).catch(() => {});
    getTraceThreadIds().then(setThreadIdOptions).catch(() => {});
    getTraceStatuses().then(setStatusOptions).catch(() => {});
  }, []);

  // Debounced filter emission
  useEffect(() => {
    const handler = setTimeout(() => {
      onFilterChange(filters);
    }, 300);
    return () => clearTimeout(handler);
  }, [filters, onFilterChange]);

  const update = <K extends keyof TraceFilterValues>(
    key: K,
    value: TraceFilterValues[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const hasFilters =
    filters.search.length > 0 ||
    filters.name.length > 0 ||
    filters.threadId.length > 0 ||
    filters.status.length > 0;

  return (
    <div className="flex flex-wrap items-start gap-4 mb-6 p-4 bg-white/50 dark:bg-slate-900/50 border border-gray-100 dark:border-slate-800 rounded-lg">
      <FilterComboBox
        label="Input Search"
        placeholder="Search input keywords..."
        options={[]}
        selected={filters.search}
        onSelectedChange={(v) => update("search", v)}
        mode={filters.searchMode}
        onModeChange={(m) => update("searchMode", m)}
        allowFreeText
      />

      <FilterComboBox
        label="Trace Name"
        placeholder="Filter by name..."
        options={nameOptions}
        selected={filters.name}
        onSelectedChange={(v) => update("name", v)}
        mode={filters.nameMode}
        onModeChange={(m) => update("nameMode", m)}
        allowFreeText
      />

      <FilterComboBox
        label="Thread ID"
        placeholder="Filter by Thread ID..."
        options={threadIdOptions}
        selected={filters.threadId}
        onSelectedChange={(v) => update("threadId", v)}
        mode={filters.threadIdMode}
        onModeChange={(m) => update("threadIdMode", m)}
        allowFreeText
      />

      <FilterComboBox
        label="Status"
        placeholder="Filter by status..."
        options={statusOptions}
        selected={filters.status}
        onSelectedChange={(v) => update("status", v)}
        mode={filters.statusMode}
        onModeChange={(m) => update("statusMode", m)}
        allowFreeText={false}
      />

      {hasFilters && (
        <button
          onClick={() => setFilters(EMPTY_FILTERS)}
          className="self-end mb-1 px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded transition-colors"
        >
          Clear Filters
        </button>
      )}
    </div>
  );
}
