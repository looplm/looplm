"use client";

import { useEffect, useState } from "react";
import type { FeedbackEvaluatorConfig } from "@/lib/api";

const inputClass =
  "w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm";

export function FeedbackEvaluatorModal({
  config,
  onClose,
  onSave,
  saving,
  reevaluate,
  onReevaluateChange,
}: {
  config: FeedbackEvaluatorConfig;
  onClose: () => void;
  onSave: (data: { prompt: string; verdicts: string[]; default_verdict: string; model: string | null }) => void;
  saving?: boolean;
  reevaluate: boolean;
  onReevaluateChange: (value: boolean) => void;
}) {
  const [prompt, setPrompt] = useState(config.prompt);
  const [verdicts, setVerdicts] = useState<string[]>(config.verdicts);
  const [defaultVerdict, setDefaultVerdict] = useState(config.default_verdict);
  const [model, setModel] = useState(config.model || "");
  const [newVerdict, setNewVerdict] = useState("");

  useEffect(() => {
    setPrompt(config.prompt);
    setVerdicts(config.verdicts);
    setDefaultVerdict(config.default_verdict);
    setModel(config.model || "");
  }, [config]);

  function addVerdict() {
    const v = newVerdict.trim().toLowerCase().replace(/\s+/g, "_");
    if (v && !verdicts.includes(v)) {
      setVerdicts([...verdicts, v]);
      setNewVerdict("");
    }
  }

  function removeVerdict(v: string) {
    const updated = verdicts.filter((x) => x !== v);
    if (updated.length === 0) return;
    setVerdicts(updated);
    if (defaultVerdict === v) {
      setDefaultVerdict(updated[0]);
    }
  }

  function handleSave() {
    onSave({
      prompt,
      verdicts,
      default_verdict: defaultVerdict,
      model: model.trim() || null,
    });
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col z-[70]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold">Feedback Evaluator Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-300 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* System Prompt */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5">
              System Prompt
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={10}
              className={`${inputClass} font-mono text-xs leading-relaxed`}
              placeholder="Describe how the LLM should evaluate feedback quality..."
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              The LLM receives this as the system prompt when evaluating feedback items. Reference the verdict names below in your prompt.
            </p>
          </div>

          {/* Verdicts */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5">
              Verdicts
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {verdicts.map((v) => (
                <span
                  key={v}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gray-100 dark:bg-slate-800 text-sm font-medium text-gray-700 dark:text-slate-300"
                >
                  {v}
                  {verdicts.length > 1 && (
                    <button
                      onClick={() => removeVerdict(v)}
                      className="text-gray-400 hover:text-red-500 text-xs leading-none ml-0.5"
                    >
                      &times;
                    </button>
                  )}
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newVerdict}
                onChange={(e) => setNewVerdict(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addVerdict())}
                placeholder="Add verdict..."
                className={`${inputClass} flex-1`}
              />
              <button
                onClick={addVerdict}
                disabled={!newVerdict.trim()}
                className="px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
              >
                Add
              </button>
            </div>
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Each feedback item will be classified into one of these verdicts by the LLM.
            </p>
          </div>

          {/* Default Verdict */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5">
              Default Verdict
            </label>
            <select
              value={defaultVerdict}
              onChange={(e) => setDefaultVerdict(e.target.value)}
              className={inputClass}
            >
              {verdicts.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Used when the LLM returns a verdict not in the list above.
            </p>
          </div>

          {/* Model */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5">
              Model <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Leave empty to use default"
              className={inputClass}
            />
          </div>

          {/* Re-evaluate */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={reevaluate}
              onChange={(e) => onReevaluateChange(e.target.checked)}
              className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm font-medium text-gray-700 dark:text-slate-300">Re-evaluate existing verdicts</span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-slate-800">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !prompt.trim() || verdicts.length === 0}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
