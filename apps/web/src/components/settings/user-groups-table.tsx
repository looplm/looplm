"use client";

import { useState } from "react";
import { TagInput } from "@/components/tag-input";
import type {
  CreateUserGroupBody,
  TraceUser,
  UpdateUserGroupBody,
  UserGroup,
  UserIdentity,
} from "@/lib/api";

const PANEL =
  "rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden";
const INPUT =
  "px-2.5 py-1.5 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-md text-sm text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-60";

/** Groups of identities and raw user IDs, e.g. "Internal QA". */
export default function UserGroupsTable({
  groups,
  identities,
  traceUsers,
  loading,
  editable,
  onCreate,
  onUpdate,
  onDelete,
}: {
  groups: UserGroup[];
  identities: UserIdentity[];
  traceUsers: TraceUser[];
  loading: boolean;
  editable: boolean;
  onCreate: (body: CreateUserGroupBody) => void;
  onUpdate: (id: string, body: UpdateUserGroupBody) => void;
  onDelete: (id: string, name: string) => void;
}) {
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const identityName = (id: string) =>
    identities.find((i) => String(i.id) === id)?.name ?? "Unknown";
  const countById = new Map(traceUsers.map((u) => [u.user_id, u.trace_count ?? 0]));

  function traceTotal(group: UserGroup): number {
    const ids = new Set(group.user_ids ?? []);
    for (const identityId of group.identity_ids ?? []) {
      const identity = identities.find((i) => String(i.id) === String(identityId));
      for (const uid of identity?.user_ids ?? []) ids.add(uid);
    }
    let total = 0;
    for (const uid of ids) total += countById.get(uid) ?? 0;
    return total;
  }

  function create() {
    const name = newName.trim();
    if (!name) return;
    onCreate({ name, description: newDescription.trim() || null });
    setNewName("");
    setNewDescription("");
  }

  function commitName(group: UserGroup) {
    const id = String(group.id);
    const draft = drafts[id];
    if (draft === undefined) return;
    const next = draft.trim();
    setDrafts((prev) => {
      const rest = { ...prev };
      delete rest[id];
      return rest;
    });
    if (!next || next === group.name) return;
    onUpdate(id, { name: next });
  }

  return (
    <div className={PANEL}>
      <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
        <h4 className="font-semibold">Groups</h4>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-slate-400">
          Groups show up in the Filter Users control on Dashboard, Traces, Analytics, Feedback and
          Costs, where they can be included or excluded.
        </p>
      </div>

      {editable && (
        <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800 flex flex-wrap items-center gap-2">
          <input
            className={`${INPUT} w-48`}
            placeholder="Group name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") create();
            }}
          />
          <input
            className={`${INPUT} flex-1 min-w-48`}
            placeholder="Description (optional)"
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") create();
            }}
          />
          <button
            type="button"
            onClick={create}
            disabled={!newName.trim()}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600"
          >
            Add group
          </button>
        </div>
      )}

      {loading ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          Loading...
        </div>
      ) : groups.length === 0 ? (
        <div className="px-6 py-8 text-center text-sm text-gray-500 dark:text-slate-400">
          No groups yet.
        </div>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-slate-800/70">
          {groups.map((group) => {
            const id = String(group.id);
            const memberIdentities = (group.identity_ids ?? []).map(String);
            const unassigned = identities.filter((i) => !memberIdentities.includes(String(i.id)));
            return (
              <div key={id} className="px-6 py-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    className={`${INPUT} w-48`}
                    value={drafts[id] ?? group.name}
                    disabled={!editable}
                    onChange={(e) => setDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                    onBlur={() => commitName(group)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                  />
                  <span className="text-xs text-gray-500 dark:text-slate-400">
                    {group.description || "No description"}
                  </span>
                  <span className="text-xs text-gray-400 dark:text-slate-500">
                    {traceTotal(group).toLocaleString()} traces
                  </span>
                  {editable && (
                    <button
                      type="button"
                      onClick={() => onDelete(id, group.name)}
                      className="ml-auto text-xs text-gray-400 hover:text-red-500"
                    >
                      Delete
                    </button>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {memberIdentities.length === 0 && (group.user_ids ?? []).length === 0 && (
                    <span className="text-xs text-gray-400 dark:text-slate-500">
                      No members yet
                    </span>
                  )}
                  {memberIdentities.map((identityId) => (
                    <span
                      key={identityId}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-[11px] text-indigo-700 dark:text-indigo-300"
                    >
                      {identityName(identityId)}
                      {editable && (
                        <button
                          type="button"
                          className="hover:text-red-500"
                          onClick={() =>
                            onUpdate(id, {
                              identity_ids: memberIdentities.filter((v) => v !== identityId),
                            })
                          }
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                  {editable && unassigned.length > 0 && (
                    <select
                      className={`${INPUT} text-xs w-40`}
                      value=""
                      onChange={(e) => {
                        if (!e.target.value) return;
                        onUpdate(id, { identity_ids: [...memberIdentities, e.target.value] });
                      }}
                    >
                      <option value="">Add identity...</option>
                      {unassigned.map((identity) => (
                        <option key={String(identity.id)} value={String(identity.id)}>
                          {identity.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
                    Extra user IDs
                  </p>
                  {editable ? (
                    <TagInput
                      value={group.user_ids ?? []}
                      onChange={(next) => onUpdate(id, { user_ids: next })}
                      placeholder="Add a raw user ID and press Enter"
                    />
                  ) : (
                    <p className="text-xs font-mono text-gray-500 dark:text-slate-400">
                      {(group.user_ids ?? []).join(", ") || "None"}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
