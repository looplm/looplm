"use client";

/**
 * "Source review" tab: import the product-owner source list as CSV, run a bulk
 * completeness scan over every source (rate-limit resilient, with a dead-letter
 * retry), and page through each source's indexed chunks in reading order. Each
 * source (one row of the CSV's Quelle column) is its own cluster of chunks; an
 * optional group-by column adds a higher grouping level.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ReportModal } from "@/components/eval/report-modal";
import { importSourceCsv, listSourceExpectations } from "@/lib/api";
import type { SourceExpectation } from "@/lib/api-types/source-registry";

import { GROUP_DIMENSIONS, readCsvFile } from "./source-registry-shared";
import { buildSourceReviewReport } from "./source-review-report";
import { SourceReviewRow } from "./source-review-row";
import { useSourceScan } from "./use-source-scan";

const CARD_CLS =
  "rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900";
const SECONDARY =
  "inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border " +
  "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 " +
  "hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50";
const PRIMARY =
  "inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium " +
  "bg-indigo-600 text-white hover:bg-indigo-500 transition-colors disabled:opacity-50";

type Group = { key: string; label: string; items: SourceExpectation[] };

export function SourceReviewTab({
  providerId,
  providerName,
  canEdit,
}: {
  providerId: string;
  providerName?: string;
  canEdit: boolean;
}) {
  const [expectations, setExpectations] = useState<SourceExpectation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<string>("none"); // "none" = per source (Quelle)
  const [showFlagged, setShowFlagged] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [reportOpen, setReportOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const { scan, results, summary, running, run, cancel } = useSourceScan(providerId, setError);

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
    setShowFlagged(false);
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

  // "Few chunks": a source with far fewer chunks than the resolved-source median.
  // Only meaningful once enough sources have been scanned.
  const sparseIds = useMemo(() => {
    const counts = [...results.values()]
      .filter((r) => r.execution_status === "ok" && r.resolved)
      .map((r) => r.chunk_count)
      .sort((a, b) => a - b);
    const out = new Set<string>();
    if (counts.length < 5) return out;
    const median = counts[Math.floor(counts.length / 2)] || 0;
    if (median <= 0) return out;
    const threshold = Math.max(1, Math.floor(median * 0.1));
    for (const r of results.values()) {
      if (r.execution_status === "ok" && r.resolved && r.chunk_count <= threshold) {
        out.add(r.expectation_id);
      }
    }
    return out;
  }, [results]);

  const isFlagged = useCallback(
    (id: string) => {
      const r = results.get(id);
      if (!r) return false;
      return (
        r.execution_status === "error" ||
        !r.resolved ||
        r.missing_chunk_count > 0 ||
        sparseIds.has(id)
      );
    },
    [results, sparseIds],
  );

  const availableDims = useMemo(
    () => GROUP_DIMENSIONS.filter((d) => expectations.some((e) => e[d.key])),
    [expectations],
  );

  const groups: Group[] = useMemo(() => {
    const visible = showFlagged ? expectations.filter((e) => isFlagged(e.id)) : expectations;
    if (groupBy === "none") {
      const items = [...visible].sort((a, b) => a.name.localeCompare(b.name));
      return [{ key: "__all__", label: "", items }];
    }
    const map = new Map<string, SourceExpectation[]>();
    for (const e of visible) {
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
  }, [expectations, groupBy, showFlagged, isFlagged]);

  const toggleGroup = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const errored = summary.errored ?? 0;
  const flaggedCount = (summary.not_indexed ?? 0) + (summary.incomplete ?? 0) + errored;
  const hasResults = results.size > 0;

  const reportMarkdown = useMemo(
    () =>
      buildSourceReviewReport({ expectations, results, summary, sparseIds, providerName, groupBy }),
    [expectations, results, summary, sparseIds, providerName, groupBy],
  );

  const handleCopyReport = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(reportMarkdown);
      toast.success("Report copied to clipboard");
    } catch {
      toast.error("Could not copy to clipboard");
    }
  }, [reportMarkdown]);

  const handleDownloadReport = useCallback(() => {
    const slug = (providerName || "index").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const date = new Date().toISOString().slice(0, 10);
    const blob = new Blob([reportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `index-gaps-${slug}-${date}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [reportMarkdown, providerName]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Source review</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            Import the source list as CSV and run an analysis to flag sources whose data seems to be
            missing or incomplete in the index. Expand any source to page through its chunks.
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
              {running ? (
                <>
                  <span className="text-xs tabular-nums text-gray-500 dark:text-slate-400">
                    Scanning… {scan?.processed ?? 0}/{scan?.total || "?"}
                  </span>
                  <button onClick={cancel} className={SECONDARY}>
                    Stop
                  </button>
                </>
              ) : (
                <button
                  onClick={() => run("all")}
                  disabled={expectations.length === 0}
                  className={PRIMARY}
                >
                  Run analysis
                </button>
              )}
              {!running && errored > 0 && (
                <button onClick={() => run("dlq")} className={SECONDARY}>
                  Retry failed ({errored})
                </button>
              )}
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
          {hasResults && (
            <button onClick={() => setReportOpen(true)} className={SECONDARY}>
              Generate report
            </button>
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
      {scan?.status === "failed" && (
        <div className="my-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          Scan failed: {scan.error}
        </div>
      )}

      {hasResults && (
        <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-slate-400">
          <span>
            <span className="font-semibold text-red-600 dark:text-red-400">
              {summary.not_indexed ?? 0}
            </span>{" "}
            not in index
          </span>
          <span>
            <span className="font-semibold text-amber-600 dark:text-amber-400">
              {summary.incomplete ?? 0}
            </span>{" "}
            incomplete
          </span>
          {errored > 0 && (
            <span>
              <span className="font-semibold text-red-600 dark:text-red-400">{errored}</span> scan
              errors
            </span>
          )}
          <span>
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">
              {summary.ok ?? 0}
            </span>{" "}
            ok
          </span>
          <label className="ml-auto inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={showFlagged}
              onChange={(e) => setShowFlagged(e.target.checked)}
              className="rounded border-gray-300 dark:border-slate-600"
            />
            Show only flagged ({flaggedCount})
          </label>
        </div>
      )}

      {loading ? (
        <p className="py-4 text-sm text-gray-400 dark:text-slate-500">Loading…</p>
      ) : expectations.length === 0 ? (
        <p className="py-4 text-sm text-gray-400 dark:text-slate-500">
          No sources defined yet.{" "}
          {canEdit ? "Import the source list as CSV to get started." : ""}
        </p>
      ) : groups.every((g) => g.items.length === 0) ? (
        <p className="py-4 text-sm text-gray-400 dark:text-slate-500">
          {showFlagged ? "No flagged sources." : "No sources to show."}
        </p>
      ) : groupBy === "none" ? (
        <div className={`${CARD_CLS} divide-y divide-gray-100 dark:divide-slate-800`}>
          {groups[0]?.items.map((e) => (
            <SourceReviewRow
              key={e.id}
              expectation={e}
              scanResult={results.get(e.id)}
              sparse={sparseIds.has(e.id)}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => {
            if (g.items.length === 0) return null;
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
                      <SourceReviewRow
                        key={e.id}
                        expectation={e}
                        scanResult={results.get(e.id)}
                        sparse={sparseIds.has(e.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {reportOpen && (
        <ReportModal
          title="What's missing in the index"
          reportMarkdown={reportMarkdown}
          onCopy={handleCopyReport}
          onDownload={handleDownloadReport}
          onClose={() => setReportOpen(false)}
        />
      )}
    </div>
  );
}
