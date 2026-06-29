"use client";

import { useEffect, useRef, useState } from "react";
import {
  discoverGithubPrompts,
  confirmGithubExtraction,
  getGithubExtractionStatus,
  cancelGithubExtraction,
  type PromptExtractionStatus,
} from "@/lib/api";

const POLL_ACTIVE = ["pending", "discovering", "running", "clustering"];

interface UseGithubExtractionOptions {
  // Reload the list without flipping the loading state — used to surface
  // prompts as they're extracted one by one.
  refreshPromptsQuietly: () => void;
  loadPrompts: () => void;
  setError: (msg: string | null) => void;
}

export function useGithubExtraction({
  refreshPromptsQuietly,
  loadPrompts,
  setError,
}: UseGithubExtractionOptions) {
  const [extraction, setExtraction] = useState<PromptExtractionStatus | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastCountRef = useRef(0);

  const inProgress = ["pending", "discovering", "running", "clustering"].includes(
    extraction?.status ?? "",
  );
  const awaitingSelection = extraction?.status === "awaiting_selection";
  const lastRunIncomplete =
    extraction?.status === "failed" || extraction?.status === "cancelled";

  // Tick a 1s clock while a run is active so the elapsed timers count up live.
  useEffect(() => {
    if (!inProgress) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [inProgress]);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await getGithubExtractionStatus();
        setExtraction(status);
        // Surface prompts as they land, one by one.
        if (status.extracted_count > lastCountRef.current) {
          lastCountRef.current = status.extracted_count;
          refreshPromptsQuietly();
        }
        if (!POLL_ACTIVE.includes(status.status)) {
          // awaiting_selection / completed / failed / cancelled — stop polling.
          stopPolling();
          lastCountRef.current = 0;
          if (status.status === "completed") loadPrompts();
          if (status.status === "failed" && status.error) setError(status.error);
        }
      } catch {
        stopPolling();
      }
    }, 2000);
  };

  // Resume polling if a run is in flight (e.g. after a reload).
  useEffect(() => {
    getGithubExtractionStatus()
      .then((status) => {
        setExtraction(status);
        if (POLL_ACTIVE.includes(status.status)) startPolling();
      })
      .catch(() => {});
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDiscover = async () => {
    setError(null);
    lastCountRef.current = 0;
    try {
      await discoverGithubPrompts();
      setExtraction({
        id: "", status: "discovering", error: null, summary: null,
        files_analyzed: [], extracted_count: 0, total_cost_usd: null, num_turns: null,
        progress_message: "Scanning the repository…", progress_log: [],
        planned_locations: [], started_at: null, completed_at: null,
      });
      startPolling();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleConfirmImport = async (selected: string[]) => {
    if (!extraction) return;
    setConfirming(true);
    setError(null);
    try {
      await confirmGithubExtraction(extraction.id, selected);
      setExtraction((prev) => (prev ? { ...prev, status: "pending", progress_message: "Starting…" } : prev));
      startPolling();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setConfirming(false);
    }
  };

  const handleCancelExtraction = async () => {
    try {
      await cancelGithubExtraction();
    } catch {
      /* ignore */
    } finally {
      stopPolling();
      setExtraction((prev) => (prev ? { ...prev, status: "cancelled", progress_message: null } : prev));
    }
  };

  return {
    extraction,
    confirming,
    now,
    inProgress,
    awaitingSelection,
    lastRunIncomplete,
    handleDiscover,
    handleConfirmImport,
    handleCancelExtraction,
  };
}
