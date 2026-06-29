"use client";

import type { ExclusionItem } from "@/lib/api";

interface ExclusionsListProps {
  exclusions: ExclusionItem[];
  canEdit: boolean;
  onClose: () => void;
  onRemoveExclusion: (externalId: string) => void;
}

export function ExclusionsList({
  exclusions,
  canEdit,
  onClose,
  onRemoveExclusion,
}: ExclusionsListProps) {
  return (
    <div className="mb-4 p-3 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg text-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium">Excluded from sync ({exclusions.length})</span>
        <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-slate-300">Close</button>
      </div>
      {exclusions.length === 0 ? (
        <div className="text-xs text-gray-400 dark:text-slate-500">Nothing excluded. Excluding a prompt removes it and stops future imports from re-adding it.</div>
      ) : (
        <ul className="space-y-1">
          {exclusions.map((ex) => (
            <li key={ex.external_id} className="flex items-center justify-between gap-2 text-xs">
              <span className="font-mono truncate text-gray-600 dark:text-slate-300" title={ex.external_id}>{ex.name || ex.external_id}</span>
              {canEdit && (
                <button
                  onClick={() => onRemoveExclusion(ex.external_id)}
                  className="shrink-0 text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  Un-exclude
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
