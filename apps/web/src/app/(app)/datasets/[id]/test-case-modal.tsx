"use client";

import { useEffect, useState } from "react";
import type { TestCaseItem } from "@/lib/api";
import { ConfigEditor } from "@/components/config-editor";
import { isNoRetrievalExpected } from "@/lib/test-case-tags";

export interface TestCaseFormData {
  test_id: string;
  prompt: string;
  expected_answer: string;
  config_json: string;
  no_retrieval: boolean;
  reactivate?: boolean;
}

const KNOWN_CONFIG_KEYS = [
  "team_filter", "tag_filter", "expected_sources",
  "expected_page_urls", "expected_source_types",
  "max_answer_length", "context_filters",
] as const;

function isNonEmpty(val: unknown): boolean {
  if (val === null || val === undefined) return false;
  if (Array.isArray(val)) return val.length > 0;
  if (typeof val === "object") return Object.keys(val as object).length > 0;
  return true;
}

export function emptyForm(): TestCaseFormData {
  return {
    test_id: "",
    prompt: "",
    expected_answer: "",
    config_json: "",
    no_retrieval: false,
  };
}

export function formFromTestCase(tc: TestCaseItem): TestCaseFormData {
  const config: Record<string, unknown> = {};
  for (const key of KNOWN_CONFIG_KEYS) {
    const val = tc[key];
    if (isNonEmpty(val)) config[key] = val;
  }
  // Merge arbitrary metadata on top
  if (tc.metadata && Object.keys(tc.metadata).length > 0) {
    Object.assign(config, tc.metadata);
  }
  return {
    test_id: tc.test_id,
    prompt: tc.prompt,
    expected_answer: tc.expected_answer || "",
    config_json: Object.keys(config).length > 0
      ? JSON.stringify(config, null, 2)
      : "",
    no_retrieval: isNoRetrievalExpected(tc.tags),
  };
}

export function TestCaseModal({
  editingCase,
  onClose,
  onSave,
  saving,
}: {
  editingCase: TestCaseItem | null;
  onClose: () => void;
  onSave: (data: TestCaseFormData) => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<TestCaseFormData>(emptyForm);
  const [configValid, setConfigValid] = useState(true);

  useEffect(() => {
    setForm(editingCase ? formFromTestCase(editingCase) : emptyForm());
    setConfigValid(true);
  }, [editingCase]);

  const isCreate = !editingCase;
  const canSave = form.test_id.trim() && form.prompt.trim() && configValid;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800 shrink-0">
            <h2 className="text-lg font-semibold">
              {isCreate ? "New Test Case" : "Edit Test Case"}
            </h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200">
              &times;
            </button>
          </div>

          {/* Body */}
          <div className="p-4 space-y-4 overflow-y-auto flex-1">
            {/* Needs-work banner */}
            {editingCase?.status === "needs_work" && (
              <div className="rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/20 p-3 space-y-2">
                <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                  This test case is marked as needing work and is excluded from eval runs.
                </p>
                {editingCase.status_note && (
                  <p className="text-sm text-amber-700 dark:text-amber-400">{editingCase.status_note}</p>
                )}
                <label className="flex items-center gap-2 text-sm text-amber-800 dark:text-amber-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!form.reactivate}
                    onChange={(e) => setForm({ ...form, reactivate: e.target.checked })}
                    className="rounded border-amber-300 dark:border-amber-700"
                  />
                  Mark as fixed when saving (include in eval runs again)
                </label>
              </div>
            )}

            {/* Test ID */}
            <div>
              <label className="block text-sm font-medium mb-1">Test ID</label>
              <input
                type="text"
                value={form.test_id}
                onChange={(e) => setForm({ ...form, test_id: e.target.value })}
                disabled={!isCreate}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm disabled:opacity-50"
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
                placeholder="User question"
              />
            </div>

            {/* Expected Answer */}
            <div>
              <label className="block text-sm font-medium mb-1">Expected Answer</label>
              <textarea
                value={form.expected_answer}
                onChange={(e) => setForm({ ...form, expected_answer: e.target.value })}
                rows={4}
                className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
                placeholder="(optional)"
              />
            </div>

            {/* Negative case flag */}
            <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3">
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.no_retrieval}
                  onChange={(e) => setForm({ ...form, no_retrieval: e.target.checked })}
                  className="mt-0.5 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                />
                <span>
                  <span className="block font-medium">No retrieval expected (negative case)</span>
                  <span className="block text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                    The query intentionally has no relevant documents, e.g. a UI command.
                    Excluded from retrieval metrics; the expected-URL sync and the AI judge
                    skip it. Expected page URLs are cleared on save.
                  </span>
                </span>
              </label>
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
              onClick={() => onSave(form)}
              disabled={saving || !canSave}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {saving ? "Saving..." : isCreate ? "Create" : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
