"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getChunkQualityRun,
  listChunkQualityRuns,
  startChunkQualityRun,
} from "@/lib/api";
import type {
  ChunkQualityRunConfig,
  ChunkQualityRunDetail,
  ChunkQualityRunSummary,
} from "@/lib/api-types/chunk-quality";

/**
 * Owns the chunk-quality run lifecycle for one provider: load the latest run,
 * start a fresh sampled analysis, and poll (2s) until it completes or fails.
 * Mirrors `useSourceGapAnalysis`.
 */
export function useChunkQuality(
  providerId: string,
  setError: (msg: string | null) => void,
) {
  const [run, setRun] = useState<ChunkQualityRunDetail | null>(null);
  const [runs, setRuns] = useState<ChunkQualityRunSummary[]>([]);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadLatestRun = useCallback(async () => {
    try {
      const { data } = await listChunkQualityRuns(providerId);
      setRuns(data);
      const latest = data[0];
      if (!latest) {
        setRun(null);
        return;
      }
      const detail = await getChunkQualityRun(latest.id);
      setRun(detail);
      if (detail.status === "pending" || detail.status === "running") {
        setRunning(true);
      }
    } catch {
      // No runs yet is fine.
    }
  }, [providerId]);

  // Reset + reload when the provider changes.
  useEffect(() => {
    setRun(null);
    setRuns([]);
    setRunning(false);
    loadLatestRun();
  }, [loadLatestRun]);

  // Poll while a run is active.
  useEffect(() => {
    if (!running || !run) return;
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getChunkQualityRun(run.id);
        setRun(detail);
        if (detail.status === "completed" || detail.status === "failed") {
          setRunning(false);
          // Refresh the summaries so the trend panel picks up the new run.
          const { data } = await listChunkQualityRuns(providerId);
          setRuns(data);
        }
      } catch {
        setRunning(false);
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [running, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = useCallback(
    async (sampleSize = 8000, config?: ChunkQualityRunConfig) => {
      setError(null);
      try {
        const { run_id } = await startChunkQualityRun(providerId, sampleSize, config);
        const detail = await getChunkQualityRun(run_id);
        setRun(detail);
        setRunning(true);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [providerId, setError],
  );

  return { run, runs, running, handleRun };
}
