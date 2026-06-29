"use client";

import { useMemo } from "react";
import type { PromptItem, PromptReviewResult } from "@/lib/api";
import { PromptReviewTab, sortBySeverity } from "@/app/(app)/prompts/prompt-review-tab";
import {
  PROMPTS_READ_ONLY_TITLE,
  SEVERITY_COLORS,
  simpleDiff,
  timeAgo,
} from "@/app/(app)/prompts/constants";

interface PromptDetailPanelProps {
  selectedPrompt: PromptItem;
  canEdit: boolean;
  githubRepo: string | null;
  rechecking: boolean;
  reviewing: boolean;
  recheckMsg: string | null;
  clusterDraft: string;
  review: PromptReviewResult | null;
  reviewHistory: PromptReviewResult[];
  versions: PromptItem[];
  activeTab: "review" | "history" | "versions";
  compareA: number | null;
  compareB: number | null;
  copied: boolean;
  onClusterDraftChange: (value: string) => void;
  onSaveCluster: () => void;
  onExclude: (promptId: string) => void;
  onDelete: (promptId: string) => void;
  onRecheck: (promptId: string) => void;
  onReview: (promptId: string) => void;
  onTabChange: (tab: "review" | "history" | "versions") => void;
  onCompareAChange: (value: number | null) => void;
  onCompareBChange: (value: number | null) => void;
  onCopy: (text: string) => void;
  onApply: () => void;
}

