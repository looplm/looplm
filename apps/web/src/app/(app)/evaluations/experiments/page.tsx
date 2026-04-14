"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getExperiments,
  createExperiment,
  updateExperiment,
  deleteExperiment,
  type Experiment,
} from "@/lib/api";

interface ExperimentFormData {
  name: string;
  description: string;
  variables: { key: string; value: string }[];
}

const emptyForm: ExperimentFormData = { name: "", description: "", variables: [{ key: "", value: "" }] };

export default function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ExperimentFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getExperiments();
      setExperiments(data.data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditingId(null);
    setForm(emptyForm);
    setError(null);
    setShowModal(true);
  }

  function openEdit(exp: Experiment) {
    setEditingId(exp.id);
    const vars = Object.entries(exp.variables).map(([key, value]) => ({ key, value }));
    if (vars.length === 0) vars.push({ key: "", value: "" });
    setForm({ name: exp.name, description: exp.description || "", variables: vars });
    setError(null);
    setShowModal(true);
  }

  function addVariable() {
    setForm((f) => ({ ...f, variables: [...f.variables, { key: "", value: "" }] }));
  }

  function removeVariable(index: number) {
    setForm((f) => ({
      ...f,
      variables: f.variables.filter((_, i) => i !== index),
    }));
  }

  function updateVariable(index: number, field: "key" | "value", val: string) {
    setForm((f) => ({
      ...f,
      variables: f.variables.map((v, i) => (i === index ? { ...v, [field]: val } : v)),
    }));
  }

  async function handleSave() {
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const variables: Record<string, string> = {};
      for (const { key, value } of form.variables) {
        if (key.trim()) variables[key.trim()] = value;
      }
      if (editingId) {
        await updateExperiment(editingId, {
          name: form.name,
          description: form.description || undefined,
          variables,
        });
      } else {
        await createExperiment({
          name: form.name,
          description: form.description || undefined,
          variables,
        });
      }
      setShowModal(false);
      await load();
    } catch (err: any) {
      setError(err.message || "Failed to save experiment");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this experiment?")) return;
    try {
      await deleteExperiment(id);
      await load();
    } catch {
      // ignore
    }
  }

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  }

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500 dark:text-slate-400">
          {experiments.length} experiment{experiments.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={openCreate}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-500 transition-colors"
        >
          New Experiment
        </button>
      </div>

      {experiments.length === 0 ? (
        <div className="text-center py-12 text-gray-400 dark:text-slate-500">
          <p className="text-lg font-medium mb-1">No experiments yet</p>
          <p className="text-sm">Experiments define variable overrides for eval runs. Create one to get started.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {experiments.map((exp) => (
            <div
              key={exp.id}
              className="flex items-center gap-4 px-4 py-3 rounded-xl bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm truncate">{exp.name}</p>
                {exp.description && (
                  <p className="text-xs text-gray-500 dark:text-slate-400 truncate mt-0.5">{exp.description}</p>
                )}
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {Object.entries(exp.variables).map(([key, value]) => (
                    <span
                      key={key}
                      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300"
                    >
                      {key}={value.length > 20 ? value.slice(0, 20) + "..." : value}
                    </span>
                  ))}
                  {Object.keys(exp.variables).length === 0 && (
                    <span className="text-[10px] text-gray-400 dark:text-slate-500">No variables</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => openEdit(exp)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                  title="Edit"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                  </svg>
                </button>
                <button
                  onClick={() => handleDelete(exp.id)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                  title="Delete"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setShowModal(false)} />
          <div className="relative bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-lg mx-4 p-6">
            <h2 className="text-lg font-semibold mb-4">
              {editingId ? "Edit Experiment" : "New Experiment"}
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. No Filters"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Optional description"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium">Variables</label>
                  <button
                    onClick={addVariable}
                    className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                  >
                    + Add variable
                  </button>
                </div>
                <div className="space-y-2">
                  {form.variables.map((v, i) => (
                    <div key={i} className="flex gap-2 items-center">
                      <input
                        type="text"
                        value={v.key}
                        onChange={(e) => updateVariable(i, "key", e.target.value)}
                        placeholder="key"
                        className="flex-1 px-2.5 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono"
                      />
                      <span className="text-gray-400">=</span>
                      <input
                        type="text"
                        value={v.value}
                        onChange={(e) => updateVariable(i, "value", e.target.value)}
                        placeholder="value"
                        className="flex-1 px-2.5 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono"
                      />
                      {form.variables.length > 1 && (
                        <button
                          onClick={() => removeVariable(i)}
                          className="text-gray-400 hover:text-red-500 p-1"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                          </svg>
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1.5">
                  Variables are injected into request templates. Use <code className="bg-gray-100 dark:bg-slate-800 px-1 rounded">filter_mode</code>, <code className="bg-gray-100 dark:bg-slate-800 px-1 rounded">team_filter</code>, or any custom key.
                </p>
              </div>
            </div>

            {error && (
              <p className="text-sm text-red-500 mt-3">{error}</p>
            )}

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowModal(false)}
                className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.name.trim()}
                className="px-4 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
              >
                {saving ? "Saving..." : editingId ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
