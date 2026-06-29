"use client";

import type { Integration } from "@/lib/api";
import { PROMPTS_READ_ONLY_TITLE } from "@/app/(app)/prompts/constants";

interface PromptHeaderProps {
  integrations: Integration[];
  canEdit: boolean;
  syncing: boolean;
  importing: boolean;
  reclustering: boolean;
  githubRepo: string | null;
  githubCount: number;
  exclusionsCount: number;
  inProgress: boolean;
  awaitingSelection: boolean;
  lastRunIncomplete: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onSync: (integrationId: string) => void;
  onToggleExclusions: () => void;
  onRecluster: () => void;
  onCancelExtraction: () => void;
  onDiscover: () => void;
  onImportJson: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function PromptHeader({
  integrations,
  canEdit,
  syncing,
  importing,
  reclustering,
  githubRepo,
  githubCount,
  exclusionsCount,
  inProgress,
  awaitingSelection,
  lastRunIncomplete,
  fileInputRef,
  onSync,
  onToggleExclusions,
  onRecluster,
  onCancelExtraction,
  onDiscover,
  onImportJson,
}: PromptHeaderProps) {
  return (
    <div className="flex items-center justify-between mb-6">
      <h1 className="text-3xl font-bold">Prompts</h1>
      <div className="flex gap-2">
        {integrations.filter((i) => i.type !== "json_file" && i.type !== "github").map((i) => (
          <button
            key={i.id}
            onClick={() => onSync(i.id)}
            disabled={syncing || !canEdit}
            title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
            className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {syncing ? "Syncing..." : `Sync ${i.name}`}
          </button>
        ))}
        {githubCount > 0 && (
          <button
            onClick={onToggleExclusions}
            className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg"
          >
            Excluded ({exclusionsCount})
          </button>
        )}
        {githubCount > 0 && (
          <button
            onClick={onRecluster}
            disabled={reclustering || !canEdit || inProgress}
            title={!canEdit ? PROMPTS_READ_ONLY_TITLE : "Re-organize prompts into groups"}
            className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {reclustering ? "Organizing…" : "Re-cluster"}
          </button>
        )}
        {githubRepo && (
          inProgress || awaitingSelection ? (
            <button
              onClick={onCancelExtraction}
              className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={onDiscover}
              disabled={!canEdit}
              title={!canEdit ? PROMPTS_READ_ONLY_TITLE : `Extract prompts from ${githubRepo}`}
              className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 text-sm rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {lastRunIncomplete && githubCount > 0
                ? `Resume (${githubCount} saved)`
                : "Extract from GitHub"}
            </button>
          )
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={onImportJson}
          className="hidden"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={importing || !canEdit}
          title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
          className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg"
        >
          {importing ? "Importing..." : "Import JSON"}
        </button>
      </div>
    </div>
  );
}