export function PromptDetailPanel({
  selectedPrompt,
  canEdit,
  githubRepo,
  rechecking,
  reviewing,
  recheckMsg,
  clusterDraft,
  review,
  reviewHistory,
  versions,
  activeTab,
  compareA,
  compareB,
  copied,
  onClusterDraftChange,
  onSaveCluster,
  onExclude,
  onDelete,
  onRecheck,
  onReview,
  onTabChange,
  onCompareAChange,
  onCompareBChange,
  onCopy,
  onApply,
}: PromptDetailPanelProps) {
  const versionA = useMemo(() => versions.find((v) => v.version === compareA), [versions, compareA]);
  const versionB = useMemo(() => versions.find((v) => v.version === compareB), [versions, compareB]);
  const diff = useMemo(() => {
    if (!versionA || !versionB) return null;
    return simpleDiff(versionA.template, versionB.template);
  }, [versionA, versionB]);

  return (
    <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">{selectedPrompt.name}</h2>
          <span className="text-xs text-gray-400 dark:text-slate-500">
            Version {selectedPrompt.version}
            {selectedPrompt.updated_at ? ` · updated ${timeAgo(selectedPrompt.updated_at)}` : ""}
          </span>
        </div>
        <div className="flex gap-2">
          {selectedPrompt.source === "github" && githubRepo && (
            <button
              onClick={() => onRecheck(selectedPrompt.id)}
              disabled={rechecking || !canEdit}
              title={!canEdit ? PROMPTS_READ_ONLY_TITLE : `Re-extract from ${githubRepo}`}
              className="px-4 py-2 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm rounded-lg"
            >
              {rechecking ? "Checking…" : "Check for updates"}
            </button>
          )}
          <button
            onClick={() => onReview(selectedPrompt.id)}
            disabled={reviewing || !canEdit}
            title={!canEdit ? PROMPTS_READ_ONLY_TITLE : undefined}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg"
          >
            {reviewing ? "Reviewing..." : "Review"}
          </button>
        </div>
      </div>

      {/* Cluster (editable hierarchy) + destructive actions */}
      <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
        <span className="text-gray-400 dark:text-slate-500">Group:</span>
        <input
          value={clusterDraft}
          onChange={(e) => onClusterDraftChange(e.target.value)}
          disabled={!canEdit}
          placeholder="e.g. Graders / Conciseness"
          className="flex-1 min-w-[12rem] bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded px-2 py-1 text-gray-700 dark:text-slate-200"
        />
        <button
          onClick={onSaveCluster}
          disabled={!canEdit || clusterDraft === (selectedPrompt.cluster_path ?? []).join(" / ")}
          className="px-3 py-1 rounded bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Save group
        </button>
        <span className="flex-1" />
        {selectedPrompt.source === "github" && (
          <button
            onClick={() => onExclude(selectedPrompt.id)}
            disabled={!canEdit}
            title="Remove and never re-import"
            className="px-3 py-1 rounded border border-amber-500/40 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Exclude from sync
          </button>
        )}
        <button
          onClick={() => onDelete(selectedPrompt.id)}
          disabled={!canEdit}
          className="px-3 py-1 rounded border border-red-500/40 text-red-600 dark:text-red-400 hover:bg-red-500/10 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Delete
        </button>
      </div>

      {recheckMsg && (
        <div className="mb-4 p-2 text-xs rounded-lg bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700">
          {recheckMsg}
        </div>
      )}

      {(selectedPrompt.variables?.length ?? 0) > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Input Variables</h3>
          <div className="flex flex-wrap gap-1.5">
            {(selectedPrompt.variables ?? []).map((v, i) => (
              <span key={`${v}-${i}`} className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-slate-800 rounded text-gray-600 dark:text-slate-300 font-mono">
                {`{${v}}`}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mb-6">
        <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400 mb-2">Template</h3>
        <pre className="p-4 bg-gray-50 dark:bg-slate-950 rounded-lg text-xs text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
          {selectedPrompt.template}
        </pre>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-gray-100 dark:border-slate-800">
        {(["review", "history", "versions"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => onTabChange(tab)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300"
            }`}
          >
            {tab === "review" ? "Current Review" : tab === "history" ? `History (${reviewHistory.length})` : `Versions (${versions.length})`}
          </button>
        ))}
      </div>

      {/* Current Review Tab */}
      {activeTab === "review" && (
        <PromptReviewTab
          review={review}
          reviewing={reviewing}
          copied={copied}
          onCopy={onCopy}
          onApply={onApply}
        />
      )}

      {/* History Tab */}
      {activeTab === "history" && (
        <div className="space-y-3">
          {reviewHistory.length === 0 ? (
            <div className="text-sm text-gray-400 dark:text-slate-500 p-4 text-center">No reviews yet.</div>
          ) : (
            reviewHistory.map((r) => (
              <div key={r.id} className="p-4 bg-gray-100/50 dark:bg-slate-800/50 rounded-lg border border-gray-100 dark:border-slate-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-500 dark:text-slate-400">
                    {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString() : "Unknown"}
                  </span>
                  <span className="text-[10px] text-gray-300 dark:text-slate-600">{r.model}</span>
                </div>
                <div className="text-xs text-gray-600 dark:text-slate-300 mb-2">
                  {r.anti_patterns?.length ?? 0} anti-pattern{(r.anti_patterns?.length ?? 0) !== 1 ? "s" : ""} · {r.suggestions?.length ?? 0} suggestion{(r.suggestions?.length ?? 0) !== 1 ? "s" : ""}
                </div>
                {sortBySeverity(r.anti_patterns ?? []).map((ap, i) => (
                  <div key={i} className="text-[10px] text-gray-500 dark:text-slate-400 ml-2">
                    <span className={SEVERITY_COLORS[ap.severity] ?? ""}>{ap.severity}</span> {ap.pattern}: {ap.description}
                  </div>
                ))}
                {r.rewritten_prompt && (
                  <details className="mt-2">
                    <summary className="text-[10px] text-indigo-600 dark:text-indigo-400 cursor-pointer">Show rewritten prompt</summary>
                    <pre className="mt-1 p-2 bg-gray-50 dark:bg-slate-950 rounded text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap max-h-32 overflow-auto">
                      {r.rewritten_prompt}
                    </pre>
                  </details>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* Versions Tab */}
      {activeTab === "versions" && (
        <div className="space-y-4">
          {versions.length <= 1 ? (
            <div className="text-sm text-gray-400 dark:text-slate-500 p-4 text-center">Only one version available.</div>
          ) : (
            <>
              <div className="flex gap-4 items-center">
                <div>
                  <label className="text-[10px] text-gray-400 dark:text-slate-500 block mb-1">Version A</label>
                  <select
                    value={compareA ?? ""}
                    onChange={(e) => onCompareAChange(e.target.value ? Number(e.target.value) : null)}
                    className="bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 text-xs rounded px-2 py-1"
                  >
                    <option value="">Select...</option>
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>v{v.version}</option>
                    ))}
                  </select>
                </div>
                <span className="text-gray-300 dark:text-slate-600 mt-4">↔</span>
                <div>
                  <label className="text-[10px] text-gray-400 dark:text-slate-500 block mb-1">Version B</label>
                  <select
                    value={compareB ?? ""}
                    onChange={(e) => onCompareBChange(e.target.value ? Number(e.target.value) : null)}
                    className="bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 text-xs rounded px-2 py-1"
                  >
                    <option value="">Select...</option>
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>v{v.version}</option>
                    ))}
                  </select>
                </div>
              </div>

              {diff && versionA && versionB && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-1">v{versionA.version}</div>
                    <pre className="p-3 bg-gray-50 dark:bg-slate-950 rounded-lg text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
                      {diff.left.map((line, i) => {
                        const otherLine = diff.right[i];
                        const changed = line !== otherLine;
                        return (
                          <span key={i} className={changed ? "bg-red-900/30" : ""}>
                            {line}{"\n"}
                          </span>
                        );
                      })}
                    </pre>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-1">v{versionB.version}</div>
                    <pre className="p-3 bg-gray-50 dark:bg-slate-950 rounded-lg text-[10px] text-gray-600 dark:text-slate-300 whitespace-pre-wrap overflow-auto max-h-64 border border-gray-100 dark:border-slate-800">
                      {diff.right.map((line, i) => {
                        const otherLine = diff.left[i];
                        const changed = line !== otherLine;
                        return (
                          <span key={i} className={changed ? "bg-green-900/30" : ""}>
                            {line}{"\n"}
                          </span>
                        );
                      })}
                    </pre>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
