"use client";

import { useCallback, useEffect, useState } from "react";

import { getIndexExplorerProviders } from "@/lib/api";
import type { IndexProviderOption } from "@/lib/api-types/index-explorer";
import { ChunkQualityTab } from "@/components/data-sources/chunk-quality-tab";
import { FieldSchemaTab } from "@/components/data-sources/field-schema-tab";
import { FileSearchTab } from "@/components/data-sources/file-search-tab";
import { IndexBreakdownTab } from "@/components/data-sources/index-breakdown-tab";
import { SourceReviewTab } from "@/components/data-sources/source-review-tab";
import { WantedSourcesPanel } from "@/components/data-sources/wanted-sources-panel";
import { ProviderManager } from "@/components/coverage/provider-manager";
import { usePermissions } from "@/components/permissions-context";

const inputCls =
  "px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm";

type Tab = "breakdown" | "fields" | "files" | "wanted" | "review" | "quality";

const TABS: { id: Tab; label: string }[] = [
  { id: "breakdown", label: "Index breakdown" },
  { id: "fields", label: "Fields" },
  { id: "files", label: "Files" },
  { id: "wanted", label: "Wanted sources" },
  { id: "review", label: "Source review" },
  { id: "quality", label: "Chunk quality" },
];

export default function DataSourcesPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("coverage");

  const [providers, setProviders] = useState<IndexProviderOption[]>([]);
  const [providerId, setProviderId] = useState("");
  const [providersLoading, setProvidersLoading] = useState(true);
  const [managerOpen, setManagerOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("breakdown");

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await getIndexExplorerProviders();
      setProviders(data);
      setProviderId((prev) => (data.some((p) => p.id === prev) ? prev : (data[0]?.id ?? "")));
    } catch {
      // Ignore — the empty state covers a failed/empty load.
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">Data Sources</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
            Explore what is currently in your connected retrieval index — drill down by source
            type, reconcile it against the sources you expect, and check the quality of the indexed
            chunks.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {providers.length > 0 && (
            <select
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
              className={inputCls}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => setManagerOpen(true)}
            className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
          >
            Manage providers
          </button>
        </div>
      </div>

      {providersLoading ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-8">Loading…</p>
      ) : providers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center">
          <p className="text-sm text-gray-500 dark:text-slate-400">
            No index providers connected yet. Connect a retrieval index to explore its contents.
          </p>
          <button
            onClick={() => setManagerOpen(true)}
            className="mt-3 px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500"
          >
            Connect an index
          </button>
        </div>
      ) : (
        <>
          {/* Tabs */}
          <div className="flex gap-1 border-b border-gray-200 dark:border-slate-700 mb-6">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  tab === t.id
                    ? "border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400"
                    : "border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "breakdown" && providerId && (
            <IndexBreakdownTab providerId={providerId} canEdit={canEdit} />
          )}
          {tab === "fields" && providerId && (
            <FieldSchemaTab
              providerId={providerId}
              providerName={providers.find((p) => p.id === providerId)?.name}
              canEdit={canEdit}
            />
          )}
          {tab === "files" && providerId && <FileSearchTab providerId={providerId} />}
          {tab === "wanted" && providerId && (
            <WantedSourcesPanel providerId={providerId} canEdit={canEdit} />
          )}
          {tab === "review" && providerId && (
            <SourceReviewTab
              providerId={providerId}
              providerName={providers.find((p) => p.id === providerId)?.name}
              canEdit={canEdit}
            />
          )}
          {tab === "quality" && providerId && (
            <ChunkQualityTab providerId={providerId} canEdit={canEdit} />
          )}
        </>
      )}

      <ProviderManager
        open={managerOpen}
        canEdit={canEdit}
        onClose={() => setManagerOpen(false)}
        onChanged={loadProviders}
      />
    </div>
  );
}
