"use client";

import type { SuggestionRunResponse, TestCaseSuggestion, TestDatasetItem } from "@/lib/api";
import { SuggestionConditions } from "@/components/test-case-conditions";
import { SuggestionReviewModal } from "./suggestion-review-modal";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

interface SuggestionsTabProps {
  suggestions: TestCaseSuggestion[];
  sugLoading: boolean;
  sugGenerated: boolean;
  sugFilter: "all" | "positive" | "negative";
  setSugFilter: (f: "all" | "positive" | "negative") => void;
  suggestionRun: SuggestionRunResponse | null;
  datasets: TestDatasetItem[];
  selectedSuggestion: TestCaseSuggestion | null;
  setSelectedSuggestion: (s: TestCaseSuggestion | null) => void;
  saving: boolean;
  onAccept: (datasetId: string, form: TestCaseFormData) => void;
  onGenerate: () => void;
  onStop: () => void;
  canEdit: boolean;
}

export function SuggestionsTab({
  suggestions,
  sugLoading,
  sugGenerated,
  sugFilter,
  setSugFilter,
  suggestionRun,
  datasets,
  selectedSuggestion,
  setSelectedSuggestion,
  saving,
  onAccept,
  onGenerate,
  onStop,
  canEdit,
}: SuggestionsTabProps) {
  const runActive =
    suggestionRun !== null && ["pending", "running"].includes(suggestionRun.status);
  const showProgress = sugLoading || runActive;
  const progressLabel = (() => {
    if (!suggestionRun || suggestionRun.status === "pending") return "Starting generation…";
    if (suggestionRun.status === "running") {
      if (suggestionRun.total > 0) {
        return `Summarizing context & drafting criteria… ${suggestionRun.processed} of ${suggestionRun.total}`;
      }
      return "Building suggestions…";
    }
    return "Generating suggestions…";
  })();
  const progressPct =
    suggestionRun && suggestionRun.total > 0
      ? Math.min(100, Math.round((suggestionRun.processed / suggestionRun.total) * 100))
      : null;

  const positiveCount = suggestions.filter((s) => s.feedback_value === 1).length;
  const negativeCount = suggestions.filter((s) => s.feedback_value === 0).length;
  const filteredSuggestions =
    sugFilter === "all"
      ? suggestions
      : suggestions.filter((s) =>
          sugFilter === "positive" ? s.feedback_value === 1 : s.feedback_value === 0,
        );

  const countFor = (f: "all" | "positive" | "negative") =>
    f === "all" ? suggestions.length : f === "positive" ? positiveCount : negativeCount;

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {(["all", "positive", "negative"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setSugFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              sugFilter === f
                ? "bg-indigo-600 text-white"
                : "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700"
            }`}
          >
            {f === "all" ? "All Feedback" : f === "positive" ? "Positive" : "Negative"}
            {suggestions.length > 0 && ` (${countFor(f)})`}
          </button>
        ))}
      </div>

      {showProgress ? (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-200 dark:border-indigo-900/50">
          <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span className="text-sm text-indigo-700 dark:text-indigo-300 whitespace-nowrap">
            {progressLabel}
          </span>
          {progressPct !== null ? (
            <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          ) : (
            <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
              <div className="h-full w-1/3 rounded-full bg-indigo-500 animate-pulse" />
            </div>
          )}
          {suggestionRun && ["pending", "running"].includes(suggestionRun.status) && (
            <button
              onClick={onStop}
              disabled={!canEdit}
              className="px-3 py-1 rounded-lg bg-white dark:bg-slate-900 border border-indigo-300 dark:border-indigo-800 text-xs text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            >
              Stop
            </button>
          )}
        </div>
      ) : null}

      {showProgress && suggestions.length === 0 ? null : suggestions.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400 space-y-3">
          <p>
            {sugGenerated
              ? "No test cases could be built from feedback in the current filter range. Try widening the date range or changing trace types."
              : "Click “Generate Test Cases” to turn user feedback in the current filter range into test case suggestions."}
          </p>
          <button
            onClick={onGenerate}
            disabled={!canEdit}
            className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {sugGenerated ? "Regenerate" : "Generate Test Cases"}
          </button>
        </div>
      ) : filteredSuggestions.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400 space-y-3">
          <p>
            No {sugFilter} suggestions in this batch ({suggestions.length} total). Switch to “All Feedback”
            or regenerate with a different feedback type.
          </p>
          <button
            onClick={() => setSugFilter("all")}
            className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200 text-sm hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
          >
            Show all feedback
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredSuggestions.map((sug) => (
            <div
              key={sug.feedback_id}
              onClick={() => setSelectedSuggestion(sug)}
              className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 cursor-pointer hover:border-indigo-300 dark:hover:border-indigo-700 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`inline-block w-2 h-2 rounded-full ${
                        sug.feedback_value === 1 ? "bg-green-500" : "bg-red-500"
                      }`}
                    />
                    <span className="text-xs text-gray-400 dark:text-slate-500">
                      {sug.feedback_value === 1 ? "Positive" : "Negative"} feedback
                      {sug.scored_at && ` — ${new Date(sug.scored_at).toLocaleDateString("de-DE")}`}
                    </span>
                    {sug.suggested_expected_answer && sug.feedback_value === 0 && (
                      <span
                        className="text-xs text-indigo-500 dark:text-indigo-400"
                        title="Criteria describing what a correct answer must cover, derived from the user feedback. Not a ground-truth answer."
                      >
                        AI-drafted criteria
                      </span>
                    )}
                  </div>
                  <p
                    className="text-sm font-medium mb-2 line-clamp-3 whitespace-pre-line"
                    title={sug.prompt}
                  >
                    {sug.prompt}
                  </p>
                  {sug.actual_answer && (
                    <div
                      className={`text-xs p-2 rounded-lg mb-2 max-h-24 overflow-auto ${
                        sug.feedback_value === 1
                          ? "bg-green-50 dark:bg-green-900/10 text-green-800 dark:text-green-300"
                          : "bg-red-50 dark:bg-red-900/10 text-red-800 dark:text-red-300"
                      }`}
                    >
                      {sug.actual_answer.slice(0, 500)}
                      {sug.actual_answer.length > 500 && "..."}
                    </div>
                  )}
                  {sug.comment && (
                    <p className="text-xs text-gray-500 dark:text-slate-400 italic mb-2">
                      &ldquo;{sug.comment}&rdquo;
                    </p>
                  )}
                  <SuggestionConditions data={sug} />
                </div>
                <div className="flex gap-2 flex-shrink-0 items-start">
                  {sug.trace_id && (
                    <a
                      href={`/traces/${sug.trace_id}`}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-xs text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700"
                    >
                      View trace
                    </a>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); setSelectedSuggestion(sug); }}
                    className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs hover:bg-indigo-500"
                  >
                    Review & Add
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Suggestion Review Modal */}
      {selectedSuggestion && (
        <SuggestionReviewModal
          suggestion={selectedSuggestion}
          datasets={datasets}
          onClose={() => setSelectedSuggestion(null)}
          onAccept={onAccept}
          saving={saving}
        />
      )}
    </div>
  );
}
