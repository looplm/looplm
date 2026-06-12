"use client";

/**
 * Wanted-status source registry: declare which sources SHOULD be in the index
 * (CSV import or manual edits), run a gap analysis against what actually is,
 * and export the result as a markdown report for the indexing-pipeline owners.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteSourceExpectation,
  fetchGapRunReport,
  getGapRun,
  importSourceCsv,
  listGapRuns,
  listSourceExpectations,
  startGapRun,
  updateSourceExpectation,
} from "@/lib/api";
import type {
  GapRowResult,
  GapRunDetail,
  SourceExpectation,
} from "@/lib/api-types/source-registry";

const STATUS_CHIP: Record<string, { label: string; cls: string }> = {
  covered_url: {
    label: "Covered (URL)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  covered_title: {
    label: "Covered (title)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  review: {
    label: "Review",
    cls: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  },
  missing: {
    label: "Missing",
    cls: "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  },
  acked: {
    label: "Acknowledged",
    cls: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
  },
};

/** Decode an uploaded CSV: try UTF-8 first, fall back to cp1252 exports. */
async function readCsvFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const utf8 = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  if (!utf8.includes("�")) return utf8;
  return new TextDecoder("windows-1252").decode(buffer);
}

export function WantedSourcesPanel({
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

  const [run, setRun] = useState<GapRunDetail | null>(null);
  const [running, setRunning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const verdicts: Record<string, GapRowResult> = {};
  for (const row of run?.results?.rows ?? []) verdicts[row.expectation_id] = row;

  const loadExpectations = useCallback(async () => {
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

  const loadLatestRun = useCallback(async () => {
    try {
      const { data } = await listGapRuns(providerId);
      const latest = data[0];
      if (!latest) return;
      const detail = await getGapRun(latest.id);
      setRun(detail);
      if (detail.status === "pending" || detail.status === "running") {
        setRunning(true);
      }
    } catch {
      // No runs yet is fine.
    }
  }, [providerId]);

  useEffect(() => {
    setRun(null);
    setNotice(null);
    loadExpectations();
    loadLatestRun();
  }, [loadExpectations, loadLatestRun]);

  // Poll while a run is active.
  useEffect(() => {
    if (!running || !run) return;
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getGapRun(run.id);
        setRun(detail);
        if (detail.status === "completed" || detail.status === "failed") {
          setRunning(false);
        }
      } catch {
        setRunning(false);
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [running, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleImport(file: File) {
    setError(null);
    setNotice(null);
    try {
      const csvText = await readCsvFile(file);
      const result = await importSourceCsv(providerId, csvText, false);
      setNotice(
        `Imported: ${result.created} new, ${result.updated} updated` +
          (result.skipped_rows ? `, ${result.skipped_rows} rows skipped (no link)` : "") +
          (result.warnings.length ? ` — ${result.warnings.length} warning(s)` : ""),
      );
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRun() {
    setError(null);
    try {
      const { run_id } = await startGapRun(providerId);
      const detail = await getGapRun(run_id);
      setRun(detail);
      setRunning(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDownloadReport() {
    if (!run) return;
    try {
      const markdown = await fetchGapRunReport(run.id);
      const blob = new Blob([markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `source-gap-report-${run.completed_at?.slice(0, 10) ?? "latest"}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleAck(expectation: SourceExpectation) {
    const note = window.prompt(
      "Why is this source intentionally not indexed? (empty input cancels)",
      expectation.ack_note ?? "",
    );
    if (!note) return;
    try {
      await updateSourceExpectation(expectation.id, { ack_note: note });
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleUnack(expectation: SourceExpectation) {
    try {
      await updateSourceExpectation(expectation.id, { ack_note: "" });
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDelete(expectation: SourceExpectation) {
    if (!window.confirm(`Remove "${expectation.name}" from the wanted sources?`)) return;
    try {
      await deleteSourceExpectation(expectation.id);
      await loadExpectations();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const summary = run?.results?.summary;

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mt-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <div>
          <h2 className="text-lg font-semibold">Wanted sources</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            The sources that should be retrievable from this index. Import the source list as
            CSV, then run a gap analysis to compare it against what is actually indexed.
          </p>
        </div>
        <div className="flex items-center gap-2">
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
              <button
                onClick={() => fileRef.current?.click()}
                className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
              >
                Import CSV
              </button>
            </>
          )}
          {canEdit && expectations.length > 0 && (
            <button
              onClick={handleRun}
              disabled={running}
              className="px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {running
                ? `Analyzing… ${run?.processed ?? 0}/${run?.total ?? expectations.length}`
                : "Run gap analysis"}
            </button>
          )}
          {run?.status === "completed" && (
            <button
              onClick={handleDownloadReport}
              className="px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
            >
              Download report
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-2 my-3">
          {error}
        </div>
      )}
      {notice && (
        <div className="bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 text-sm rounded-lg px-4 py-2 my-3">
          {notice}
        </div>
      )}
      {run?.status === "failed" && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-2 my-3">
          Gap analysis failed: {run.error}
        </div>
      )}

      {summary && run?.status === "completed" && (
        <div className="flex flex-wrap gap-2 my-3 text-xs">
          <span className={`px-2 py-1 rounded-full ${STATUS_CHIP.covered_url.cls}`}>
            ✓ {summary.covered} covered
          </span>
          <span className={`px-2 py-1 rounded-full ${STATUS_CHIP.review.cls}`}>
            {summary.review} to review
          </span>
          <span className={`px-2 py-1 rounded-full ${STATUS_CHIP.missing.cls}`}>
            {summary.missing} missing
          </span>
          <span className={`px-2 py-1 rounded-full ${STATUS_CHIP.acked.cls}`}>
            {summary.acked} acknowledged
          </span>
          {run.completed_at && (
            <span className="px-2 py-1 text-gray-400 dark:text-slate-500">
              analyzed {new Date(run.completed_at).toLocaleString()}
            </span>
          )}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">Loading…</p>
      ) : expectations.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
          No wanted sources defined yet.{" "}
          {canEdit ? "Import the source list as CSV to get started." : ""}
        </p>
      ) : (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 dark:text-slate-400 border-b border-gray-100 dark:border-slate-800">
                <th className="py-2 pr-3 font-medium">Source</th>
                <th className="py-2 pr-3 font-medium">Type</th>
                <th className="py-2 pr-3 font-medium">Adapter</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Evidence</th>
                {canEdit && <th className="py-2 font-medium" />}
              </tr>
            </thead>
            <tbody>
              {expectations.map((e) => {
                const verdict = verdicts[e.id];
                const status = e.ack_note ? "acked" : verdict?.status;
                const chip = status ? STATUS_CHIP[status] : null;
                return (
                  <tr
                    key={e.id}
                    className="border-b border-gray-50 dark:border-slate-800/50 align-top"
                  >
                    <td className="py-2 pr-3 max-w-[28rem]">
                      <span className="font-medium">{e.name}</span>
                      <div className="flex gap-2 text-xs">
                        {e.html_url && (
                          <a
                            href={e.html_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-indigo-600 dark:text-indigo-400 hover:underline"
                          >
                            HTML
                          </a>
                        )}
                        {e.pdf_url && (
                          <a
                            href={e.pdf_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-indigo-600 dark:text-indigo-400 hover:underline"
                          >
                            PDF
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-gray-500 dark:text-slate-400">
                      {e.typ ?? "—"}
                    </td>
                    <td className="py-2 pr-3">
                      {e.adapter_tag ? (
                        <code className="text-xs bg-gray-100 dark:bg-slate-800 rounded px-1.5 py-0.5">
                          {e.adapter_tag}
                        </code>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {chip ? (
                        <span className={`px-2 py-1 rounded-full text-xs ${chip.cls}`}>
                          {chip.label}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400 dark:text-slate-500">
                          not analyzed
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs text-gray-500 dark:text-slate-400 max-w-[24rem]">
                      {e.ack_note ? (
                        <>Acknowledged: {e.ack_note}</>
                      ) : verdict ? (
                        <>
                          {verdict.detail}
                          {verdict.matched_title && (
                            <span className="block truncate">↳ {verdict.matched_title}</span>
                          )}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    {canEdit && (
                      <td className="py-2 whitespace-nowrap text-xs">
                        {e.ack_note ? (
                          <button
                            onClick={() => handleUnack(e)}
                            className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
                          >
                            Un-ack
                          </button>
                        ) : (
                          <button
                            onClick={() => handleAck(e)}
                            title="Mark this gap as intentional"
                            className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
                          >
                            Ack
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(e)}
                          className="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 px-1.5 py-1"
                        >
                          ×
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
