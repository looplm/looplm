"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelSourceScan,
  getSourceScan,
  getSourceScanResults,
  startSourceScan,
} from "@/lib/api";
import type {
  SourceScanResultItem,
  SourceScanRun,
  SourceScanSummary,
} from "@/lib/api-types/source-registry";

/**
 * Owns the bulk source-scan lifecycle for one provider: start (full or DLQ
 * retry), poll progress, cancel, and keep the per-source verdict map + summary
 * fresh. Results stream in while a scan runs (each source is upserted as it is
 * checked), so the row labels fill in live.
 */
export function useSourceScan(providerId: string, setError: (msg: string | null) => void) {
  const [scan, setScan] = useState<SourceScanRun | null>(null);
  const [results, setResults] = useState<Map<string, SourceScanResultItem>>(new Map());
  const [summary, setSummary] = useState<SourceScanSummary>({});
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadResults = useCallback(
    async (seedScan: boolean) => {
      try {
        const res = await getSourceScanResults(providerId);
        setResults(new Map(res.data.map((r) => [r.expectation_id, r])));
        setSummary(res.summary);
        if (seedScan && res.latest_run) {
          setScan(res.latest_run);
          if (res.latest_run.status === "pending" || res.latest_run.status === "running") {
            setRunning(true);
          }
        }
      } catch {
        // No scan yet is fine — the tab still works without verdicts.
      }
    },
    [providerId],
  );

  // Reset + initial load when the provider changes.
  useEffect(() => {
    setScan(null);
    setResults(new Map());
    setSummary({});
    setRunning(false);
    loadResults(true);
  }, [loadResults]);

  // Poll progress + stream partial results while a scan is active.
  useEffect(() => {
    if (!running || !scan) return;
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getSourceScan(scan.id);
        setScan(detail);
        await loadResults(false);
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
    // Depend on scan?.id (not scan) so per-tick progress updates don't reset the poll.
  }, [running, scan?.id, loadResults]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = useCallback(
    async (scope: "all" | "dlq" = "all") => {
      setError(null);
      try {
        const { scan_id } = await startSourceScan(providerId, scope);
        const detail = await getSourceScan(scan_id);
        setScan(detail);
        setRunning(true);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [providerId, setError],
  );

  const cancel = useCallback(async () => {
    if (!scan) return;
    try {
      const detail = await cancelSourceScan(scan.id);
      setScan(detail);
      setRunning(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [scan, setError]);

  return { scan, results, summary, running, run, cancel };
}
