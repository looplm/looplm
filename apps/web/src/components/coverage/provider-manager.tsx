"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  createIndexProvider,
  deleteIndexProvider,
  getIndexProviders,
  testIndexProvider,
  updateIndexProvider,
  type IndexProvider,
} from "@/lib/api";
import { ConfirmModal } from "@/components/confirm-modal";

// Only azure_search is implemented today; the backend enum reserves the rest.
const PROVIDER_TYPES = [{ value: "azure_search", label: "Azure AI Search" }];

interface FormState {
  id: string | null;
  type: string;
  name: string;
  endpoint: string;
  apiKey: string;
  indexName: string;
}

const EMPTY_FORM: FormState = {
  id: null,
  type: "azure_search",
  name: "",
  endpoint: "",
  apiKey: "",
  indexName: "",
};

export function ProviderManager({
  open,
  canEdit,
  onClose,
  onChanged,
}: {
  open: boolean;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [providers, setProviders] = useState<IndexProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const { data } = await getIndexProviders();
      setProviders(data);
    } catch (err) {
      toast.error("Failed to load providers", { description: String(err) });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) load();
  }, [open]);

  if (!open) return null;

  function openCreate() {
    setForm({ ...EMPTY_FORM });
  }

  function openEdit(p: IndexProvider) {
    setForm({
      id: p.id,
      type: p.type,
      name: p.name,
      endpoint: p.base_url || "",
      apiKey: "",
      indexName: String((p.config as { index_name?: string })?.index_name || ""),
      // apiKey left blank on edit — only sent if the user types a new one
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const config = { index_name: form.indexName.trim() };
      if (form.id) {
        await updateIndexProvider(form.id, {
          name: form.name.trim(),
          base_url: form.endpoint.trim(),
          config,
          ...(form.apiKey ? { api_key: form.apiKey } : {}),
        });
        toast.success("Provider updated");
      } else {
        await createIndexProvider({
          type: form.type,
          name: form.name.trim(),
          api_key: form.apiKey,
          base_url: form.endpoint.trim(),
          config,
        });
        toast.success("Provider created");
      }
      setForm(null);
      await load();
      onChanged();
    } catch (err) {
      toast.error("Save failed", { description: String(err) });
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(id: string) {
    setTesting(id);
    try {
      const res = await testIndexProvider(id);
      if (res.ok) {
        toast.success("Connection OK", {
          description: `${(res.document_count ?? 0).toLocaleString()} documents indexed`,
        });
      } else {
        toast.error("Connection failed", { description: res.error || "Unknown error" });
      }
    } catch (err) {
      toast.error("Connection failed", { description: String(err) });
    } finally {
      setTesting(null);
    }
  }

  async function handleDelete() {
    if (!deleteId) return;
    const id = deleteId;
    setDeleteId(null);
    try {
      await deleteIndexProvider(id);
      toast.success("Provider deleted");
      await load();
      onChanged();
    } catch (err) {
      toast.error("Delete failed", { description: String(err) });
    }
  }

  const inputCls =
    "w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm";

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800">
            <h2 className="text-lg font-semibold">Index providers</h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-slate-200"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="p-4 space-y-3">
            {loading ? (
              <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>
            ) : providers.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-slate-400">
                No providers yet. Add one to connect a retrieval index.
              </p>
            ) : (
              providers.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between p-3 rounded-lg border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{p.name}</p>
                    <p className="text-xs text-gray-400 dark:text-slate-500 truncate">
                      {p.type} · {String((p.config as { index_name?: string })?.index_name || "—")} ·{" "}
                      {p.base_url || "—"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => handleTest(p.id)}
                      disabled={testing === p.id}
                      className="px-2.5 py-1.5 rounded-lg text-xs bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50"
                    >
                      {testing === p.id ? "Testing…" : "Test"}
                    </button>
                    {canEdit && (
                      <>
                        <button
                          onClick={() => openEdit(p)}
                          className="px-2.5 py-1.5 rounded-lg text-xs bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => setDeleteId(p.id)}
                          className="px-2.5 py-1.5 rounded-lg text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}

            {canEdit && !form && (
              <button
                onClick={openCreate}
                className="px-3 py-1.5 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500"
              >
                + Add provider
              </button>
            )}

            {form && (
              <form
                onSubmit={handleSubmit}
                className="mt-2 p-4 rounded-lg border border-gray-200 dark:border-slate-700 space-y-3"
              >
                <div>
                  <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">Type</label>
                  <select
                    value={form.type}
                    onChange={(e) => setForm({ ...form, type: e.target.value })}
                    disabled={!!form.id}
                    className={inputCls}
                  >
                    {PROVIDER_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">Name</label>
                  <input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="e.g. Klara prod index"
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">
                    Endpoint
                  </label>
                  <input
                    value={form.endpoint}
                    onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
                    placeholder="https://<service>.search.windows.net"
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">
                    Index name
                  </label>
                  <input
                    value={form.indexName}
                    onChange={(e) => setForm({ ...form, indexName: e.target.value })}
                    placeholder="prod-index"
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">
                    API key {form.id && <span className="text-gray-400">(leave blank to keep)</span>}
                  </label>
                  <input
                    type="password"
                    value={form.apiKey}
                    onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                    placeholder={form.id ? "••••••••" : "admin or query key"}
                    required={!form.id}
                    className={inputCls}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setForm(null)}
                    className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="px-3 py-1.5 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
                  >
                    {saving ? "Saving…" : form.id ? "Save" : "Create"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>

      {deleteId && (
        <ConfirmModal
          title="Delete provider?"
          message="This removes the connection (and its coverage runs). The indexed data itself is untouched."
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleDelete}
          onCancel={() => setDeleteId(null)}
        />
      )}
    </>
  );
}
