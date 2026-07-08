"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  getFeedback,
  getFeedbackStats,
  importFeedback,
  type FeedbackStatsResponse,
  type FeedbackListResponse,
} from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";

export type Tab = "feedback" | "suggestions" | "top-questions" | "themes" | "failure-modes";

// Backend caps a hand-picked selection at 200 ids (see generate_suggestions),
// and the list endpoint allows per_page up to 200 — so one request covers the
// whole selectable range.
export const MAX_SELECTABLE = 200;

// `tab` and `evalCompleted` belong to other hooks but feed this hook's load
// dependencies, so they are threaded in explicitly.
export function useFeedbackList(tab: Tab, evalCompleted: number) {
  const [stats, setStats] = useState<FeedbackStatsResponse | null>(null);
  const [feedbackResp, setFeedbackResp] = useState<FeedbackListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [filterValue, setFilterValue] = useState<string>("all");
  const [filterVerdict, setFilterVerdict] = useState<string>("all");
  const [selectedFeedbackIds, setSelectedFeedbackIds] = useState<Set<string>>(new Set());
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const globalFilters = useGlobalFilters();

  const loadFeedback = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        page: String(page),
        per_page: "30",
      };

      // The feedback table backs the source picker on every tab, so always
      // scope to user-feedback and apply the value/verdict filters.
      params.score_name = "user-feedback";
      if (filterValue === "positive") params.value = "1";
      else if (filterValue === "negative") params.value = "0";
      if (filterVerdict !== "all") params.verdict = filterVerdict;

      if (globalFilters.environment && globalFilters.environment !== "all") {
        params.environment = globalFilters.environment;
      }
      if (globalFilters.startDate) params.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) params.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.filteredUsers.length > 0) {
        const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
        params[key] = globalFilters.filteredUsers.join(",");
      }

      const statsParams: Record<string, string> = {};
      // Mirror the table's value/verdict filters so the KPI cards and trend
      // chart above the table reflect the same subset.
      if (filterValue === "positive") statsParams.value = "1";
      else if (filterValue === "negative") statsParams.value = "0";
      if (filterVerdict !== "all") statsParams.verdict = filterVerdict;
      if (globalFilters.startDate) statsParams.start_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) statsParams.end_date = new Date(globalFilters.endDate).toISOString();
      if (!globalFilters.startDate) statsParams.days = "30";
      if (globalFilters.environment && globalFilters.environment !== "all") statsParams.environment = globalFilters.environment;
      if (globalFilters.filteredUsers.length > 0) {
        const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
        statsParams[key] = globalFilters.filteredUsers.join(",");
      }

      const [feedbackData, statsData] = await Promise.all([
        getFeedback(params),
        getFeedbackStats(statsParams),
      ]);
      setFeedbackResp(feedbackData);
      setStats(statsData);
    } catch (e) {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, filterValue, filterVerdict, globalFilters.startDate, globalFilters.endDate, globalFilters.environment, globalFilters.userFilterMode, globalFilters.filteredUsers, globalFilters.traceNames, tab, evalCompleted]);

  const toggleFeedbackId = useCallback((id: string, checked: boolean) => {
    setSelectedFeedbackIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const setPageSelection = useCallback((ids: string[], checked: boolean) => {
    setSelectedFeedbackIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  const clearSelectedFeedback = useCallback(() => setSelectedFeedbackIds(new Set()), []);

  // Select every feedback row matching the current filters across all pages,
  // not just the page in view. Capped at MAX_SELECTABLE to match the backend.
  const [selectingAll, setSelectingAll] = useState(false);
  const selectAllMatching = useCallback(async () => {
    setSelectingAll(true);
    try {
      const params: Record<string, string> = {
        page: "1",
        per_page: String(MAX_SELECTABLE),
        score_name: "user-feedback",
      };
      if (filterValue === "positive") params.value = "1";
      else if (filterValue === "negative") params.value = "0";
      if (filterVerdict !== "all") params.verdict = filterVerdict;
      if (globalFilters.environment && globalFilters.environment !== "all") {
        params.environment = globalFilters.environment;
      }
      if (globalFilters.startDate) params.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) params.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.filteredUsers.length > 0) {
        const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
        params[key] = globalFilters.filteredUsers.join(",");
      }
      const resp = await getFeedback(params);
      const ids = resp.data.map((i) => String(i.id));
      setSelectedFeedbackIds(new Set(ids));
      if (resp.pagination.total > ids.length) {
        toast.info(
          `Selected the first ${ids.length} of ${resp.pagination.total} matching items (max ${MAX_SELECTABLE}).`,
        );
      }
    } catch (err: any) {
      toast.error("Failed to select all matching", { description: err.message });
    } finally {
      setSelectingAll(false);
    }
  }, [filterValue, filterVerdict, globalFilters.environment, globalFilters.startDate, globalFilters.endDate, globalFilters.filteredUsers, globalFilters.userFilterMode]);

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const json = JSON.parse(text);
      const scores = Array.isArray(json) ? json : json.scores || [];
      await importFeedback({ scores, filename: file.name });
      toast.success("Feedback imported successfully");
      loadFeedback();
    } catch (err: any) {
      toast.error("Import failed", { description: err.message });
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // The feedback table backs the source picker on every tab, so load it
  // regardless of which tab is active.
  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  // Reset to page 1 whenever the active tab or any filter changes.
  useEffect(() => {
    setPage(1);
  }, [tab, filterValue, filterVerdict, globalFilters.startDate, globalFilters.endDate, globalFilters.environment, globalFilters.userFilterMode, globalFilters.filteredUsers, globalFilters.traceNames]);

  return {
    stats,
    feedbackResp,
    setFeedbackResp,
    loading,
    page,
    setPage,
    filterValue,
    setFilterValue,
    filterVerdict,
    setFilterVerdict,
    selectedFeedbackIds,
    hoveredBar,
    setHoveredBar,
    fileInputRef,
    loadFeedback,
    toggleFeedbackId,
    setPageSelection,
    clearSelectedFeedback,
    selectAllMatching,
    selectingAll,
    handleImport,
  };
}
