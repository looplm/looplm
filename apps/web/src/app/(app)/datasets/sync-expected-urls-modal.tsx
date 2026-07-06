"use client";

import { useEffect, useState } from "react";
import { syncAllExpectedUrlsFromLabels, syncExpectedUrlsFromLabels } from "@/lib/api";

type SyncMode = "replace" | "merge";

const MODES: { value: SyncMode; label: string; description: string }[] = [
  {
    value: "replace",
    label: "Recompute (replace)",
    description:
      "Delete each case's current expected URLs and rebuild the list from the chunks labeled relevant. Cases without labeled-relevant chunks keep their URLs.",
  },
  {
    value: "merge",
    label: "Merge",
    description:
      "Keep the current expected URLs and only append label-derived URLs that are missing.",
  },
];

/** Normalized outcome for the result view, shared by both sync scopes. */
type SyncSummary = {
  updated: number;
  unchanged: number;
  skipped: number;
  flagged: number;
  perDataset?: { name: string; updated: number; unchanged: number; skipped: number; flagged: number }[];
};

/**
 * Sync expected page URLs from chunk relevance labels. With a datasetId the sync covers
 * that dataset's cases; without one it runs project-wide across all datasets.
 */
export function SyncExpectedUrlsModal({
  datasetId,
  onClose,
  onSynced,
}: {
  datasetId?: string;
  onClose: () => void;
  onSynced: () => void;
}) {
  const [mode, setMode] = useState<SyncMode>("replace");
  const [includeAi, setIncludeAi] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SyncSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function handleSync() {
    setRunning(true);
    setError(null);
    const gold_source = includeAi ? "both" : "human";
    try {
      if (datasetId) {
        const res = await syncExpectedUrlsFromLabels(datasetId, { mode, gold_source });
        setResult({
          updated: res.updated.length,
          unchanged: res.unchanged.length,
          skipped: res.skipped.length,
          flagged: res.flagged?.length ?? 0,
        });
      } else {
        const res = await syncAllExpectedUrlsFromLabels({ mode, gold_source });
        setResult({
          updated: res.total_updated,
          unchanged: res.total_unchanged,
          skipped: res.total_skipped,
          flagged: res.total_flagged ?? 0,
          perDataset: res.datasets.map((d) => ({
            name: d.dataset_name,
            updated: d.updated.length,
            unchanged: d.unchanged.length,
            skipped: d.skipped.length,
            flagged: d.flagged?.length ?? 0,
          })),
        });
      }
      onSynced();
    } catch {
      setError("Sync failed. Please try again.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-lg">
          <div className="p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">Sync Expected URLs from Labels</h2>
          </div>
          <div className="p-4 space-y-3">
            <p className="text-sm text-gray-600 dark:text-slate-400">
              Derives each test case&apos;s expected page URLs from its chunk relevance labels:
              every chunk judged relevant contributes its source URL, ordered by relevance grade.
              {!datasetId && " Applies to all datasets in the project."}
            </p>
            {!result && (
              <div className="space-y-2">
                {MODES.map((m) => (
                  <label
                    key={m.value}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      mode === m.value
                        ? "border-indigo-400 dark:border-indigo-600 bg-indigo-50/50 dark:bg-indigo-950/20"
                        : "border-gray-200 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-800/50"
                    }`}
                  >
                    <input
                      type="radio"
                      name="sync-mode"
                      checked={mode === m.value}
                      onChange={() => setMode(m.value)}
                      className="mt-1"
                    />
                    <span>
                      <span className="block text-sm font-medium">{m.label}</span>
                      <span className="block text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                        {m.description}
                      </span>
                    </span>
                  </label>
                ))}
                <label className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-slate-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors">
                  <input
                    type="checkbox"
                    checked={includeAi}
                    onChange={(e) => setIncludeAi(e.target.checked)}
                    className="mt-1 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span>
                    <span className="block text-sm font-medium">Include AI judge labels</span>
                    <span className="block text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                      Count the AI judge as an additional annotator when resolving which chunks
                      are relevant (majority vote; adjudicated gold verdicts always win).
                      Without this, only human labels count.
                    </span>
                  </span>
                </label>
              </div>
            )}
            {result && (
              <div className="rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-3 text-sm space-y-1">
                <p>
                  <span className="font-medium">{result.updated}</span>{" "}
                  {result.updated === 1 ? "case" : "cases"} updated
                </p>
                {result.unchanged > 0 && (
                  <p className="text-gray-500 dark:text-slate-400">
                    {result.unchanged} already in sync
                  </p>
                )}
                {result.skipped > 0 && (
                  <p className="text-gray-500 dark:text-slate-400">
                    {result.skipped} skipped (no chunks labeled relevant), left unchanged
                  </p>
                )}
                {result.flagged > 0 && (
                  <p className="text-gray-500 dark:text-slate-400">
                    {result.flagged} skipped (no retrieval expected), never synced
                  </p>
                )}
                {result.perDataset && result.perDataset.length > 0 && (
                  <div className="pt-2 mt-2 border-t border-gray-200 dark:border-slate-700 space-y-0.5 max-h-48 overflow-y-auto">
                    {result.perDataset.map((d) => (
                      <p key={d.name} className="text-xs text-gray-500 dark:text-slate-400">
                        <span className="font-medium text-gray-700 dark:text-slate-300">{d.name}</span>
                        : {d.updated} updated, {d.unchanged} in sync, {d.skipped} skipped
                        {d.flagged > 0 ? `, ${d.flagged} no-retrieval` : ""}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          </div>
          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              {result ? "Close" : "Cancel"}
            </button>
            {!result && (
              <button
                onClick={handleSync}
                disabled={running}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 transition-colors"
              >
                {running ? "Syncing..." : mode === "replace" ? "Recompute URLs" : "Merge URLs"}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
