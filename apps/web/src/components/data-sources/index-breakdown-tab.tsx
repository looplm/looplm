"use client";

/**
 * Index breakdown tab: the summary stat cards, the LLM grouping suggestion, the
 * collapsible grouping composer, and the live drill-down tree. Lifted verbatim
 * from the original Data Sources page so the page itself can be a thin tab host.
 */

import { useCallback, useEffect, useState } from "react";

import {
  computeGroupingSuggestion,
  getGroupingSuggestion,
  getIndexSummary,
} from "@/lib/api";
import type {
  IndexGroupingSuggestion,
  IndexGroupingSuggestionResponse,
  IndexSummary,
} from "@/lib/api-types/index-explorer";
import { StatCard } from "@/components/eval-shared";
import { GroupingSuggestionCallout } from "@/components/data-sources/grouping-suggestion-callout";
import { IndexTree } from "@/components/data-sources/index-tree";

import { Chevron } from "./chunk-quality/shared";

const inputCls =
  "px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm";

export function IndexBreakdownTab({ providerId, canEdit }: { providerId: string; canEdit: boolean }) {
  const [summary, setSummary] = useState<IndexSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  // Ordered grouping levels (top → bottom). Each level holds one or more fields;
  // more than one field at a level = parallel facets shown side by side.
  const [levels, setLevels] = useState<string[][]>([]);
  const [composerOpen, setComposerOpen] = useState(false);

  const [suggestion, setSuggestion] = useState<IndexGroupingSuggestion | null>(null);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);

  const applySuggestion = useCallback(
    (resp: IndexGroupingSuggestionResponse, available: IndexSummary["partition_keys"]) => {
      const sug = resp.suggestion;
      setSuggestion(sug);
      if (sug && sug.suggested_levels.length > 0) {
        const valid = sug.suggested_levels
          .map((lvl) => lvl.find((k) => available.some((pk) => pk.key === k)))
          .filter((k): k is string => Boolean(k))
          .map((k) => [k]);
        if (valid.length > 0) setLevels(valid);
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
    setLevels([]);
    setSuggestion(null);
    setSuggestionError(null);
    getIndexSummary(providerId)
      .then((s) => {
        setSummary(s);
        if (s.partition_keys.length > 0) setLevels([[s.partition_keys[0].key]]);
      })
      .catch((e) => setSummaryError((e as Error).message))
      .finally(() => setSummaryLoading(false));
  }, [providerId]);

  // Once the summary is in, fetch the cached grouping suggestion — computing one
  // on the fly when the provider has never been analyzed.
  useEffect(() => {
    if (!providerId || !summary || summary.partition_keys.length === 0) return;
    let cancelled = false;
    const keys = summary.partition_keys;
    setSuggestionError(null);
    setSuggestionLoading(true);
    getGroupingSuggestion(providerId)
      .then((resp) => (resp.suggestion ? resp : computeGroupingSuggestion(providerId)))
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
  const usedCount = levels.reduce((n, lvl) => n + lvl.length, 0);
  const firstUnused = (extra: Set<string>) => keys.find((k) => !extra.has(k.key));

  function changeField(i: number, j: number, value: string) {
    setLevels((prev) => {
      const next = prev.slice(0, i + 1).map((lvl) => [...lvl]);
      if (value === "") {
        next[i].splice(j, 1);
        if (next[i].length === 0) return next.slice(0, i);
      } else {
        next[i][j] = value;
      }
      return next;
    });
  }

  function addParallel(i: number) {
    setLevels((prev) => {
      const used = new Set(prev.flat());
      const k = firstUnused(used);
      if (!k) return prev;
      const next = prev.slice(0, i + 1).map((lvl) => [...lvl]);
      next[i].push(k.key);
      return next;
    });
  }

  function addLevel() {
    setLevels((prev) => {
      const k = firstUnused(new Set(prev.flat()));
      return k ? [...prev, [k.key]] : prev;
    });
  }

  function optionsFor(current: string) {
    const usedElsewhere = new Set(levels.flat().filter((k) => k !== current));
    return keys.filter((k) => k.key === current || !usedElsewhere.has(k.key));
  }

  const canAddMore = usedCount < keys.length && levels.length > 0;
  const groupingSummary = levels
    .map((lvl) => lvl.map((k) => keys.find((x) => x.key === k)?.label ?? k).join(" or "))
    .join(" → ");

  return (
    <>
      {summaryError && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
          {summaryError}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        <StatCard label="Documents in index" value={summary ? summary.document_count.toLocaleString() : "—"} />
        <StatCard label="Groupable fields" value={summary ? summary.partition_keys.length : "—"} />
      </div>

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

      {!summaryLoading && keys.length > 0 && (
        <section className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mb-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold">Index breakdown</h2>
            <p className="text-xs text-gray-500 dark:text-slate-400">
              Drill down into the indexed documents by the fields below.
            </p>
          </div>

          <div className="rounded-lg border border-gray-100 dark:border-slate-800 mb-3">
            <button
              type="button"
              onClick={() => setComposerOpen((v) => !v)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm"
              aria-expanded={composerOpen}
            >
              <Chevron open={composerOpen} />
              <span className="flex-shrink-0 text-gray-500 dark:text-slate-400">Grouped by</span>
              <span className="truncate font-medium text-gray-700 dark:text-slate-200">
                {groupingSummary || "—"}
              </span>
              <span className="ml-auto flex-shrink-0 text-xs text-indigo-600 dark:text-indigo-400">
                {composerOpen ? "Done" : "Edit"}
              </span>
            </button>

            {composerOpen && (
              <div className="border-t border-gray-100 dark:border-slate-800 p-3">
                <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
                  {levels.map((level, i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <span className="text-xs text-gray-500 dark:text-slate-400">
                        {i === 0 ? "Group by" : "then by"}
                      </span>
                      <div className="flex items-center gap-1.5">
                        {level.map((field, j) => (
                          <div key={j} className="flex items-center gap-1.5">
                            {j > 0 && (
                              <span className="text-xs text-gray-400 dark:text-slate-500">or</span>
                            )}
                            <select
                              value={field}
                              onChange={(e) => changeField(i, j, e.target.value)}
                              className={inputCls}
                            >
                              {optionsFor(field).map((k) => (
                                <option key={k.key} value={k.key}>
                                  {k.label}
                                  {k.multivalued ? " (multi)" : ""}
                                </option>
                              ))}
                            </select>
                            {!(i === 0 && j === 0) && (
                              <button
                                onClick={() => changeField(i, j, "")}
                                title="Remove this field"
                                aria-label="Remove this field"
                                className="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 rounded px-1.5 py-1 text-sm leading-none"
                              >
                                ×
                              </button>
                            )}
                          </div>
                        ))}
                        {canAddMore && (
                          <button
                            onClick={() => addParallel(i)}
                            title="Add a parallel field at this level (shown side by side)"
                            className="text-sm text-indigo-600 dark:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800 rounded px-1.5 py-1"
                          >
                            + or
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                  {canAddMore && (
                    <button
                      onClick={addLevel}
                      className="self-end px-3 py-2 rounded-lg text-sm text-indigo-600 dark:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800"
                    >
                      + Add level
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {providerId && levels.length > 0 && (
            <IndexTree
              key={`${providerId}:${levels.map((l) => l.join(",")).join(">")}`}
              providerId={providerId}
              levels={levels}
            />
          )}
        </section>
      )}

      {summaryLoading && (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading index…</p>
      )}

      {!summaryLoading && keys.length === 0 && summary && (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
          This index exposes no groupable (facetable) fields.
        </p>
      )}
    </>
  );
}
