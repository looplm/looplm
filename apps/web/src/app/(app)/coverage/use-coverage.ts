"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  getCoverageRun,
  getDatasets,
  getIndexProviders,
  getPartitionKeys,
  startCoverageAnalysis,
  type CoverageRun,
  type IndexProvider,
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

  useEffect(() => {
    loadProviders();
    loadDatasets();
  }, [loadProviders, loadDatasets]);

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
    [providerId, stopPolling],
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
  };
}
