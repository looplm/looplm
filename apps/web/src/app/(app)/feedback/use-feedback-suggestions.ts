"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  generateSuggestions,
  getLatestSuggestions,
  acceptSuggestion,
  deleteTestCase,
  getDatasets,
  type TestCaseSuggestion,
  type TestDatasetItem,
  type TestCaseCreateBody,
} from "@/lib/api";
import { getSuggestionRun, stopSuggestionRun } from "@/lib/api/evals-api";
import type { SuggestionRunResponse } from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

// `setDerivedView` is owned by the compose hook; the loaders jump to the
// results view when a run is already in progress, so it is threaded in.
export function useFeedbackSuggestions(setDerivedView: (v: "picker" | "results") => void) {
  const globalFilters = useGlobalFilters();

  const [suggestions, setSuggestions] = useState<TestCaseSuggestion[]>([]);
  const [sugLoading, setSugLoading] = useState(false);
  const [sugGenerated, setSugGenerated] = useState(false);
  const [sugFilter, setSugFilter] = useState<"all" | "positive" | "negative">("all");
  const [datasets, setDatasets] = useState<TestDatasetItem[]>([]);
  const [selectedSuggestion, setSelectedSuggestion] = useState<TestCaseSuggestion | null>(null);
  const [saving, setSaving] = useState(false);
  const [suggestionRun, setSuggestionRun] = useState<SuggestionRunResponse | null>(null);

  const loadSuggestions = useCallback(async (idsOverride?: string[]) => {
    setSugLoading(true);
    try {
      const params: Record<string, string> = {};
      if (idsOverride && idsOverride.length > 0) {
        // Hand-picked feedback: the selection IS the filter, so the
        // type/date/environment/user params are intentionally omitted.
        params.selected_feedback_ids = idsOverride.join(",");
      } else {
        params.feedback_type = sugFilter;
        params.limit = "100";
        if (globalFilters.startDate) params.from_date = new Date(globalFilters.startDate).toISOString();
        if (globalFilters.endDate) params.to_date = new Date(globalFilters.endDate).toISOString();
        if (globalFilters.environment && globalFilters.environment !== "all") {
          params.environment = globalFilters.environment;
        }
        if (globalFilters.filteredUsers.length > 0) {
          const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
          params[key] = globalFilters.filteredUsers.join(",");
        }
      }
      const [run, dsData] = await Promise.all([
        generateSuggestions(params),
        getDatasets(),
      ]);
      setSuggestionRun(run);
      setDatasets(dsData.data);
      setSugGenerated(true);
      setSuggestions([]);
      if (run.status === "completed") {
        setSuggestions(run.suggestions as TestCaseSuggestion[]);
        setSugLoading(false);
      } else if (run.status === "failed") {
        setSugLoading(false);
        toast.error("Failed to generate suggestions", {
          description: run.error || "Unknown error",
        });
      }
      // pending/running → polling effect takes over.
    } catch (err: any) {
      toast.error("Failed to generate suggestions", { description: err.message });
      setSugLoading(false);
    }
  }, [sugFilter, globalFilters.startDate, globalFilters.endDate, globalFilters.environment, globalFilters.userFilterMode, globalFilters.filteredUsers]);

  const loadLatestSuggestions = useCallback(async () => {
    setSugLoading(true);
    try {
      const [run, dsData] = await Promise.all([
        getLatestSuggestions().catch(() => null),
        getDatasets().catch(() => null),
      ]);
      if (dsData) setDatasets(dsData.data);
      if (!run) {
        setSugLoading(false);
        return;
      }
      setSuggestionRun(run);
      if (run.status === "completed") {
        setSuggestions(run.suggestions as TestCaseSuggestion[]);
        setSugGenerated(run.count > 0);
        setSugLoading(false);
      } else if (run.status === "failed" || run.status === "cancelled") {
        setSuggestions([]);
        setSugLoading(false);
      } else {
        // pending/running: the polling effect picks it up and clears loading.
        // Surface live progress by jumping straight to the results view.
        setDerivedView("results");
      }
    } catch {
      setSugLoading(false);
    }
  }, [setDerivedView]);

  // Polling loop for suggestion run progress
  useEffect(() => {
    if (!suggestionRun || !["pending", "running"].includes(suggestionRun.status)) return;
    const runId = suggestionRun.id;
    const interval = setInterval(async () => {
      try {
        const updated = await getSuggestionRun(runId);
        setSuggestionRun(updated);
        if (updated.status === "completed") {
          clearInterval(interval);
          setSuggestions(updated.suggestions as TestCaseSuggestion[]);
          setSugGenerated(updated.count > 0);
          setSugLoading(false);
        } else if (updated.status === "failed") {
          clearInterval(interval);
          setSugLoading(false);
          toast.error("Failed to generate suggestions", {
            description: updated.error || "Unknown error",
          });
        } else if (updated.status === "cancelled") {
          clearInterval(interval);
          setSugLoading(false);
        }
      } catch {
        clearInterval(interval);
        setSugLoading(false);
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [suggestionRun?.id, suggestionRun?.status]);

  async function handleStopSuggestionRun() {
    if (!suggestionRun || !["pending", "running"].includes(suggestionRun.status)) return;
    try {
      const updated = await stopSuggestionRun(suggestionRun.id);
      setSuggestionRun(updated);
      setSugLoading(false);
      toast.success("Generation stopped");
    } catch (err: any) {
      toast.error("Failed to stop generation", { description: err.message });
    }
  }

  async function handleAcceptSuggestion(datasetId: string, form: TestCaseFormData) {
    if (!selectedSuggestion) return;
    setSaving(true);
    try {
      const config = form.config_json.trim()
        ? JSON.parse(form.config_json) as Record<string, unknown>
        : {};

      const {
        team_filter, tag_filter, expected_sources,
        expected_page_urls, expected_source_types,
        max_answer_length, context_filters,
        ...extraMetadata
      } = config;

      const body: TestCaseCreateBody = {
        test_id: form.test_id,
        prompt: form.prompt,
        expected_answer: form.expected_answer || undefined,
        team_filter: (team_filter as string[]) || [],
        tag_filter: (tag_filter as string[]) || [],
        expected_sources: (expected_sources as string[]) || [],
        expected_page_urls: (expected_page_urls as string[]) || [],
        expected_source_types: (expected_source_types as string[]) || [],
        max_answer_length: (max_answer_length as number) ?? null,
        context_filters: (context_filters as Record<string, string>) || selectedSuggestion.context_filters,
        metadata: Object.keys(extraMetadata).length > 0 ? extraMetadata : {},
        source_feedback_id: selectedSuggestion.feedback_id,
        source_trace_id: selectedSuggestion.trace_id || undefined,
        message_count: selectedSuggestion.message_count ?? undefined,
        has_summary: selectedSuggestion.has_summary,
      };
      const created = await acceptSuggestion(datasetId, body);
      const removedSuggestion = selectedSuggestion;
      setSuggestions((prev) => prev.filter((s) => s.feedback_id !== removedSuggestion.feedback_id));
      setSelectedSuggestion(null);
      toast.success("Test case added to dataset", {
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await deleteTestCase(datasetId, created.id);
              setSuggestions((prev) =>
                prev.some((s) => s.feedback_id === removedSuggestion.feedback_id)
                  ? prev
                  : [removedSuggestion, ...prev],
              );
              toast.success("Test case removed");
            } catch (err: any) {
              toast.error("Failed to undo", { description: err.message });
            }
          },
        },
      });
    } catch (err: any) {
      toast.error("Failed to add test case", { description: err.message });
    } finally {
      setSaving(false);
    }
  }

  return {
    suggestions,
    sugLoading,
    sugGenerated,
    sugFilter,
    setSugFilter,
    datasets,
    selectedSuggestion,
    setSelectedSuggestion,
    saving,
    suggestionRun,
    loadSuggestions,
    loadLatestSuggestions,
    handleStopSuggestionRun,
    handleAcceptSuggestion,
  };
}
