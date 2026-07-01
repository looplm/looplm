"use client";

import { useEffect, useState } from "react";
import type { EvaluatorItem } from "@/lib/api";
import {
  PillGroup,
  SectionHeader,
  TYPE_PILL_STYLES,
  SOURCE_PILL_STYLES,
  RELEVANCE_PILL_STYLES,
  CHECK_TYPE_PILL_STYLES,
  CATEGORY_PILL_STYLES,
} from "./evaluator-badges";
import {
  type EvaluatorFormData,
  type StructuredConfig,
  EMPTY_FORM,
  EMPTY_STRUCTURED,
  parseStructuredConfig,
  mergeStructuredIntoRaw,
  slugifyId,
} from "./evaluator-modal-utils";

export type { EvaluatorFormData } from "./evaluator-modal-utils";
export { EMPTY_FORM } from "./evaluator-modal-utils";

const inputClass =
  "w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm";

export function EvaluatorModal({
  editingEvaluator,
  defaultCategory = "",
  onClose,
  onSave,
}: {
  editingEvaluator: EvaluatorItem | null;
  // Focus a newly-created evaluator starts with ("" = unassigned; optional).
  defaultCategory?: string;
  onClose: () => void;
  onSave: (data: EvaluatorFormData) => void;
}) {
  const [form, setForm] = useState<EvaluatorFormData>(EMPTY_FORM);
  const [structured, setStructured] = useState<StructuredConfig>(EMPTY_STRUCTURED);
  const [showConfig, setShowConfig] = useState(false);

  useEffect(() => {
    if (editingEvaluator) {
      const configStr = JSON.stringify(editingEvaluator.config, null, 2);
      setForm({
        name: editingEvaluator.name,
        display_name: editingEvaluator.display_name || "",
        type: editingEvaluator.type,
        source: editingEvaluator.source || "custom",
        category: editingEvaluator.category || "",
        description: editingEvaluator.description || "",
        relevance: editingEvaluator.relevance,
        affects_pass: editingEvaluator.affects_pass,
        config: configStr,
      });
      const configObj = (editingEvaluator.config as Record<string, unknown>) || {};
      setStructured(parseStructuredConfig(configObj));
      const cfg = JSON.stringify(editingEvaluator.config);
      setShowConfig(cfg !== "{}" && cfg !== "null");
    } else {
      setForm({ ...EMPTY_FORM, category: defaultCategory });
      setStructured(EMPTY_STRUCTURED);
      setShowConfig(false);
    }
  }, [editingEvaluator, defaultCategory]);

  const handleTypeChange = (newType: string) => {
    setForm({ ...form, type: newType });
    setStructured((prev) => {
      const next = { ...prev };
      if (newType === "deterministic") {
        next.prompt_template = "";
        next.model = "";
      }
      if (newType === "llm_judge") {
        next.check_type = "contains_urls";
        next.pattern = "";
        next.expected_strings = "";
      }
      return next;
    });
  };

  const handleSave = () => {
    const mergedConfig = mergeStructuredIntoRaw(form.config, structured, form.type);
    onSave({ ...form, config: mergedConfig });
  };

  const showLlm = form.type === "llm_judge" || form.type === "hybrid";
  const showDeterministic = form.type === "deterministic" || form.type === "hybrid";

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-md z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-5xl max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">
              {editingEvaluator ? "Edit Evaluator" : "New Evaluator"}
            </h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200">
              &times;
            </button>
          </div>
          <div className="p-4 space-y-5">
            {/* Identity Section */}
            <div className="space-y-3">
              <SectionHeader icon="&#9868;" label="Identity" />
              <div>
                <label className="block text-sm font-medium mb-1">Display Name</label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      display_name: e.target.value,
                      // The id is derived from the display name on create; fixed once saved.
                      name: editingEvaluator ? f.name : slugifyId(e.target.value),
                    }))
                  }
                  className={inputClass}
                  placeholder="e.g. Faithfulness"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">ID</label>
                <input
                  type="text"
                  value={form.name}
                  disabled
                  className={`${inputClass} font-mono opacity-60`}
                  placeholder="auto-generated from the display name"
                />
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                  {editingEvaluator
                    ? "The identifier can't be changed."
                    : "Auto-generated from the display name — the stable identifier used in results."}
                </p>
              </div>
            </div>

            <hr className="border-gray-100 dark:border-slate-800" />

            {/* Classification Section */}
            <div className="space-y-3">
              <SectionHeader icon="&#9783;" label="Classification" />
              <div>
                <label className="block text-sm font-medium mb-2">
                  Pipeline focus <span className="font-normal text-gray-400 dark:text-slate-500">(optional)</span>
                </label>
                <PillGroup
                  options={[
                    { value: "retrieval", label: "Retrieval" },
                    { value: "generation", label: "Generation" },
                  ]}
                  value={form.category}
                  onChange={(v) => setForm({ ...form, category: form.category === v ? "" : v })}
                  styles={CATEGORY_PILL_STYLES}
                />
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                  Which part of the RAG pipeline this evaluator assesses — retrieval (was the right
                  context fetched) or generation (how the model used it). Click again to clear; leave
                  unset if it applies to neither.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Type</label>
                  <PillGroup
                    options={[
                      { value: "llm_judge", label: "LLM Judge" },
                      { value: "deterministic", label: "Code" },
                      { value: "hybrid", label: "Hybrid" },
                    ]}
                    value={form.type}
                    onChange={handleTypeChange}
                    styles={TYPE_PILL_STYLES}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Source</label>
                  <PillGroup
                    options={[
                      { value: "custom", label: "Custom" },
                      { value: "ragas", label: "RAGAS" },
                    ]}
                    value={form.source}
                    onChange={(v) => setForm({ ...form, source: v })}
                    styles={SOURCE_PILL_STYLES}
                  />
                </div>
              </div>
            </div>

            <hr className="border-gray-100 dark:border-slate-800" />

            {/* Behavior Section */}
            <div className="space-y-3">
              <SectionHeader icon="&#9881;" label="Behavior" />
              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className={inputClass}
                  rows={3}
                  placeholder="What does this evaluator check?"
                />
              </div>
              <div className="flex gap-4 items-start">
                <div className="flex-1">
                  <label className="block text-sm font-medium mb-2">Relevance</label>
                  <PillGroup
                    options={[
                      { value: "core", label: "Core" },
                      { value: "important", label: "Important" },
                      { value: "minor", label: "Minor" },
                    ]}
                    value={form.relevance}
                    onChange={(v) => setForm({ ...form, relevance: v })}
                    styles={RELEVANCE_PILL_STYLES}
                  />
                </div>
                <div className="pt-6">
                  <label className="flex items-center gap-3 text-sm cursor-pointer select-none">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={form.affects_pass}
                      onClick={() => setForm({ ...form, affects_pass: !form.affects_pass })}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                        form.affects_pass ? "bg-indigo-600" : "bg-gray-300 dark:bg-slate-600"
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                          form.affects_pass ? "translate-x-4.5" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                    Affects Pass/Fail
                  </label>
                </div>
              </div>
            </div>

            {/* Configuration Section */}
            {(showDeterministic || showLlm) && (
              <>
                <hr className="border-gray-100 dark:border-slate-800" />
                <div className="space-y-4">
                  <SectionHeader icon="&#9881;" label="Configuration" />

                  {/* Deterministic section (shown first for hybrid — matches execution order) */}
                  {showDeterministic && (
                    <div className="space-y-3">
                      {form.type === "hybrid" && (
                        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wide">
                          Code Check
                        </p>
                      )}
                      <div>
                        <label className="block text-sm font-medium mb-2">Check Type</label>
                        <PillGroup
                          options={[
                            { value: "contains_urls", label: "Contains URLs" },
                            { value: "contains_sources", label: "Contains Sources" },
                            { value: "regex_match", label: "Regex Match" },
                            { value: "string_contains", label: "String Contains" },
                            { value: "image_missing", label: "Image Missing" },
                            { value: "image_ordering", label: "Image Ordering" },
                            { value: "length_threshold", label: "Length Threshold" },
                          ]}
                          value={structured.check_type}
                          onChange={(v) => setStructured({ ...structured, check_type: v })}
                          styles={CHECK_TYPE_PILL_STYLES}
                        />
                      </div>
                      {structured.check_type === "regex_match" && (
                        <div>
                          <label className="block text-sm font-medium mb-1">Pattern</label>
                          <input
                            type="text"
                            value={structured.pattern}
                            onChange={(e) => setStructured({ ...structured, pattern: e.target.value })}
                            className={`${inputClass} font-mono`}
                            placeholder="e.g. https?://\\S+"
                          />
                        </div>
                      )}
                      {structured.check_type === "string_contains" && (
                        <div>
                          <label className="block text-sm font-medium mb-1">Expected Strings</label>
                          <textarea
                            value={structured.expected_strings}
                            onChange={(e) => setStructured({ ...structured, expected_strings: e.target.value })}
                            className={`${inputClass} font-mono`}
                            rows={3}
                            placeholder="One string per line"
                          />
                        </div>
                      )}
                      {(structured.check_type === "contains_urls" || structured.check_type === "contains_sources") && (
                        <p className="text-xs text-gray-400 dark:text-slate-500 italic">
                          Uses expected data from test cases.
                        </p>
                      )}
                      {(structured.check_type === "image_missing" || structured.check_type === "image_ordering") && (
                        <p className="text-xs text-gray-400 dark:text-slate-500 italic">
                          Checks IMAGE_X references in the API response automatically.
                        </p>
                      )}
                      {structured.check_type === "length_threshold" && (
                        <p className="text-xs text-gray-400 dark:text-slate-500 italic">
                          Uses per-test-case max_answer_length, falling back to default_max_length in config. Set in the Advanced JSON config below.
                        </p>
                      )}
                    </div>
                  )}

                  {/* LLM section */}
                  {showLlm && (
                    <div className="space-y-3">
                      {form.type === "hybrid" && (
                        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wide mt-2">
                          LLM Fallback
                        </p>
                      )}
                      <div>
                        <label className="block text-sm font-medium mb-1">Prompt Template</label>
                        <textarea
                          value={structured.prompt_template}
                          onChange={(e) => setStructured({ ...structured, prompt_template: e.target.value })}
                          className={`${inputClass} font-mono`}
                          rows={6}
                          placeholder="Evaluate the following response..."
                        />
                        <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                          Available variables: <code className="text-xs">{"{{input}}"}</code>, <code className="text-xs">{"{{output}}"}</code>, <code className="text-xs">{"{{expected_output}}"}</code>, <code className="text-xs">{"{{context}}"}</code>
                        </p>
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-1">Model</label>
                        <input
                          type="text"
                          value={structured.model}
                          onChange={(e) => setStructured({ ...structured, model: e.target.value })}
                          className={inputClass}
                          placeholder="Leave empty for default"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}

            <hr className="border-gray-100 dark:border-slate-800" />

            {/* Advanced Section */}
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setShowConfig(!showConfig)}
                className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors"
              >
                <span className="text-sm">{showConfig ? "\u25BE" : "\u25B8"}</span>
                <span className="text-sm">&#123;&#125;</span>
                Advanced
              </button>
              {showConfig && (
                <div>
                  <label className="block text-sm font-medium mb-1">Config (JSON)</label>
                  <textarea
                    value={form.config}
                    onChange={(e) => setForm({ ...form, config: e.target.value })}
                    className={`${inputClass} font-mono`}
                    rows={4}
                    placeholder="{}"
                  />
                  <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                    Fields above take precedence over matching keys here.
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!form.name.trim()}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {editingEvaluator ? "Save Changes" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
