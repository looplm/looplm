"use client";

import Link from "next/link";
import type { DuplicateGroup } from "@/lib/api";

const READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export function DuplicateGroupCard({
  group,
  index,
  keepId,
  canEdit,
  busy,
  onSelectKeep,
  onDeleteOthers,
  onMerge,
  onDismiss,
}: {
  group: DuplicateGroup;
  index: number;
  keepId: string;
  canEdit: boolean;
  busy: boolean;
  onSelectKeep: (caseId: string) => void;
  onDeleteOthers: () => void;
  onMerge: () => void;
  onDismiss: () => void;
}) {
  const otherCount = group.members.length - 1;
  const isExact = group.match_type === "exact";

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-hidden">
      {/* Group header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-800/30">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium text-gray-700 dark:text-slate-200">
            Group {index + 1}
          </span>
          <span
            className={`px-1.5 py-0.5 rounded text-xs font-medium ${
              isExact
                ? "bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-300"
                : "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300"
            }`}
          >
            {isExact ? "Exact" : `Near · ${Math.round(group.score * 100)}%`}
          </span>
          <span className="text-gray-400 dark:text-slate-500 text-xs">
            {group.members.length} cases
          </span>
        </div>
      </div>

      {/* Members */}
      <ul className="divide-y divide-gray-100/70 dark:divide-slate-800/70">
        {group.members.map((m) => {
          const isKeep = m.case_id === keepId;
          return (
            <li
              key={m.case_id}
              className={`flex items-start gap-3 px-4 py-3 ${
                isKeep ? "bg-emerald-50/50 dark:bg-emerald-950/10" : ""
              }`}
            >
              <label className="flex items-center pt-0.5 cursor-pointer" title="Keep this case">
                <input
                  type="radio"
                  name={`keep-${index}`}
                  checked={isKeep}
                  onChange={() => onSelectKeep(m.case_id)}
                  className="text-emerald-600 focus:ring-emerald-500"
                />
              </label>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs text-indigo-600 dark:text-indigo-400">
                    {m.test_id}
                  </span>
                  {isKeep && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300">
                      Keep
                    </span>
                  )}
                  {m.status === "needs_work" && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300">
                      Needs work
                    </span>
                  )}
                  <Link
                    href={`/datasets/${m.dataset_id}`}
                    className="text-xs text-gray-500 dark:text-slate-400 hover:text-indigo-500 dark:hover:text-indigo-400 hover:underline"
                  >
                    {m.dataset_name}
                  </Link>
                </div>
                <p className="text-sm text-gray-700 dark:text-slate-200 mt-1 line-clamp-2" title={m.prompt}>
                  {m.prompt}
                </p>
              </div>
              <Link
                href={`/datasets/${m.dataset_id}?edit=${m.case_id}`}
                className="shrink-0 text-xs text-gray-500 dark:text-slate-400 hover:text-indigo-500 dark:hover:text-indigo-400 hover:underline pt-0.5"
                title="Open to edit and differentiate"
              >
                Edit
              </Link>
            </li>
          );
        })}
      </ul>

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-gray-100 dark:border-slate-800 bg-gray-50/40 dark:bg-slate-800/20">
        <button
          onClick={onDismiss}
          disabled={busy}
          className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
          title="These are not duplicates — hide this group from future scans"
        >
          Not duplicates
        </button>
        <button
          onClick={onMerge}
          disabled={busy || !canEdit}
          title={!canEdit ? READ_ONLY_TITLE : "Merge the others into the kept case, then delete them"}
          className="px-3 py-1.5 rounded-lg text-sm text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950/30 hover:bg-indigo-100 dark:hover:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-900/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Merge {otherCount} into kept
        </button>
        <button
          onClick={onDeleteOthers}
          disabled={busy || !canEdit}
          title={!canEdit ? READ_ONLY_TITLE : "Delete every case except the kept one"}
          className="px-3 py-1.5 rounded-lg text-sm text-white bg-red-600 hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Delete {otherCount} other{otherCount === 1 ? "" : "s"}
        </button>
      </div>
    </div>
  );
}
