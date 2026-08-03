"use client";

import { useMemo, useState } from "react";
import type { TraceUser, UserIdentity } from "@/lib/api";
import { claimedUserIds } from "@/lib/user-directory";

const PANEL =
  "rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden";
const INPUT =
  "px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-sm text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-60";

/**
 * Every user ID seen in traces that no identity owns yet.
 *
 * The name field is pre-filled with the `username` the app put in trace metadata, as a
 * suggestion only: nothing is stored until the row is saved.
 */
export default function UserIdSuggestions({
  identities,
  traceUsers,
  loading,
  editable,
  onCreate,
  onMerge,
}: {
  identities: UserIdentity[];
  traceUsers: TraceUser[];
  loading: boolean;
  editable: boolean;
  onCreate: (name: string, userIds: string[]) => void;
  onMerge: (identityId: string, userIds: string[]) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");

  const unnamed = useMemo(() => {
    const claimed = claimedUserIds(identities);
    const rows = traceUsers.filter((u) => !claimed.has(u.user_id));
    return rows.sort((a, b) => (b.trace_count ?? 0) - (a.trace_count ?? 0));
  }, [identities, traceUsers]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return unnamed;
    return unnamed.filter(
      (u) =>
        u.user_id.toLowerCase().includes(q) || (u.username?.toLowerCase().includes(q) ?? false),
    );
  }, [unnamed, search]);

  function save(user: TraceUser) {
    const name = (drafts[user.user_id] ?? user.username ?? "").trim();
    if (!name) return;
    setDrafts((prev) => {
      const rest = { ...prev };
      delete rest[user.user_id];
      return rest;
    });
    onCreate(name, [user.user_id]);
  }

  function merge(user: TraceUser, identityId: string) {
    const identity = identities.find((i) => String(i.id) === identityId);
    if (!identity) return;
    onMerge(identityId, [...(identity.user_ids ?? []), user.user_id]);
  }

  return (
    <div className={PANEL}>
      <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between gap-4">
        <div>
          <h4 className="font-semibold">Unnamed user IDs</h4>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-slate-400">
            Suggested names come from the username in your trace metadata. Nothing is saved until
            you name a row or merge it into an existing person.
          </p>
        </div>
        {unnamed.length > 8 && (
          <input
            className={`${INPUT} w-48 shrink-0`}
            placeholder="Search user IDs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}
      </div>
      {loading ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          Loading...
        </div>
      ) : visible.length === 0 ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          {unnamed.length === 0
            ? "Every user ID in this project has a name."
            : "No user IDs match that search."}
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
              <th className="px-6 py-3 font-medium">User ID</th>
              <th className="px-4 py-3 font-medium text-right w-24">Traces</th>
              <th className="px-6 py-3 font-medium w-64">Name</th>
              <th className="px-6 py-3 font-medium text-right w-56">Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((user) => {
              const draft = drafts[user.user_id] ?? user.username ?? "";
              return (
                <tr
                  key={user.user_id}
                  className="border-b border-gray-100 dark:border-slate-800/70"
                >
                  <td className="px-6 py-3 font-mono text-xs text-gray-700 dark:text-slate-200 truncate max-w-xs">
                    {user.user_id}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-500 dark:text-slate-400">
                    {(user.trace_count ?? 0).toLocaleString()}
                  </td>
                  <td className="px-6 py-3">
                    <input
                      className={`${INPUT} w-full`}
                      placeholder="Add a name"
                      value={draft}
                      disabled={!editable}
                      onChange={(e) =>
                        setDrafts((prev) => ({ ...prev, [user.user_id]: e.target.value }))
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") save(user);
                      }}
                    />
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        disabled={!editable || !draft.trim()}
                        onClick={() => save(user)}
                        className="px-2.5 py-1 rounded-md bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600"
                      >
                        Save
                      </button>
                      {identities.length > 0 && (
                        <select
                          className={`${INPUT} text-xs w-32`}
                          disabled={!editable}
                          value=""
                          onChange={(e) => {
                            if (e.target.value) merge(user, e.target.value);
                          }}
                        >
                          <option value="">Merge into...</option>
                          {identities.map((identity) => (
                            <option key={String(identity.id)} value={String(identity.id)}>
                              {identity.name}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
