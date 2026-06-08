"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  createAcknowledgement,
  deleteAcknowledgement,
  getAcknowledgements,
  getCoverageOverview,
  getCoverageRun,
  getDatasets,
  getIndexProviders,
  getPartitionKeys,
  listCoverageRuns,
  startCoverageAnalysis,
  type CoverageCategoryOverview,
  type CoverageRun,
  type CoverageRunSummary,
  type IndexProvider,
  type PartitionAcknowledgement,
  type PartitionKey,
  type StartAnalysisBody,
  type TestDatasetItem,
} from "@/lib/api";

const POLL_MS = 3000;

export function useCoverage() {
  const [providers, setProviders] = useState<IndexProvider[]>([]);
  const [providerId, setProviderId] = useState<string>("");
  const [partitionKeys, setPartitionKeys] = useState<PartitionKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [datasets, setDatasets] = useState<TestDatasetItem[]>([]);

  const [run, setRun] = useState<CoverageRun | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [acknowledgements, setAcknowledgements] = useState<PartitionAcknowledgement[]>([]);
  const [overview, setOverview] = useState<CoverageCategoryOverview[]>([]);
  const [history, setHistory] = useState<CoverageRunSummary[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await getIndexProviders();
      setProviders(data);
      setProviderId((cur) => cur || data[0]?.id || "");
    } catch (err) {
      toast.error("Failed to load providers", { description: String(err) });
    }
  }, []);

  const loadDatasets = useCallback(async () => {
    try {
      const resp = await getDatasets({ per_page: "100" });
      setDatasets(resp.data);
    } catch {
      /* non-fatal */
    }
  }, []);

  // Overview (latest per category) + full run history, scoped to the provider.
  const refreshLists = useCallback(async () => {
    if (!providerId) {
      setOverview([]);
      setHistory([]);
      return;
    }
    try {
      const [ov, hist] = await Promise.all([
        getCoverageOverview(providerId),
        listCoverageRuns(providerId),
      ]);
      setOverview(ov.data);
      setHistory(hist.data);
    } catch {
      /* non-fatal */
    }
  }, [providerId]);

  useEffect(() => {
    loadProviders();
    loadDatasets();
  }, [loadProviders, loadDatasets]);

  useEffect(() => {
    refreshLists();
  }, [refreshLists]);

  const openRun = useCallback(async (runId: string) => {
    try {
      const full = await getCoverageRun(runId);
      setRun(full);
    } catch (err) {
      toast.error("Failed to open run", { description: String(err) });
    }
  }, []);

  // Load partition keys whenever the selected provider changes.
  useEffect(() => {
    if (!providerId) {
      setPartitionKeys([]);
      return;
    }
    let cancelled = false;
    setKeysLoading(true);
    setPartitionKeys([]);
    getPartitionKeys(providerId)
      .then(({ data }) => {
        if (!cancelled) setPartitionKeys(data);
      })
      .catch((err) => {
        if (!cancelled) toast.error("Failed to load partition keys", { description: String(err) });
      })
      .finally(() => {
        if (!cancelled) setKeysLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [providerId]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const analyze = useCallback(
    async (opts: Omit<StartAnalysisBody, "provider_id">) => {
      if (!providerId) return;
      setAnalyzing(true);
      setRun(null);
      stopPolling();
      try {
        const { run_id } = await startCoverageAnalysis({ provider_id: providerId, ...opts });
        // Poll until terminal.
        pollRef.current = setInterval(async () => {
          try {
            const updated = await getCoverageRun(run_id);
            setRun(updated);
            if (updated.status === "completed" || updated.status === "failed") {
              stopPolling();
              setAnalyzing(false);
              if (updated.status === "completed") {
                toast.success("Coverage analysis complete");
                refreshLists();
              } else {
                toast.error("Analysis failed", { description: updated.error || "Unknown error" });
              }
            }
          } catch (err) {
            stopPolling();
            setAnalyzing(false);
            toast.error("Polling failed", { description: String(err) });
          }
        }, POLL_MS);
      } catch (err) {
        setAnalyzing(false);
        toast.error("Failed to start analysis", { description: String(err) });
      }
    },
    [providerId, stopPolling, refreshLists],
  );

  // Acknowledgements ("intentional" memory) for the completed run's partition.
  const completedKey = run?.status === "completed" ? run.results?.partition_key : undefined;

  const refreshAcks = useCallback(async () => {
    if (!providerId || !completedKey) {
      setAcknowledgements([]);
      return;
    }
    try {
      const { data } = await getAcknowledgements(providerId, completedKey);
      setAcknowledgements(data);
    } catch {
      /* non-fatal */
    }
  }, [providerId, completedKey]);

  useEffect(() => {
    refreshAcks();
  }, [refreshAcks]);

  const addAcknowledgement = useCallback(
    async (value: string, note: string) => {
      if (!providerId || !completedKey) return;
      try {
        await createAcknowledgement({
          provider_id: providerId,
          partition_key: completedKey,
          partition_value: value,
          note: note || undefined,
        });
        toast.success("Marked as intentional");
        await refreshAcks();
      } catch (err) {
        toast.error("Failed to save", { description: String(err) });
      }
    },
    [providerId, completedKey, refreshAcks],
  );

  const removeAcknowledgement = useCallback(
    async (id: string) => {
      try {
        await deleteAcknowledgement(id);
        await refreshAcks();
      } catch (err) {
        toast.error("Failed to undo", { description: String(err) });
      }
    },
    [refreshAcks],
  );

  return {
    providers,
    providerId,
    setProviderId,
    partitionKeys,
    keysLoading,
    datasets,
    run,
    analyzing,
    analyze,
    loadProviders,
    loadDatasets,
    acknowledgements,
    addAcknowledgement,
    removeAcknowledgement,
    overview,
    history,
    openRun,
    refreshLists,
  };
}
