"use client";

import { useState } from "react";
import type { TraceUser, UpdateUserIdentityBody, UserIdentity } from "@/lib/api";

const PANEL =
  "rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden";
const INPUT =
  "px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-sm text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-60";

/** Named people and the raw user IDs behind them. */
export default function UserIdentitiesTable({
  identities,
  traceUsers,
  loading,
  editable,
  onRename,
  onDelete,
}: {
  identities: UserIdentity[];
  traceUsers: TraceUser[];
  loading: boolean;
  editable: boolean;
  onRename: (id: string, body: UpdateUserIdentityBody) => void;
  onDelete: (id: string, name: string) => void;
}) {
  // Draft names keyed by identity id, so a half-typed rename survives re-renders.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const countById = new Map(traceUsers.map((u) => [u.user_id, u.trace_count ?? 0]));

  function commitName(identity: UserIdentity) {
    const draft = drafts[String(identity.id)];
    if (draft === undefined) return;
    const next = draft.trim();
    setDrafts((prev) => {
      const rest = { ...prev };
      delete rest[String(identity.id)];
      return rest;
    });
    if (!next || next === identity.name) return;
    onRename(String(identity.id), { name: next });
  }

  return (
    <div className={PANEL}>
      <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
        <h4 className="font-semibold">Named identities</h4>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-slate-400">
          One row per person. Detach a user ID with the × to hand it back to the unnamed list.
        </p>
      </div>
      {loading ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          Loading...
        </div>
      ) : identities.length === 0 ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          No identities yet. Name a user ID below to create the first one.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
              <th className="px-6 py-3 font-medium w-64">Name</th>
              <th className="px-6 py-3 font-medium">User IDs</th>
              <th className="px-4 py-3 font-medium text-right w-24">Traces</th>
              <th className="px-6 py-3 font-medium text-right w-24">Actions</th>
            </tr>
          </thead>
          <tbody>
            {identities.map((identity) => {
              const id = String(identity.id);
              const userIds = identity.user_ids ?? [];
              const traces = userIds.reduce((sum, uid) => sum + (countById.get(uid) ?? 0), 0);
              return (
                <tr key={id} className="border-b border-gray-100 dark:border-slate-800/70">
                  <td className="px-6 py-3">
                    <input
                      className={`${INPUT} w-full`}
                      value={drafts[id] ?? identity.name}
                      disabled={!editable}
                      onChange={(e) => setDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                      onBlur={() => commitName(identity)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                        if (e.key === "Escape") {
                          setDrafts((prev) => {
                            const rest = { ...prev };
                            delete rest[id];
                            return rest;
                          });
                        }
                      }}
                    />
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex flex-wrap gap-1">
                      {userIds.length === 0 && (
                        <span className="text-xs text-gray-400 dark:text-slate-500">
                          No user IDs attached
                        </span>
                      )}
                      {userIds.map((uid) => (
                        <span
                          key={uid}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 dark:bg-slate-800 text-[11px] font-mono text-gray-700 dark:text-slate-200"
                        >
                          {uid}
                          {editable && (
                            <button
                              type="button"
                              title={`Detach ${uid}`}
                              className="hover:text-red-500"
                              onClick={() =>
                                onRename(id, { user_ids: userIds.filter((v) => v !== uid) })
                              }
                            >
                              ×
                            </button>
                          )}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-500 dark:text-slate-400">
                    {traces.toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-right">
                    {editable && (
                      <button
                        type="button"
                        onClick={() => onDelete(id, identity.name)}
                        className="text-xs text-gray-400 hover:text-red-500"
                      >
                        Delete
                      </button>
                    )}
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
