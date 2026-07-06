"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { TestCaseSuggestion, TestDatasetItem, RagPipelineView } from "@/lib/api";
import { createDataset, regenerateSuggestionExpectedAnswer, getTraceRagPipeline } from "@/lib/api";
import { ConfigEditor } from "@/components/config-editor";
import RagPipeline from "@/components/rag-pipeline";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

const CREATE_NEW_DATASET = "__create__";

function formFromSuggestion(sug: TestCaseSuggestion): TestCaseFormData {
  const config: Record<string, unknown> = {};
  if ((sug.team_filter?.length ?? 0) > 0) config.team_filter = sug.team_filter;
  if ((sug.tag_filter?.length ?? 0) > 0) config.tag_filter = sug.tag_filter;
  if (sug.expected_sources && sug.expected_sources.length > 0) {
    config.expected_sources = sug.expected_sources;
  }
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
    no_retrieval: false,
  };
}

const WIDE_STORAGE_KEY = "looplm:suggestion-modal-wide";

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
  // Default to the worker's suggested dataset if it found a relevance match.
  // Otherwise default to creating a new one — picking an arbitrary existing
  // dataset would silently mis-categorise the test case.
  const initialDatasetId = (): string =>
    suggestion.suggested_dataset_id ?? CREATE_NEW_DATASET;
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(initialDatasetId);
  const [newDatasetName, setNewDatasetName] = useState("");
  const [creatingDataset, setCreatingDataset] = useState(false);
  const [configValid, setConfigValid] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [ragPipeline, setRagPipeline] = useState<RagPipelineView | null>(null);
  const [wide, setWide] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(WIDE_STORAGE_KEY) === "1";
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(WIDE_STORAGE_KEY, wide ? "1" : "0");
  }, [wide]);

  useEffect(() => {
    setForm(formFromSuggestion(suggestion));
    setConfigValid(true);
    setSelectedDatasetId(suggestion.suggested_dataset_id ?? CREATE_NEW_DATASET);
    setNewDatasetName("");
  }, [suggestion, datasets]);

  useEffect(() => {
    setRagPipeline(null);
    if (!suggestion.trace_id) return;
    getTraceRagPipeline(String(suggestion.trace_id))
      .then((p) => setRagPipeline(p.available ? p : null))
      .catch(() => {});
  }, [suggestion.trace_id]);

  const isCreatingNew = selectedDatasetId === CREATE_NEW_DATASET;
  const canSave =
    form.test_id.trim() &&
    form.prompt.trim() &&
    configValid &&
    (isCreatingNew ? newDatasetName.trim().length > 0 : Boolean(selectedDatasetId));

  async function handleSave() {
    if (isCreatingNew) {
      setCreatingDataset(true);
      try {
        const ds = await createDataset({ name: newDatasetName.trim() });
        onAccept(ds.id, form);
      } catch (err: any) {
        toast.error("Failed to create dataset", { description: err.message });
      } finally {
        setCreatingDataset(false);
      }
      return;
    }
    onAccept(selectedDatasetId, form);
  }

  const traceHref = suggestion.trace_id ? `/traces/${suggestion.trace_id}` : null;

  async function handleRegenerate() {
    setRegenerating(true);
    try {
      const { expected_answer } = await regenerateSuggestionExpectedAnswer(
        String(suggestion.feedback_id),
      );
      if (expected_answer) {
        setForm((f) => ({ ...f, expected_answer }));
        toast.success("Criteria regenerated");
      } else {
        toast.error("LLM returned an empty result");
      }
    } catch (err: any) {
      toast.error("Failed to regenerate", { description: err.message });
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div
          className={`bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-h-[90vh] flex flex-col transition-[max-width] duration-150 ${
            wide ? "max-w-7xl" : "max-w-4xl"
          }`}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800 shrink-0">
            <h2 className="text-lg font-semibold">Review Suggestion</h2>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setWide((w) => !w)}
                title={wide ? "Narrow modal" : "Widen modal"}
                aria-label={wide ? "Narrow modal" : "Widen modal"}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 p-1 rounded-md hover:bg-gray-100 dark:hover:bg-slate-800"
              >
                {wide ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 15 3 21m0 0h5.25M3 21v-5.25M15 9l6-6m0 0h-5.25M21 3v5.25" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9m11.25-5.25v4.5m0-4.5h-4.5m4.5 0L15 9m-11.25 11.25v-4.5m0 4.5h4.5m-4.5 0L9 15m11.25 5.25v-4.5m0 4.5h-4.5m4.5 0L15 15" />
                  </svg>
                )}
              </button>
              <button
                onClick={onClose}
                aria-label="Close"
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 px-2"
              >
                &times;
              </button>
            </div>
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
              {traceHref && (
                <a
                  href={traceHref}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  View raw trace
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                </a>
              )}
            </div>

            {/* RAG pipeline (when the source trace is an agentic-RAG trace) */}
            {ragPipeline && <RagPipeline view={ragPipeline} compact />}

            {/* Dataset selector */}
            <div>
              <label className="block text-sm font-medium mb-1">Add to Dataset</label>
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
                <option value={CREATE_NEW_DATASET}>+ Create new dataset…</option>
              </select>
              {isCreatingNew && (
                <input
                  type="text"
                  value={newDatasetName}
                  onChange={(e) => setNewDatasetName(e.target.value)}
                  placeholder="New dataset name"
                  autoFocus
                  className="mt-2 w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                />
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
              <label className="block text-sm font-medium mb-1">
                Prompt
                {form.prompt.includes("[Earlier in this conversation") && (
                  <span className="ml-2 text-xs font-normal text-gray-500 dark:text-slate-400">
                    includes conversation topic — edit as needed
                  </span>
                )}
              </label>
              <textarea
                value={form.prompt}
                onChange={(e) => setForm({ ...form, prompt: e.target.value })}
                rows={form.prompt.includes("\n") ? 8 : 3}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
              />
            </div>

            {/* Expected Answer */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium">
                  Expected Answer
                  {suggestion.feedback_value === 0 && suggestion.suggested_expected_answer && (
                    <span className="ml-2 text-xs font-normal text-indigo-500">AI-drafted criteria</span>
                  )}
                </label>
                {suggestion.feedback_value === 0 && (
                  <button
                    type="button"
                    onClick={handleRegenerate}
                    disabled={regenerating}
                    className="text-xs px-2 py-1 rounded-md text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 disabled:opacity-50"
                  >
                    {regenerating ? "Regenerating..." : "Regenerate criteria"}
                  </button>
                )}
              </div>
              {suggestion.feedback_value === 0 && suggestion.suggested_expected_answer && (
                <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">
                  These are acceptance criteria, not a verified answer. Edit or replace them
                  with the real expected response if you have one.
                </p>
              )}
              <textarea
                value={form.expected_answer}
                onChange={(e) => setForm({ ...form, expected_answer: e.target.value })}
                rows={4}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                placeholder="(optional)"
              />
            </div>

            {suggestion.expected_sources && suggestion.expected_sources.length > 0 && (
              <div>
                <label className="block text-sm font-medium mb-1">
                  Expected Sources
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    from retrieval context — edit in Configuration below
                  </span>
                </label>
                <ul className="space-y-1">
                  {suggestion.expected_sources.map((url) => (
                    <li key={url} className="text-xs">
                      <a
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-600 dark:text-indigo-400 hover:underline break-all"
                      >
                        {url}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

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
              onClick={handleSave}
              disabled={saving || creatingDataset || !canSave}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {creatingDataset
                ? "Creating dataset..."
                : saving
                  ? "Adding..."
                  : isCreatingNew
                    ? "Create & Add"
                    : "Add to Dataset"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
