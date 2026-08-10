"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelSyntheticQuestionRun,
  getSyntheticQuestionRun,
  listSyntheticQuestionRuns,
  startSyntheticQuestionRun,
} from "@/lib/api";
import type {
  SyntheticQuestionRunDetail,
  SyntheticQuestionRunRequest,
  SyntheticQuestionRunSummary,
} from "@/lib/api-types/synthetic-questions";

const ACTIVE = ["pending", "running"];
const TERMINAL = ["completed", "failed", "cancelled"];

/**
 * Owns the synthetic-question run lifecycle for one provider: load the latest run,
 * start a generation or preview, and poll (2s) until it finishes. Mirrors `useChunkQuality`.
 */
export function useSyntheticQuestions(
  providerId: string,
  setError: (msg: string | null) => void,
) {
  const [run, setRun] = useState<SyntheticQuestionRunDetail | null>(null);
  const [runs, setRuns] = useState<SyntheticQuestionRunSummary[]>([]);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadLatestRun = useCallback(async () => {
    try {
      const { data } = await listSyntheticQuestionRuns(providerId);
      setRuns(data);
      const latest = data[0];
      if (!latest) {
        setRun(null);
        return;
      }
      const detail = await getSyntheticQuestionRun(latest.id);
      setRun(detail);
      if (ACTIVE.includes(detail.status)) setRunning(true);
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
        const detail = await getSyntheticQuestionRun(run.id);
        setRun(detail);
        if (TERMINAL.includes(detail.status)) {
          setRunning(false);
          const { data } = await listSyntheticQuestionRuns(providerId);
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
    async (body: Omit<SyntheticQuestionRunRequest, "provider_id">) => {
      setError(null);
      try {
        const { run_id } = await startSyntheticQuestionRun({
          provider_id: providerId,
          ...body,
        });
        const detail = await getSyntheticQuestionRun(run_id);
        setRun(detail);
        setRunning(true);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [providerId, setError],
  );

  const handleCancel = useCallback(async () => {
    if (!run) return;
    try {
      await cancelSyntheticQuestionRun(run.id);
      setRun(await getSyntheticQuestionRun(run.id));
      setRunning(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [run, setError]);

  return { run, runs, running, handleRun, handleCancel, reload: loadLatestRun };
}
