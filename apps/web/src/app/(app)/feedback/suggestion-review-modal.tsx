"use client";

import { useEffect, useState } from "react";
import type { TestCaseSuggestion, TestDatasetItem } from "@/lib/api";
import { ConfigEditor } from "@/components/config-editor";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

function formFromSuggestion(sug: TestCaseSuggestion): TestCaseFormData {
  const config: Record<string, unknown> = {};
  if (sug.team_filter.length > 0) config.team_filter = sug.team_filter;
  if (sug.tag_filter.length > 0) config.tag_filter = sug.tag_filter;
  return {
    test_id: sug.prompt
      .slice(0, 60)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/-+$/, ""),
    prompt: sug.prompt,
    expected_answer: sug.suggested_expected_answer || "",
    config_json: Object.keys(config).length > 0
      ? JSON.stringify(config, null, 2)
      : "",
  };
}

export function SuggestionReviewModal({
  suggestion,
  datasets,
  onClose,
  onAccept,
  saving,
}: {
  suggestion: TestCaseSuggestion;
  datasets: TestDatasetItem[];
  onClose: () => void;
  onAccept: (datasetId: string, form: TestCaseFormData) => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<TestCaseFormData>(() => formFromSuggestion(suggestion));
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(() => {
    // Pre-select the suggested dataset, or the first one
    if (suggestion.suggested_dataset_id) return suggestion.suggested_dataset_id;
    return datasets[0]?.id ?? "";
  });
  const [configValid, setConfigValid] = useState(true);

  useEffect(() => {
    setForm(formFromSuggestion(suggestion));
    setConfigValid(true);
    setSelectedDatasetId(
      suggestion.suggested_dataset_id || datasets[0]?.id || ""
    );
  }, [suggestion, datasets]);

  const canSave = form.test_id.trim() && form.prompt.trim() && selectedDatasetId && configValid;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800 shrink-0">
            <h2 className="text-lg font-semibold">Review Suggestion</h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200">
              &times;
            </button>
          </div>

          {/* Body */}
          <div className="p-4 space-y-4 overflow-y-auto flex-1">
            {/* Feedback context (read-only) */}
            <div className="rounded-lg border border-gray-100 dark:border-slate-800 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    suggestion.feedback_value === 1 ? "bg-green-500" : "bg-red-500"
                  }`}
                />
                <span className="text-xs text-gray-400 dark:text-slate-500">
                  {suggestion.feedback_value === 1 ? "Positive" : "Negative"} feedback
                  {suggestion.scored_at && ` — ${new Date(suggestion.scored_at).toLocaleDateString("de-DE")}`}
                </span>
              </div>
              {suggestion.actual_answer && (
                <div
                  className={`text-xs p-2 rounded-lg max-h-24 overflow-auto ${
                    suggestion.feedback_value === 1
                      ? "bg-green-50 dark:bg-green-900/10 text-green-800 dark:text-green-300"
                      : "bg-red-50 dark:bg-red-900/10 text-red-800 dark:text-red-300"
                  }`}
                >
                  {suggestion.actual_answer.slice(0, 500)}
                  {suggestion.actual_answer.length > 500 && "..."}
                </div>
              )}
              {suggestion.comment && (
                <p className="text-xs text-gray-500 dark:text-slate-400 italic">
                  &ldquo;{suggestion.comment}&rdquo;
                </p>
              )}
            </div>

            {/* Dataset selector */}
            <div>
              <label className="block text-sm font-medium mb-1">Add to Dataset</label>
              {datasets.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-slate-400">
                  No datasets available.{" "}
                  <a href="/datasets" className="text-indigo-600 dark:text-indigo-400 hover:underline">
                    Create one first
                  </a>
                  .
                </p>
              ) : (
                <select
                  value={selectedDatasetId}
                  onChange={(e) => setSelectedDatasetId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                >
                  {datasets.map((ds) => (
                    <option key={ds.id} value={ds.id}>
                      {ds.name} ({ds.test_count} cases)
                      {ds.id === suggestion.suggested_dataset_id ? " — Suggested" : ""}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Test ID */}
            <div>
              <label className="block text-sm font-medium mb-1">Test ID</label>
              <input
                type="text"
                value={form.test_id}
                onChange={(e) => setForm({ ...form, test_id: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                placeholder="e.g. leistungskurve-definition"
              />
            </div>

            {/* Prompt */}
            <div>
              <label className="block text-sm font-medium mb-1">Prompt</label>
              <textarea
                value={form.prompt}
                onChange={(e) => setForm({ ...form, prompt: e.target.value })}
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
              />
            </div>

            {/* Expected Answer */}
            <div>
              <label className="block text-sm font-medium mb-1">
                Expected Answer
                {suggestion.feedback_value === 0 && suggestion.suggested_expected_answer && (
                  <span className="ml-2 text-xs font-normal text-indigo-500">AI-generated</span>
                )}
              </label>
              <textarea
                value={form.expected_answer}
                onChange={(e) => setForm({ ...form, expected_answer: e.target.value })}
                rows={4}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                placeholder="(optional)"
              />
            </div>

            <hr className="border-gray-100 dark:border-slate-800" />

            {/* Configuration */}
            <ConfigEditor
              configJson={form.config_json}
              onChange={(json) => setForm({ ...form, config_json: json })}
              onValidChange={setConfigValid}
            />
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800 shrink-0">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => onAccept(selectedDatasetId, form)}
              disabled={saving || !canSave}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {saving ? "Adding..." : "Add to Dataset"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
