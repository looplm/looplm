"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useGlobalFilters } from "./global-filters-context";
import { useUserDirectory } from "./user-directory-context";
import { claimedUserIds } from "@/lib/user-directory";

/**
 * The Filter Users control: one picker over groups, named identities and still-unnamed user ids,
 * sharing a single include/exclude mode. Selecting a group or identity keeps the group identity in
 * the URL (`ugl` / `uil`); the filters context is what expands it to raw ids for the API.
 */
export default function GlobalFilterUsers() {
  const {
    userFilterMode,
    setUserFilterMode,
    filteredUsers,
    setFilteredUsers,
    filteredIdentityIds,
    setFilteredIdentityIds,
    filteredGroupIds,
    setFilteredGroupIds,
    hasUserSelection,
  } = useGlobalFilters();
  const { identities, groups, traceUsers } = useUserDirectory();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const excluding = userFilterMode === "exclude";
  const q = search.trim().toLowerCase();
  const matches = (...values: (string | null | undefined)[]) =>
    !q || values.some((v) => v?.toLowerCase().includes(q));

  // Unnamed ids only: a named id is reachable through its identity, so listing it twice would let
  // the same person be selected two different ways.
  const unnamedUsers = useMemo(() => {
    const claimed = claimedUserIds(identities);
    return traceUsers.filter((u) => !claimed.has(u.user_id));
  }, [identities, traceUsers]);

  const visibleGroups = groups.filter((g) => matches(g.name, g.description));
  const visibleIdentities = identities.filter((i) => matches(i.name, ...(i.user_ids ?? [])));
  const visibleUnnamed = unnamedUsers.filter((u) => matches(u.user_id, u.username));

  const totalSelected =
    filteredGroupIds.length + filteredIdentityIds.length + filteredUsers.length;

  function toggle(list: string[], setList: (v: string[]) => void, value: string) {
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
    setSearch("");
  }

  function clearAll() {
    setFilteredGroupIds([]);
    setFilteredIdentityIds([]);
    setFilteredUsers([]);
  }

  const label = () => {
    if (!hasUserSelection) return "Filter Users";
    const parts: string[] = [];
    if (filteredGroupIds.length) parts.push(`${filteredGroupIds.length} group${filteredGroupIds.length > 1 ? "s" : ""}`);
    const people = filteredIdentityIds.length + filteredUsers.length;
    if (people) parts.push(`${people} user${people > 1 ? "s" : ""}`);
    return `${parts.join(", ")} ${excluding ? "excluded" : "included"}`;
  };

  const checkbox = (selected: boolean) => (
    <span
      className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
        selected
          ? excluding
            ? "bg-red-500 border-red-500 text-white"
            : "bg-green-500 border-green-500 text-white"
          : "border-gray-300 dark:border-slate-600"
      }`}
    >
      {selected && (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      )}
    </span>
  );

  const row = (
    key: string,
    selected: boolean,
    onClick: () => void,
    primary: string,
    secondary?: string | null,
    mono = false,
  ) => (
    <button
      key={key}
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors ${
        selected ? "bg-gray-50 dark:bg-slate-700/50" : ""
      }`}
    >
      {checkbox(selected)}
      <span className="truncate flex-1">
        <span className={`text-gray-700 dark:text-slate-200 ${mono ? "font-mono" : ""}`}>
          {primary}
        </span>
        {secondary && (
          <span className="text-gray-400 dark:text-slate-500 ml-1 text-[10px] font-mono">
            {secondary}
          </span>
        )}
      </span>
    </button>
  );

  const sectionLabel = (text: string) => (
    <p className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
      {text}
    </p>
  );

  if (traceUsers.length === 0 && groups.length === 0 && identities.length === 0) return null;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => {
          setOpen((v) => !v);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-indigo-500 ${
          hasUserSelection
            ? excluding
              ? "bg-red-50 dark:bg-red-600/15 text-red-600 dark:text-red-300 border border-red-200 dark:border-red-500/30"
              : "bg-green-50 dark:bg-green-600/15 text-green-600 dark:text-green-300 border border-green-200 dark:border-green-500/30"
            : "bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-700"
        }`}
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
        </svg>
        {label()}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-80 bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg shadow-lg overflow-hidden">
          {/* Mode toggle — one mode for the whole selection */}
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

          <div className="p-2 border-b border-gray-100 dark:border-slate-700">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search groups and users..."
              className="w-full px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-xs text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="max-h-72 overflow-y-auto py-1">
            {visibleGroups.length > 0 && sectionLabel("Groups")}
            {visibleGroups.map((group) =>
              row(
                `g-${group.id}`,
                filteredGroupIds.includes(String(group.id)),
                () => toggle(filteredGroupIds, setFilteredGroupIds, String(group.id)),
                group.name,
                group.description,
              ),
            )}

            {visibleIdentities.length > 0 && sectionLabel("People")}
            {visibleIdentities.map((identity) =>
              row(
                `i-${identity.id}`,
                filteredIdentityIds.includes(String(identity.id)),
                () => toggle(filteredIdentityIds, setFilteredIdentityIds, String(identity.id)),
                identity.name,
                (identity.user_ids ?? []).length > 1
                  ? `${(identity.user_ids ?? []).length} IDs`
                  : (identity.user_ids ?? [])[0],
              ),
            )}

            {visibleUnnamed.length > 0 && sectionLabel("Unnamed user IDs")}
            {visibleUnnamed.map((user) =>
              row(
                `u-${user.user_id}`,
                filteredUsers.includes(user.user_id),
                () => toggle(filteredUsers, setFilteredUsers, user.user_id),
                user.username || user.user_id,
                user.username ? user.user_id : null,
                !user.username,
              ),
            )}

            {visibleGroups.length === 0 &&
              visibleIdentities.length === 0 &&
              visibleUnnamed.length === 0 && (
                <p className="px-3 py-4 text-center text-xs text-gray-400 dark:text-slate-500">
                  Nothing matches that search.
                </p>
              )}
          </div>

          {totalSelected > 0 && (
            <button
              onClick={clearAll}
              className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-400/10 border-t border-gray-100 dark:border-slate-700 transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
