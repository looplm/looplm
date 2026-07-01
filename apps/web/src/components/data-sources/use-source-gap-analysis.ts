"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelGapRun,
  fetchGapRunReport,
  getGapRun,
  importSourceCsv,
  listGapRuns,
  startGapRun,
} from "@/lib/api";
import type { GapRunDetail } from "@/lib/api-types/source-registry";

import { readCsvFile } from "./source-registry-shared";

/**
 * Owns the gap-run lifecycle (start, poll, download report) plus CSV import for
 * a single provider. The caller passes in a `loadExpectations` callback so the
 * registry refreshes after an import, and the shared error/notice banner
 * setters so messages funnel through a single channel.
 */
export function useSourceGapAnalysis(
  providerId: string,
  loadExpectations: () => Promise<void>,
  setError: (msg: string | null) => void,
  setNotice: (msg: string | null) => void,
) {
  const [run, setRun] = useState<GapRunDetail | null>(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Reset run state when the provider changes.
  useEffect(() => {
    setRun(null);
    setNotice(null);
    loadLatestRun();
  }, [loadLatestRun]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while a run is active.
  useEffect(() => {
    if (!running || !run) return;
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getGapRun(run.id);
        setRun(detail);
        if (
          detail.status === "completed" ||
          detail.status === "failed" ||
          detail.status === "cancelled"
        ) {
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

  async function handleCancel() {
    if (!run) return;
    setError(null);
    try {
      const detail = await cancelGapRun(run.id);
      setRun(detail);
      setRunning(false);
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

  return {
    run,
    running,
    handleImport,
    handleRun,
    handleCancel,
    handleDownloadReport,
  };
}
