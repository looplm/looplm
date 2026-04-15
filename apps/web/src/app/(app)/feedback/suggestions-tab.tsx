"use client";

import type { TestCaseSuggestion, TestDatasetItem } from "@/lib/api";
import { SuggestionConditions } from "@/components/test-case-conditions";
import { SuggestionReviewModal } from "./suggestion-review-modal";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

interface SuggestionsTabProps {
  suggestions: TestCaseSuggestion[];
  sugLoading: boolean;
  sugFilter: "all" | "positive" | "negative";
  setSugFilter: (f: "all" | "positive" | "negative") => void;
  datasets: TestDatasetItem[];
  selectedSuggestion: TestCaseSuggestion | null;
  setSelectedSuggestion: (s: TestCaseSuggestion | null) => void;
  saving: boolean;
  onAccept: (datasetId: string, form: TestCaseFormData) => void;
}

export function SuggestionsTab({
  suggestions,
  sugLoading,
  sugFilter,
  setSugFilter,
  datasets,
  selectedSuggestion,
  setSelectedSuggestion,
  saving,
  onAccept,
}: SuggestionsTabProps) {
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
          </button>
        ))}
      </div>

      {sugLoading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading suggestions...</p>
      ) : suggestions.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No suggestions available. Feedback from your integration will appear here as test case suggestions.
        </div>
      ) : (
        <div className="space-y-3">
          {suggestions.map((sug) => (
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
                      <span className="text-xs text-indigo-500 dark:text-indigo-400">AI-generated answer</span>
                    )}
                  </div>
                  <p className="text-sm font-medium mb-2">{sug.prompt}</p>
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
                <div className="flex gap-2 flex-shrink-0">
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
