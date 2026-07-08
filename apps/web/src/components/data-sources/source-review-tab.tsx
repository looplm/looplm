"use client";

/**
 * "Source review" tab: import the product-owner source list as CSV, then page
 * through every indexed chunk of each source in reading order to check for
 * completeness. Each source (one row of the CSV's Quelle column) is its own
 * cluster of chunks; an optional group-by column adds a higher grouping level.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { importSourceCsv, listSourceExpectations } from "@/lib/api";
import type { SourceExpectation } from "@/lib/api-types/source-registry";

import { GROUP_DIMENSIONS, readCsvFile } from "./source-registry-shared";
import { SourceReviewRow } from "./source-review-row";

const CARD_CLS =
  "rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900";
const SECONDARY =
  "inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border " +
  "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 " +
  "hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50";

type Group = { key: string; label: string; items: SourceExpectation[] };

export function SourceReviewTab({
  providerId,
  canEdit,
}: {
  providerId: string;
  canEdit: boolean;
}) {
  const [expectations, setExpectations] = useState<SourceExpectation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<string>("none"); // "none" = per source (Quelle)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await listSourceExpectations(providerId);
      setExpectations(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  useEffect(() => {
    setNotice(null);
    load();
  }, [load]);

  async function handleImport(file: File) {
    setError(null);
    setNotice(null);
    try {
      const csvText = await readCsvFile(file);
      const result = await importSourceCsv(providerId, csvText, false);
      setNotice(
        `Imported: ${result.created} new, ${result.updated} updated` +
          (result.skipped_rows ? `, ${result.skipped_rows} rows skipped (no link)` : ""),
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  // Group-by columns that actually carry values on the current expectations.
  const availableDims = useMemo(
    () => GROUP_DIMENSIONS.filter((d) => expectations.some((e) => e[d.key])),
    [expectations],
  );

  const groups: Group[] = useMemo(() => {
    if (groupBy === "none") {
      const items = [...expectations].sort((a, b) => a.name.localeCompare(b.name));
      return [{ key: "__all__", label: "", items }];
    }
    const map = new Map<string, SourceExpectation[]>();
    for (const e of expectations) {
      const raw = e[groupBy as keyof SourceExpectation] as string | null;
      const key = (raw && String(raw).trim()) || "__uncat__";
      const bucket = map.get(key);
      if (bucket) bucket.push(e);
      else map.set(key, [e]);
    }
    const out: Group[] = [];
    for (const [key, items] of map) {
      items.sort((a, b) => a.name.localeCompare(b.name));
      out.push({ key, label: key === "__uncat__" ? "Uncategorized" : key, items });
    }
    out.sort((a, b) => a.label.localeCompare(b.label));
    return out;
  }, [expectations, groupBy]);

  const toggleGroup = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Source review</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            Import the source list as CSV, then expand a source to page through every indexed chunk
            in reading order and check it for completeness.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-gray-500 dark:text-slate-400">
            Cluster by{" "}
            <select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              className="ml-1 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="none">Source (Quelle)</option>
              {availableDims.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
          {canEdit && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleImport(f);
                  e.target.value = "";
                }}
              />
              <button onClick={() => fileRef.current?.click()} className={SECONDARY}>
                Import CSV
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="my-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}
      {notice && (
        <div className="my-3 rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400">
          {notice}
        </div>
      )}

      {loading ? (
        <p className="py-4 text-sm text-gray-400 dark:text-slate-500">Loading…</p>
      ) : expectations.length === 0 ? (
        <p className="py-4 text-sm text-gray-400 dark:text-slate-500">
          No sources defined yet.{" "}
          {canEdit ? "Import the source list as CSV to get started." : ""}
        </p>
      ) : groupBy === "none" ? (
        <div className={`${CARD_CLS} divide-y divide-gray-100 dark:divide-slate-800`}>
          {groups[0]?.items.map((e) => (
            <SourceReviewRow key={e.id} expectation={e} />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => {
            const isCollapsed = collapsed.has(g.key);
            return (
              <div key={g.key}>
                <button
                  onClick={() => toggleGroup(g.key)}
                  className="mb-1 flex w-full items-center gap-2 text-left text-sm font-medium text-gray-600 dark:text-slate-300"
                >
                  <span className="text-gray-400">{isCollapsed ? "▸" : "▾"}</span>
                  {g.label}
                  <span className="text-xs font-normal text-gray-400 dark:text-slate-500">
                    ({g.items.length})
                  </span>
                </button>
                {!isCollapsed && (
                  <div className={`${CARD_CLS} divide-y divide-gray-100 dark:divide-slate-800`}>
                    {g.items.map((e) => (
                      <SourceReviewRow key={e.id} expectation={e} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
