"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useGlobalFilters } from "./global-filters-context";
import { getTraceEnvironments, getTraceUsers, getIntegrations } from "@/lib/api";

type QuickRange = "7d" | "30d" | "90d" | "custom";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 16);
}

function nowLocal(): string {
  return new Date().toISOString().slice(0, 16);
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function detectQuickRange(startDate: string, endDate: string): QuickRange | null {
  if (!startDate) return null;
  for (const days of [7, 30, 90] as const) {
    const expected = daysAgo(days);
    if (startDate.slice(0, 10) === expected.slice(0, 10)) {
      return `${days}d` as QuickRange;
    }
  }
  return "custom";
}

function formatRangeLabel(startDate: string, endDate: string): string {
  if (!startDate) return "";
  const fmt = (s: string) => {
    const d = new Date(s);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };
  const start = fmt(startDate);
  const end = endDate ? fmt(endDate) : "Now";
  return `${start} - ${end}`;
}

export default function GlobalFilterHeader() {
  const {
    startDate,
    endDate,
    environment,
    userFilterMode,
    filteredUsers,
    setStartDate,
    setEndDate,
    setEnvironment,
    setUserFilterMode,
    setFilteredUsers,
    setDateRange,
    resetFilters,
    hasActiveFilters,
    traceNames,
    traceNameOptions,
    canEditTraceNames,
    traceNamesSaving,
    traceNamesError,
    setTraceNames,
  } = useGlobalFilters();

  const [environments, setEnvironments] = useState<string[]>([]);
  const [users, setUsers] = useState<{ user_id: string; username: string | null }[]>([]);
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const userDropdownRef = useRef<HTMLDivElement>(null);
  const userInputRef = useRef<HTMLInputElement>(null);
  const [showTraceDropdown, setShowTraceDropdown] = useState(false);
  const [traceSearch, setTraceSearch] = useState("");
  const traceDropdownRef = useRef<HTMLDivElement>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [showCustom, setShowCustom] = useState(() => {
    const detected = detectQuickRange(startDate, endDate);
    return detected === "custom";
  });

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (userDropdownRef.current && !userDropdownRef.current.contains(e.target as Node)) {
        setShowUserDropdown(false);
      }
      if (traceDropdownRef.current && !traceDropdownRef.current.contains(e.target as Node)) {
        setShowTraceDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    getTraceEnvironments().then(setEnvironments).catch(() => {});
    getTraceUsers().then(setUsers).catch(() => {});
    getIntegrations()
      .then((r) => {
        const timestamps = r.data
          .filter((i) => i.type !== "json_file" && i.last_synced_at)
          .map((i) => new Date(i.last_synced_at!).getTime());
        if (timestamps.length > 0) {
          setLastSyncedAt(new Date(Math.max(...timestamps)).toISOString());
        }
      })
      .catch(() => {});
  }, []);

  const activeRange = detectQuickRange(startDate, endDate);

  const handleQuickRange = (days: number) => {
    setShowCustom(false);
    setDateRange(daysAgo(days), nowLocal());
  };

  const handleCustomToggle = () => {
    setShowCustom((prev) => !prev);
  };

  const pillClass = (active: boolean) =>
    `px-3 py-1 text-xs font-medium rounded-full transition-all ${
      active
        ? "bg-indigo-600 text-white shadow-sm"
        : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-700 hover:text-gray-700 dark:hover:text-slate-200"
    }`;

  return (
    <div className="relative z-40 flex flex-wrap items-center gap-3 mb-6 px-4 py-2.5 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border border-gray-200/60 dark:border-slate-700/60 rounded-xl shadow-sm">
      {/* Date range icon + pills */}
      <div className="flex items-center gap-1.5">
        <svg className="w-4 h-4 text-gray-400 dark:text-slate-500 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
        </svg>
        <div className="flex items-center rounded-full bg-gray-50 dark:bg-slate-800/50 p-0.5 gap-0.5">
          <button onClick={() => handleQuickRange(7)} className={pillClass(activeRange === "7d")}>7d</button>
          <button onClick={() => handleQuickRange(30)} className={pillClass(activeRange === "30d")}>30d</button>
          <button onClick={() => handleQuickRange(90)} className={pillClass(activeRange === "90d")}>90d</button>
          <button onClick={handleCustomToggle} className={pillClass(activeRange === "custom" || showCustom)}>
            Custom
          </button>
        </div>
      </div>

      {/* Active range label (non-custom) */}
      {startDate && !showCustom && (
        <span className="text-xs text-gray-400 dark:text-slate-500">
          {formatRangeLabel(startDate, endDate)}
        </span>
      )}

      {/* Separator */}
      {showCustom && (
        <div className="h-5 w-px bg-gray-200 dark:bg-slate-700 hidden sm:block" />
      )}

      {/* Custom date inputs */}
      {showCustom && (
        <div className="flex items-center gap-2">
          <input
            type="datetime-local"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="px-2.5 py-1 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-xs text-gray-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          />
          <span className="text-gray-300 dark:text-slate-600 text-xs">to</span>
          <input
            type="datetime-local"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="px-2.5 py-1 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-xs text-gray-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
      )}

      {/* Spacer pushes environment + reset to the right */}
      <div className="flex-1" />

      {/* Environment select */}
      {environments.length > 0 && (
        <div className="flex items-center gap-1.5">
          <svg className="w-4 h-4 text-gray-400 dark:text-slate-500 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7" />
          </svg>
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
            className={`px-2.5 py-1 rounded-lg text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-indigo-500 ${
              environment !== "all"
                ? "bg-indigo-50 dark:bg-indigo-600/15 text-indigo-600 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/30"
                : "bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700"
            }`}
          >
            <option value="all">All Environments</option>
            {environments.map((env) => (
              <option key={env} value={env}>{env}</option>
            ))}
          </select>
        </div>
      )}

      {/* User filter (include/exclude combo box) */}
      {users.length > 0 && (
        <div className="relative" ref={userDropdownRef}>
          <button
            onClick={() => {
              setShowUserDropdown((v) => !v);
              setTimeout(() => userInputRef.current?.focus(), 0);
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-indigo-500 ${
              filteredUsers.length > 0
                ? userFilterMode === "exclude"
                  ? "bg-red-50 dark:bg-red-600/15 text-red-600 dark:text-red-300 border border-red-200 dark:border-red-500/30"
                  : "bg-green-50 dark:bg-green-600/15 text-green-600 dark:text-green-300 border border-green-200 dark:border-green-500/30"
                : "bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-700"
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
            </svg>
            {filteredUsers.length > 0
              ? `${filteredUsers.length} ${userFilterMode === "exclude" ? "excluded" : "included"}`
              : "Filter Users"}
          </button>
          {showUserDropdown && (
            <div className="absolute right-0 top-full mt-1 z-50 w-80 bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg shadow-lg overflow-hidden">
              {/* Mode toggle */}
              <div className="flex border-b border-gray-100 dark:border-slate-700">
                {(["include", "exclude"] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setUserFilterMode(mode)}
                    className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                      userFilterMode === mode
                        ? mode === "exclude"
                          ? "bg-red-50 dark:bg-red-600/15 text-red-600 dark:text-red-300"
                          : "bg-green-50 dark:bg-green-600/15 text-green-600 dark:text-green-300"
                        : "text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300"
                    }`}
                  >
                    {mode === "include" ? "Include only" : "Exclude"}
                  </button>
                ))}
              </div>
              {/* Search input */}
              <div className="p-2 border-b border-gray-100 dark:border-slate-700">
                <input
                  ref={userInputRef}
                  type="text"
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  placeholder="Search users..."
                  className="w-full px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-xs text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              {/* Selected tags */}
              {filteredUsers.length > 0 && (
                <div className="px-2 pt-2 pb-1 flex flex-wrap gap-1 border-b border-gray-100 dark:border-slate-700">
                  {filteredUsers.map((uid) => {
                    const u = users.find((u) => u.user_id === uid);
                    const label = u?.username || uid.slice(0, 12) + "...";
                    return (
                      <span
                        key={uid}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${
                          userFilterMode === "exclude"
                            ? "bg-red-100 dark:bg-red-600/20 text-red-700 dark:text-red-300"
                            : "bg-green-100 dark:bg-green-600/20 text-green-700 dark:text-green-300"
                        }`}
                      >
                        {label}
                        <button
                          onClick={() => setFilteredUsers(filteredUsers.filter((id) => id !== uid))}
                          className="hover:opacity-70"
                        >
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}
              {/* User list */}
              <div className="max-h-48 overflow-y-auto py-1">
                {users
                  .filter((u) => {
                    if (!userSearch) return true;
                    const q = userSearch.toLowerCase();
                    return u.user_id.toLowerCase().includes(q) || (u.username?.toLowerCase().includes(q) ?? false);
                  })
                  .map((u) => {
                    const isSelected = filteredUsers.includes(u.user_id);
                    const label = u.username ? `${u.username}` : u.user_id;
                    const sublabel = u.username ? u.user_id : null;
                    return (
                      <button
                        key={u.user_id}
                        onClick={() => {
                          setFilteredUsers(
                            isSelected
                              ? filteredUsers.filter((id) => id !== u.user_id)
                              : [...filteredUsers, u.user_id]
                          );
                          setUserSearch("");
                        }}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors ${
                          isSelected ? "bg-gray-50 dark:bg-slate-700/50" : ""
                        }`}
                      >
                        <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                          isSelected
                            ? userFilterMode === "exclude"
                              ? "bg-red-500 border-red-500 text-white"
                              : "bg-green-500 border-green-500 text-white"
                            : "border-gray-300 dark:border-slate-600"
                        }`}>
                          {isSelected && (
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                            </svg>
                          )}
                        </span>
                        <span className="truncate flex-1">
                          <span className="text-gray-700 dark:text-slate-200">{label}</span>
                          {sublabel && (
                            <span className="text-gray-400 dark:text-slate-500 ml-1 text-[10px]">{sublabel}</span>
                          )}
                        </span>
                      </button>
                    );
                  })}
              </div>
              {/* Clear all */}
              {filteredUsers.length > 0 && (
                <button
                  onClick={() => setFilteredUsers([])}
                  className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-400/10 border-t border-gray-100 dark:border-slate-700 transition-colors"
                >
                  Clear all
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Trace-type filter (persisted to project.settings, owner-only) */}
      {traceNameOptions.length > 0 && (
        <div className="relative" ref={traceDropdownRef}>
          <button
            onClick={() => {
              if (!canEditTraceNames) return;
              setShowTraceDropdown((v) => !v);
            }}
            disabled={!canEditTraceNames}
            title={
              !canEditTraceNames
                ? "Only the project owner can change which trace types are included"
                : "Scope every Observe page to a subset of trace types"
            }
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-indigo-500 ${
              traceNames.length > 0
                ? "bg-indigo-50 dark:bg-indigo-600/15 text-indigo-600 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/30"
                : "bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-700"
            } ${!canEditTraceNames ? "opacity-60 cursor-not-allowed" : ""}`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
            {traceNames.length > 0
              ? `${traceNames.length} trace type${traceNames.length === 1 ? "" : "s"}`
              : "All trace types"}
            {traceNamesSaving && <span className="ml-1 text-[10px] opacity-70">(saving…)</span>}
          </button>
          {showTraceDropdown && canEditTraceNames && (
            <div className="absolute right-0 top-full mt-1 z-50 w-80 bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg shadow-lg overflow-hidden">
              <div className="px-3 py-2 text-[11px] text-gray-500 dark:text-slate-400 border-b border-gray-100 dark:border-slate-700">
                Scopes every number on Dashboard, Traces, Feedback and Costs. Empty = all trace types.
              </div>
              <div className="p-2 border-b border-gray-100 dark:border-slate-700">
                <input
                  type="text"
                  value={traceSearch}
                  onChange={(e) => setTraceSearch(e.target.value)}
                  placeholder="Search trace types..."
                  className="w-full px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-xs text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              <div className="max-h-60 overflow-y-auto py-1">
                {traceNameOptions
                  .filter((n) => !traceSearch || n.toLowerCase().includes(traceSearch.toLowerCase()))
                  .map((n) => {
                    const isSelected = traceNames.includes(n);
                    return (
                      <button
                        key={n}
                        onClick={() => {
                          const next = isSelected
                            ? traceNames.filter((x) => x !== n)
                            : [...traceNames, n];
                          setTraceNames(next);
                        }}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors ${
                          isSelected ? "bg-gray-50 dark:bg-slate-700/50" : ""
                        }`}
                      >
                        <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                          isSelected
                            ? "bg-indigo-500 border-indigo-500 text-white"
                            : "border-gray-300 dark:border-slate-600"
                        }`}>
                          {isSelected && (
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                            </svg>
                          )}
                        </span>
                        <span className="truncate text-gray-700 dark:text-slate-200">{n}</span>
                      </button>
                    );
                  })}
              </div>
              {traceNames.length > 0 && (
                <button
                  onClick={() => setTraceNames([])}
                  className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-400/10 border-t border-gray-100 dark:border-slate-700 transition-colors"
                >
                  Clear (include all types)
                </button>
              )}
              {traceNamesError && (
                <p className="px-3 py-2 text-[11px] text-red-500 border-t border-gray-100 dark:border-slate-700">{traceNamesError}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Last sync indicator */}
      <Link
        href="/settings?tab=integrations"
        className="flex items-center gap-1 text-xs text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors"
        title="View integrations"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
        </svg>
        {lastSyncedAt ? `Synced ${formatRelativeTime(lastSyncedAt)}` : "Never synced"}
      </Link>

      {/* Reset button */}
      {hasActiveFilters && (
        <button
          onClick={resetFilters}
          className="flex items-center gap-1 px-2.5 py-1 text-xs text-gray-400 dark:text-slate-500 hover:text-red-400 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-400/10 rounded-lg transition-colors"
          title="Reset all filters"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
          Reset
        </button>
      )}
    </div>
  );
}
