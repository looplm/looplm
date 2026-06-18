"use client";

import { useState } from "react";
import { FeedbackTableRow } from "./feedback-table-row";
import type { FeedbackScoreItem, FeedbackListResponse } from "@/lib/api";

const FEEDBACK_READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export type GenerateOutput = "suggestions" | "top-questions" | "themes";

export const OUTPUT_LABELS: Record<GenerateOutput, string> = {
  suggestions: "Suggestions",
  "top-questions": "Top Questions",
  themes: "Themes",
};

interface FeedbackSourcePickerProps {
  // Data
  feedbackResp: FeedbackListResponse | null;
  loading: boolean;
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  // Filters
  filterValue: string;
  setFilterValue: (v: string) => void;
  filterVerdict: string;
  setFilterVerdict: (v: string) => void;
  configuredVerdicts: string[];
  // Selection
  selectedFeedbackIds: Set<string>;
  toggleFeedbackId: (id: string, checked: boolean) => void;
  setPageSelection: (ids: string[], checked: boolean) => void;
  clearSelectedFeedback: () => void;
  selectAllMatching: () => void;
  selectingAll: boolean;
  maxSelectable: number;
  // Row interaction
  onSelectFeedback: (item: FeedbackScoreItem) => void;
  // Generate
  output: GenerateOutput | null;
  onGenerate: (output: GenerateOutput) => void;
  canEdit: boolean;
}

/**
 * The shared feedback selection surface — the feedback table with filters,
 * a selection action bar, and pagination. Rendered as the body of the User
 * Feedback tab (output=null) and as step 1 of each derived analysis tab
 * (output set). The selection it produces drives whichever output is generated.
 */
export function FeedbackSourcePicker({
  feedbackResp,
  loading,
  page,
  setPage,
  filterValue,
  setFilterValue,
  filterVerdict,
  setFilterVerdict,
  configuredVerdicts,
  selectedFeedbackIds,
  toggleFeedbackId,
  setPageSelection,
  clearSelectedFeedback,
  selectAllMatching,
  selectingAll,
  maxSelectable,
  onSelectFeedback,
  output,
  onGenerate,
  canEdit,
}: FeedbackSourcePickerProps) {
  const selectedCount = selectedFeedbackIds.size;
  // Generation is possible without an explicit selection (it falls back to the
  // current filters), so on a derived tab the action bar is always shown.
  const showActions = output !== null || selectedCount > 0;

  return (
    <>
      {/* Filters */}
      <div className="flex gap-3 mb-4 items-center">
        <select
          value={filterValue}
          onChange={(e) => setFilterValue(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300"
        >
          <option value="all">All</option>
          <option value="positive">Positive</option>
          <option value="negative">Negative</option>
        </select>

        <select
          value={filterVerdict}
          onChange={(e) => setFilterVerdict(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300"
        >
          <option value="all">All Verdicts</option>
          {configuredVerdicts.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
          <option value="none">Not evaluated</option>
        </select>
      </div>

      {/* Selection action bar */}
      {showActions && (
        <div className="sticky top-2 z-10 mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800">
          <span className="text-sm text-indigo-700 dark:text-indigo-300">
            {selectedCount > 0 ? (
              <>
                {selectedCount} feedback item{selectedCount === 1 ? "" : "s"} selected
                {feedbackResp && feedbackResp.pagination.total > selectedCount && (
                  <>
                    {" · "}
                    <button
                      onClick={selectAllMatching}
                      disabled={selectingAll}
                      className="underline underline-offset-2 hover:text-indigo-900 dark:hover:text-indigo-100 disabled:opacity-50"
                    >
                      {selectingAll
                        ? "Selecting…"
                        : `Select all ${Math.min(feedbackResp.pagination.total, maxSelectable)} matching`}
                    </button>
                  </>
                )}
              </>
            ) : (
              <>No feedback selected — generating will use the current filters.</>
            )}
          </span>
          <div className="flex gap-2">
            {selectedCount > 0 && (
              <button
                onClick={clearSelectedFeedback}
                className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
              >
                Clear
              </button>
            )}
            <GenerateMenu
              output={output}
              count={selectedCount}
              canEdit={canEdit}
              onGenerate={onGenerate}
            />
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : !feedbackResp || feedbackResp.data.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No feedback found yet. Sync your Langfuse integration to pull scores.
        </div>
      ) : (
        <>
          <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      className="w-4 h-4 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                      checked={feedbackResp.data.length > 0 && feedbackResp.data.every((i) => selectedFeedbackIds.has(String(i.id)))}
                      onChange={(e) => setPageSelection(feedbackResp.data.map((i) => String(i.id)), e.target.checked)}
                    />
                  </th>
                  <th className="px-4 py-3 font-medium">Time</th>
                  <th className="px-4 py-3 font-medium">User Question</th>
                  <th className="px-4 py-3 font-medium w-20 text-center">Value</th>
                  <th className="px-4 py-3 font-medium">Comment</th>
                  <th className="px-4 py-3 font-medium">Verdict</th>
                  <th className="px-4 py-3 font-medium w-20 text-center">Conf.</th>
                  <th className="px-4 py-3 font-medium w-20">Trace</th>
                </tr>
              </thead>
              <tbody>
                {feedbackResp.data.map((item) => (
                  <FeedbackTableRow
                    key={item.id}
                    item={item}
                    configuredVerdicts={configuredVerdicts}
                    onSelect={onSelectFeedback}
                    isSelected={selectedFeedbackIds.has(String(item.id))}
                    onCheckboxChange={toggleFeedbackId}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {feedbackResp.pagination.total_pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500 dark:text-slate-400">
                Page {feedbackResp.pagination.page} of {feedbackResp.pagination.total_pages} ({feedbackResp.pagination.total} total)
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 disabled:opacity-40"
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(feedbackResp!.pagination.total_pages, p + 1))}
                  disabled={page >= feedbackResp.pagination.total_pages}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}

/**
 * Generate control: a primary action plus a dropdown to pick which output to
 * generate from the current selection (or filters). On a derived tab the
 * primary action defaults to that tab's output; on the User Feedback tab it
 * opens the menu directly.
 */
function GenerateMenu({
  output,
  count,
  canEdit,
  onGenerate,
}: {
  output: GenerateOutput | null;
  count: number;
  canEdit: boolean;
  onGenerate: (output: GenerateOutput) => void;
}) {
  const [open, setOpen] = useState(false);
  const countSuffix = count > 0 ? ` (${count})` : "";
  const primaryLabel = output ? `Generate ${OUTPUT_LABELS[output]}${countSuffix}` : `Generate${countSuffix}`;

  const choose = (target: GenerateOutput) => {
    setOpen(false);
    onGenerate(target);
  };

  return (
    <div className="relative flex">
      <button
        onClick={() => (output ? choose(output) : setOpen((o) => !o))}
        disabled={!canEdit}
        title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
        className="px-3 py-1.5 rounded-l-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {primaryLabel}
      </button>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!canEdit}
        aria-label="Choose what to generate"
        title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
        className="px-2 py-1.5 rounded-r-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 border-l border-indigo-400/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <svg className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {open && (
        <>
          {/* Click-away backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 w-44 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 shadow-lg overflow-hidden">
            {(Object.keys(OUTPUT_LABELS) as GenerateOutput[]).map((target) => (
              <button
                key={target}
                onClick={() => choose(target)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors ${
                  target === output
                    ? "text-indigo-600 dark:text-indigo-300 font-medium"
                    : "text-gray-700 dark:text-slate-200"
                }`}
              >
                {OUTPUT_LABELS[target]}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
