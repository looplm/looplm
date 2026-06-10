"use client";

import { useCallback, useEffect, useState } from "react";

import {
  computeGroupingSuggestion,
  getGroupingSuggestion,
  getIndexExplorerProviders,
  getIndexSummary,
} from "@/lib/api";
import type {
  IndexGroupingSuggestion,
  IndexGroupingSuggestionResponse,
  IndexProviderOption,
  IndexSummary,
} from "@/lib/api-types/index-explorer";
import { StatCard } from "@/components/eval-shared";
import { IndexTree } from "@/components/data-sources/index-tree";
import { GroupingSuggestionCallout } from "@/components/data-sources/grouping-suggestion-callout";
import { ProviderManager } from "@/components/coverage/provider-manager";
import { usePermissions } from "@/components/permissions-context";

const inputCls =
  "px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm";

export default function DataSourcesPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("coverage");

  const [providers, setProviders] = useState<IndexProviderOption[]>([]);
  const [providerId, setProviderId] = useState("");
  const [providersLoading, setProvidersLoading] = useState(true);
  const [managerOpen, setManagerOpen] = useState(false);

  const [summary, setSummary] = useState<IndexSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  // Ordered list of fields the tree groups by (top → bottom).
  const [groupBy, setGroupBy] = useState<string[]>([]);

  // LLM grouping advisor (auto-run on provider load, cached server-side).
  const [suggestion, setSuggestion] = useState<IndexGroupingSuggestion | null>(null);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await getIndexExplorerProviders();
      setProviders(data);
      // Keep the current selection if it still exists; otherwise default to the first.
      setProviderId((prev) =>
        data.some((p) => p.id === prev) ? prev : (data[0]?.id ?? ""),
      );
    } catch {
      // Ignore — the empty state covers a failed/empty load.
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  // Load providers once.
  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  // Apply a suggestion response: store it for the callout and adopt its
  // hierarchy (clamped to fields that actually exist on this index).
  const applySuggestion = useCallback(
    (resp: IndexGroupingSuggestionResponse, available: IndexSummary["partition_keys"]) => {
      const sug = resp.suggestion;
      setSuggestion(sug);
      if (sug && sug.suggested_group_by.length > 0) {
        const valid = sug.suggested_group_by.filter((k) =>
          available.some((pk) => pk.key === k),
        );
        if (valid.length > 0) setGroupBy(valid);
      }
    },
    [],
  );

  // Load summary + a provisional default grouping when the provider changes.
  useEffect(() => {
    if (!providerId) return;
    setSummaryLoading(true);
    setSummaryError(null);
    setSummary(null);
    setGroupBy([]);
    setSuggestion(null);
    setSuggestionError(null);
    getIndexSummary(providerId)
      .then((s) => {
        setSummary(s);
        // Provisional default; the advisor effect may override it below.
        if (s.partition_keys.length > 0) setGroupBy([s.partition_keys[0].key]);
      })
      .catch((e) => setSummaryError((e as Error).message))
      .finally(() => setSummaryLoading(false));
  }, [providerId]);

  // Once the summary is in, fetch the cached grouping suggestion — computing one
  // on the fly (auto-run) when the provider has never been analyzed.
  useEffect(() => {
    if (!providerId || !summary || summary.partition_keys.length === 0) return;
    let cancelled = false;
    const keys = summary.partition_keys;
    setSuggestionError(null);
    setSuggestionLoading(true);
    getGroupingSuggestion(providerId)
      .then((resp) =>
        resp.suggestion ? resp : computeGroupingSuggestion(providerId),
      )
      .then((resp) => {
        if (!cancelled) applySuggestion(resp, keys);
      })
      .catch((e) => {
        if (!cancelled) setSuggestionError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setSuggestionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [providerId, summary, applySuggestion]);

  const handleReanalyze = useCallback(() => {
    if (!providerId || !summary) return;
    const keys = summary.partition_keys;
    setSuggestionError(null);
    setSuggestionLoading(true);
    computeGroupingSuggestion(providerId)
      .then((resp) => applySuggestion(resp, keys))
      .catch((e) => setSuggestionError((e as Error).message))
      .finally(() => setSuggestionLoading(false));
  }, [providerId, summary, applySuggestion]);

  const keys = summary?.partition_keys ?? [];

  function setLevel(idx: number, value: string) {
    setGroupBy((prev) => {
      if (value === "") return prev.slice(0, idx); // remove this level and any below
      const next = [...prev];
      next[idx] = value;
      return next.slice(0, idx + 1); // changing a level drops deeper levels
    });
  }

  function addLevel() {
    const used = new Set(groupBy);
    const nextKey = keys.find((k) => !used.has(k.key));
    if (nextKey) setGroupBy((prev) => [...prev, nextKey.key]);
  }

  const canAddLevel = groupBy.length < keys.length && groupBy.length > 0;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">Data Sources</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
            Explore what is currently in your connected retrieval index — drill down by source
            type, space, or URL into the indexed documents.
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
          {summaryError && (
            <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
              {summaryError}
            </div>
          )}

          {/* Summary */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <StatCard
              label="Documents in index"
              value={summary ? summary.document_count.toLocaleString() : "—"}
            />
            <StatCard
              label="Groupable fields"
              value={summary ? summary.partition_keys.length : "—"}
            />
            <StatCard label="Provider" value={providers.find((p) => p.id === providerId)?.name ?? "—"} />
          </div>

          {/* LLM-suggested hierarchy + metadata hints */}
          {!summaryLoading && keys.length > 0 && (
            <GroupingSuggestionCallout
              suggestion={suggestion}
              keys={keys}
              loading={suggestionLoading}
              error={suggestionError}
              onReanalyze={handleReanalyze}
              canReanalyze={canEdit}
            />
          )}

          {/* Group-by composer */}
          {!summaryLoading && keys.length > 0 && (
            <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mb-4">
              <div className="flex flex-wrap items-end gap-3">
                {groupBy.map((g, idx) => (
                  <label key={idx} className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500 dark:text-slate-400">
                      {idx === 0 ? "Group by" : "then by"}
                    </span>
                    <select
                      value={g}
                      onChange={(e) => setLevel(idx, e.target.value)}
                      className={inputCls}
                    >
                      {keys.map((k) => (
                        <option key={k.key} value={k.key}>
                          {k.label}
                          {k.multivalued ? " (multi)" : ""}
                        </option>
                      ))}
                      {idx > 0 && <option value="">— remove —</option>}
                    </select>
                  </label>
                ))}
                {canAddLevel && (
                  <button
                    onClick={addLevel}
                    className="px-3 py-2 rounded-lg text-sm text-indigo-600 dark:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800"
                  >
                    + Add level
                  </button>
                )}
              </div>
            </div>
          )}

          {summaryLoading && (
            <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading index…</p>
          )}

          {!summaryLoading && keys.length === 0 && summary && (
            <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
              This index exposes no groupable (facetable) fields.
            </p>
          )}

          {!summaryLoading && providerId && groupBy.length > 0 && (
            <IndexTree
              key={`${providerId}:${groupBy.join(">")}`}
              providerId={providerId}
              groupBy={groupBy}
            />
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
