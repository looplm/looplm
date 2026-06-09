"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  createDataset,
  createTestCase,
  type CoverageSuggestion,
  type TestCaseCreateBody,
  type TestDatasetItem,
} from "@/lib/api";

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "value";
}

function suggestionToBody(s: CoverageSuggestion, index: number): TestCaseCreateBody {
  return {
    test_id: `coverage-${slugify(s.partition_value)}-${index + 1}`,
    prompt: s.prompt,
    expected_answer: s.acceptance_criteria || undefined,
    tag_filter: s.tag_filter || [],
    team_filter: s.team_filter || [],
    expected_source_types: s.expected_source_types || [],
    context_filters: s.context_filters || {},
    has_summary: false,
    metadata: { source: "rag-coverage", partition_value: s.partition_value },
  };
}

function Chips({ label, values }: { label: string; values: string[] }) {
  if (!values || values.length === 0) return null;
  return (
    <span className="inline-flex items-center gap-1 mr-2">
      <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
        {label}
      </span>
      {values.map((v) => (
        <span
          key={v}
          className="inline-block px-1.5 py-0.5 rounded text-[11px] bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300"
        >
          {v}
        </span>
      ))}
    </span>
  );
}

export function SuggestionList({
  suggestions,
  datasets,
  canEdit,
  onDatasetsChanged,
}: {
  suggestions: CoverageSuggestion[];
  datasets: TestDatasetItem[];
  canEdit: boolean;
  onDatasetsChanged: () => void;
}) {
  const [accepting, setAccepting] = useState<{ suggestion: CoverageSuggestion; index: number } | null>(
    null,
  );
  const [acceptedKeys, setAcceptedKeys] = useState<Set<number>>(new Set());

  if (suggestions.length === 0) return null;

  // Group by partition value for readability.
  const groups = new Map<string, { s: CoverageSuggestion; index: number }[]>();
  suggestions.forEach((s, index) => {
    const arr = groups.get(s.partition_value) || [];
    arr.push({ s, index });
    groups.set(s.partition_value, arr);
  });

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">
        Suggested eval questions{" "}
        <span className="text-sm font-normal text-gray-400 dark:text-slate-500">
          ({suggestions.length} for {groups.size} gap{groups.size === 1 ? "" : "s"})
        </span>
      </h2>

      {[...groups.entries()].map(([value, items]) => (
        <div key={value} className="rounded-xl border border-gray-100 dark:border-slate-800 p-4">
          <p className="text-sm font-medium mb-3">
            Gap: <span className="text-indigo-600 dark:text-indigo-400">{value}</span>
          </p>
          <div className="space-y-3">
            {items.map(({ s, index }) => (
              <div
                key={index}
                className="p-3 rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-100 dark:border-slate-800"
              >
                <p className="text-sm font-medium">{s.prompt}</p>
                {s.acceptance_criteria && (
                  <p className="mt-1 text-xs text-gray-500 dark:text-slate-400 whitespace-pre-wrap">
                    {s.acceptance_criteria}
                  </p>
                )}
                <div className="mt-2 flex items-center flex-wrap gap-y-1">
                  <Chips label="tags" values={s.tag_filter} />
                  <Chips label="team" values={s.team_filter} />
                  <Chips label="source" values={s.expected_source_types} />
                </div>
                <div className="mt-2 flex justify-end">
                  {acceptedKeys.has(index) ? (
                    <span className="text-xs text-green-600 dark:text-green-400">✓ Added</span>
                  ) : (
                    <button
                      onClick={() => setAccepting({ suggestion: s, index })}
                      disabled={!canEdit}
                      className="px-2.5 py-1.5 rounded-lg text-xs bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
                      title={canEdit ? undefined : "Read-only access"}
                    >
                      Add to dataset
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {accepting && (
        <AcceptModal
          suggestion={accepting.suggestion}
          index={accepting.index}
          datasets={datasets}
          onClose={() => setAccepting(null)}
          onAccepted={(idx) => {
            setAcceptedKeys((prev) => new Set(prev).add(idx));
            setAccepting(null);
            onDatasetsChanged();
          }}
        />
      )}
    </div>
  );
}

function AcceptModal({
  suggestion,
  index,
  datasets,
  onClose,
  onAccepted,
}: {
  suggestion: CoverageSuggestion;
  index: number;
  datasets: TestDatasetItem[];
  onClose: () => void;
  onAccepted: (index: number) => void;
}) {
  const [datasetId, setDatasetId] = useState<string>(datasets[0]?.id || "__new__");
  const [newName, setNewName] = useState("RAG coverage");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      let targetId = datasetId;
      if (datasetId === "__new__") {
        const ds = await createDataset({ name: newName.trim() || "RAG coverage" });
        targetId = ds.id;
      }
      await createTestCase(targetId, suggestionToBody(suggestion, index));
      toast.success("Test case added");
      onAccepted(index);
    } catch (err) {
      toast.error("Failed to add", { description: String(err) });
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm";

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-lg">
          <div className="p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">Add to dataset</h2>
          </div>
          <div className="p-4 space-y-3">
            <div>
              <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">Prompt</label>
              <p className="text-sm">{suggestion.prompt}</p>
            </div>
            <div>
              <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">Dataset</label>
              <select
                value={datasetId}
                onChange={(e) => setDatasetId(e.target.value)}
                className={inputCls}
              >
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
                <option value="__new__">+ New dataset…</option>
              </select>
            </div>
            {datasetId === "__new__" && (
              <div>
                <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">
                  New dataset name
                </label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} className={inputCls} />
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 p-4 border-t border-gray-100 dark:border-slate-800">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50"
            >
              {saving ? "Adding…" : "Add test case"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
