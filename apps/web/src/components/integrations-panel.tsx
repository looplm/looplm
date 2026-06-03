"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { getIntegrations, createIntegration, updateIntegration, deleteIntegration, triggerSync, stopSync, getImportHistory, type Integration, type JsonImportItem } from "@/lib/api";
import { IntegrationCard } from "@/components/integration-card";
import { LooplmTracingCard } from "@/components/ingest-keys-panel";
import { ImportHistoryTable } from "@/components/import-history-table";

const emptyForm = { type: "langfuse", name: "", api_key: "", public_key: "", base_url: "", project: "" };

export default function IntegrationsPanel() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [customSinceDate, setCustomSinceDate] = useState<Record<string, string>>({});
  const [updateExisting, setUpdateExisting] = useState<Record<string, boolean>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevStatusRef = useRef<Record<string, string>>({});

  // Import history state
  const [imports, setImports] = useState<JsonImportItem[]>([]);
  const [importFilter, setImportFilter] = useState<string>("all");
  const [importPage, setImportPage] = useState(1);
  const [importTotalPages, setImportTotalPages] = useState(0);

  const load = () => getIntegrations().then((r) => {
    const prev = prevStatusRef.current;
    for (const integration of r.data) {
      if (integration.sync_status === "error" && prev[integration.id] && prev[integration.id] !== "error") {
        toast.error(`Sync failed for "${integration.name}"`, {
          description: integration.last_sync_error || "An unknown error occurred",
          duration: 10000,
        });
      }
      prev[integration.id] = integration.sync_status;
    }
    // Filter out json_file integrations
    setIntegrations(r.data.filter((i) => i.type !== "json_file"));
  }).catch((e) => setError(e.message));

  const loadImports = () => {
    const params: Record<string, string> = { page: String(importPage), per_page: "20" };
    if (importFilter !== "all") params.entity_type = importFilter;
    getImportHistory(params).then((r) => {
      setImports(r.data);
      setImportTotalPages(r.pagination.total_pages);
    }).catch(() => {});
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { loadImports(); }, [importPage, importFilter]);

  // Poll while any integration is syncing
  useEffect(() => {
    const isSyncing = integrations.some((i) => i.sync_status === "syncing");
    if (isSyncing && !pollRef.current) {
      pollRef.current = setInterval(load, 3000);
    } else if (!isSyncing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [integrations]);

  const openCreateForm = () => {
    setEditingId(null);
    setForm(emptyForm);
    setShowForm(true);
  };

  const openEditForm = (i: Integration) => {
    setEditingId(i.id);
    setForm({
      type: i.type,
      name: i.name,
      api_key: "",
      public_key: "",
      base_url: i.base_url || "",
      project: (i.config?.project as string) || "",
    });
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingId) {
        const existing = integrations.find((i) => i.id === editingId);
        const config: Record<string, unknown> = { ...existing?.config };
        if (form.type === "langsmith") {
          config.project = form.project || undefined;
        }
        if (form.type === "langfuse" && form.public_key) {
          config.public_key = form.public_key;
        }
        await updateIntegration(editingId, {
          name: form.name,
          ...(form.api_key ? { api_key: form.api_key } : {}),
          base_url: form.base_url || undefined,
          config,
        });
      } else {
        const config: Record<string, unknown> = {};
        if (form.type === "langsmith" && form.project) {
          config.project = form.project;
        }
        if (form.type === "langfuse" && form.public_key) {
          config.public_key = form.public_key;
        }
        await createIntegration({
          type: form.type,
          name: form.name,
          api_key: form.api_key,
          base_url: form.base_url || undefined,
          config,
        });
      }
      closeForm();
      load();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleSync = async (id: string, since?: string) => {
    const update = updateExisting[id] ?? true;
    try {
      await triggerSync(id, (since || update) ? { since, update_existing: update || undefined } : undefined);
      load();
    } catch (err: any) {
      toast.error("Failed to start sync", { description: err.message });
    }
  };

  const handleSyncPreset = (id: string, days: number | null) => {
    if (days === null) {
      handleSync(id);
    } else {
      const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
      handleSync(id, since);
    }
  };

  const handleStopSync = async (id: string) => {
    try {
      await stopSync(id);
      load();
    } catch (err: any) {
      toast.error("Failed to stop sync", { description: err.message });
    }
  };

  const handleDelete = async (i: Integration) => {
    if (!confirm(`Delete "${i.name}"? All synced traces from this integration will be permanently removed.`)) return;
    try {
      await deleteIntegration(i.id);
      load();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-lg font-semibold">Integrations</h2>
        <button
          onClick={openCreateForm}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white"
        >
          + Add Integration
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 underline">dismiss</button>
        </div>
      )}

      {showForm && (
        <form onSubmit={handleSubmit} className="mb-8 p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 space-y-4">
          <h2 className="text-lg font-semibold">{editingId ? "Edit Integration" : "New Integration"}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Type</label>
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                disabled={!!editingId}
                className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm disabled:opacity-50"
              >
                <option value="langfuse">Langfuse</option>
                <option value="langsmith">LangSmith</option>
                <option value="looplm">LoopLM Tracing (SDK)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Name</label>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
                placeholder="Production Langfuse"
              />
            </div>
            {form.type === "langfuse" && (
              <div>
                <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
                  Public Key{editingId ? " (leave blank to keep current)" : ""}
                </label>
                <input
                  required={!editingId}
                  type="password"
                  value={form.public_key}
                  onChange={(e) => setForm({ ...form, public_key: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
                  placeholder="pk-lf-..."
                />
              </div>
            )}
            {form.type !== "looplm" && (
              <div>
                <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
                  {form.type === "langfuse" ? "Secret Key" : "API Key"}{editingId ? " (leave blank to keep current)" : ""}
                </label>
                <input
                  required={!editingId}
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
                  placeholder={form.type === "langfuse" ? "sk-lf-..." : ""}
                />
              </div>
            )}
            {form.type !== "looplm" && (
              <div>
                <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Base URL (optional)</label>
                <input
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
                  placeholder="https://cloud.langfuse.com"
                />
              </div>
            )}
            {form.type === "langsmith" && (
              <div>
                <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Project Name (optional)</label>
                <input
                  value={form.project}
                  onChange={(e) => setForm({ ...form, project: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
                  placeholder="default"
                />
              </div>
            )}
          </div>
          <div className="flex gap-3">
            <button type="submit" className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white">
              {editingId ? "Save Changes" : "Create"}
            </button>
            <button type="button" onClick={closeForm} className="px-4 py-2 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg text-sm">
              Cancel
            </button>
          </div>
        </form>
      )}

      {!showForm && integrations.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400 flex flex-col items-center gap-4">
          <p>No integrations configured. Add one to start syncing traces.</p>
          <button
            onClick={openCreateForm}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white transition-colors"
          >
            + Add Integration
          </button>
        </div>
      ) : !showForm && (
        <div className="grid grid-cols-1 gap-6">
          {integrations.map((i) => (
            i.type === "looplm" ? (
              <LooplmTracingCard
                key={i.id}
                integration={i}
                onEdit={openEditForm}
                onDelete={handleDelete}
              />
            ) : (
              <IntegrationCard
                key={i.id}
                integration={i}
                updateExisting={updateExisting[i.id] ?? true}
                customSinceDate={customSinceDate[i.id] || ""}
                onEdit={openEditForm}
                onDelete={handleDelete}
                onSyncPreset={handleSyncPreset}
                onSync={handleSync}
                onStopSync={handleStopSync}
                onUpdateExistingChange={(checked) => setUpdateExisting({ ...updateExisting, [i.id]: checked })}
                onCustomSinceDateChange={(date) => setCustomSinceDate({ ...customSinceDate, [i.id]: date })}
              />
            )
          ))}
        </div>
      )}

      <ImportHistoryTable
        imports={imports}
        importFilter={importFilter}
        importPage={importPage}
        importTotalPages={importTotalPages}
        onFilterChange={(filter) => { setImportFilter(filter); setImportPage(1); }}
        onPageChange={setImportPage}
      />
    </div>
  );
}
