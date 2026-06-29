"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  analyzeTopQuestions,
  getTopQuestionsAnalysis,
  getLatestTopQuestions,
  stopTopQuestionsAnalysis,
  analyzeFeedbackThemes,
  getFeedbackThemesAnalysis,
  getLatestFeedbackThemes,
  stopFeedbackThemesAnalysis,
} from "@/lib/api/evals-api";
import type { TopQuestionsResponse, FeedbackThemesResponse } from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";

// `setDerivedView` is owned by the compose hook; the loaders jump to the
// results view when an analysis is already in progress, so it is threaded in.
export function useFeedbackDerived(setDerivedView: (v: "picker" | "results") => void) {
  const globalFilters = useGlobalFilters();

  // Top questions state
  const [topQuestionsResult, setTopQuestionsResult] = useState<TopQuestionsResponse | null>(null);
  const [topQuestionsId, setTopQuestionsId] = useState<string | null>(null);
  const [topQuestionsTriggering, setTopQuestionsTriggering] = useState(false);
  const [topQuestionsLoading, setTopQuestionsLoading] = useState(false);

  // Feedback themes state
  const [feedbackThemesResult, setFeedbackThemesResult] = useState<FeedbackThemesResponse | null>(null);
  const [feedbackThemesId, setFeedbackThemesId] = useState<string | null>(null);
  const [feedbackThemesTriggering, setFeedbackThemesTriggering] = useState(false);
  const [feedbackThemesLoading, setFeedbackThemesLoading] = useState(false);

  const topQuestionsRunning = topQuestionsResult ? ["pending", "running"].includes(topQuestionsResult.status) : false;

  async function handleAnalyzeTopQuestions(ids?: string[]) {
    setTopQuestionsTriggering(true);
    try {
      const body: Record<string, unknown> = { limit: 200 };
      if (ids && ids.length > 0) {
        // Hand-picked feedback: the selection IS the filter, so the
        // date/environment params are intentionally omitted.
        body.selected_feedback_ids = ids;
      } else {
        if (globalFilters.startDate) body.from_date = new Date(globalFilters.startDate).toISOString();
        if (globalFilters.endDate) body.to_date = new Date(globalFilters.endDate).toISOString();
        if (globalFilters.environment && globalFilters.environment !== "all") {
          body.environment = globalFilters.environment;
        }
      }
      const { analysis_id } = await analyzeTopQuestions(body as any);
      setTopQuestionsId(analysis_id);
      const data = await getTopQuestionsAnalysis(analysis_id);
      setTopQuestionsResult(data);
    } catch (err: any) {
      toast.error("Analysis failed", { description: err.message });
    } finally {
      setTopQuestionsTriggering(false);
    }
  }

  async function handleStopTopQuestions() {
    if (!topQuestionsId || !topQuestionsRunning) return;
    try {
      await stopTopQuestionsAnalysis(topQuestionsId);
      setTopQuestionsResult((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
      toast.success("Analysis stopped");
    } catch (err: any) {
      toast.error("Failed to stop analysis", { description: err.message });
    }
  }

  // Polling loop for top questions analysis progress
  useEffect(() => {
    if (!topQuestionsId || !topQuestionsResult || !["pending", "running"].includes(topQuestionsResult.status)) return;
    const interval = setInterval(async () => {
      try {
        const updated = await getTopQuestionsAnalysis(topQuestionsId);
        setTopQuestionsResult(updated);
        if (updated.status === "completed") {
          clearInterval(interval);
          toast.success(`Identified ${updated.themes.length} question themes from ${updated.total_questions} questions`);
        } else if (updated.status === "failed") {
          clearInterval(interval);
          toast.error("Analysis failed", { description: updated.error || "Unknown error" });
        } else if (updated.status === "cancelled") {
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [topQuestionsId, topQuestionsResult?.status]);

  const loadTopQuestions = useCallback(async () => {
    setTopQuestionsLoading(true);
    try {
      const data = await getLatestTopQuestions();
      setTopQuestionsResult(data);
      // Resume polling if the latest analysis is still in progress, and surface
      // the live progress by jumping straight to the results view.
      if (["pending", "running"].includes(data.status)) {
        setTopQuestionsId(data.id);
        setDerivedView("results");
      }
    } catch {
      // No previous analysis found — that's fine
      setTopQuestionsResult(null);
    } finally {
      setTopQuestionsLoading(false);
    }
  }, [setDerivedView]);

  const feedbackThemesRunning = feedbackThemesResult ? ["pending", "running"].includes(feedbackThemesResult.status) : false;

  async function handleAnalyzeFeedbackThemes(ids?: string[]) {
    setFeedbackThemesTriggering(true);
    try {
      const body: Record<string, unknown> = { limit: 200 };
      if (ids && ids.length > 0) {
        // Hand-picked feedback: the selection IS the filter, so the
        // date/environment params are intentionally omitted.
        body.selected_feedback_ids = ids;
      } else {
        if (globalFilters.startDate) body.from_date = new Date(globalFilters.startDate).toISOString();
        if (globalFilters.endDate) body.to_date = new Date(globalFilters.endDate).toISOString();
        if (globalFilters.environment && globalFilters.environment !== "all") {
          body.environment = globalFilters.environment;
        }
      }
      const { analysis_id } = await analyzeFeedbackThemes(body as any);
      setFeedbackThemesId(analysis_id);
      const data = await getFeedbackThemesAnalysis(analysis_id);
      setFeedbackThemesResult(data);
    } catch (err: any) {
      toast.error("Analysis failed", { description: err.message });
    } finally {
      setFeedbackThemesTriggering(false);
    }
  }

  async function handleStopFeedbackThemes() {
    if (!feedbackThemesId || !feedbackThemesRunning) return;
    try {
      await stopFeedbackThemesAnalysis(feedbackThemesId);
      setFeedbackThemesResult((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
      toast.success("Analysis stopped");
    } catch (err: any) {
      toast.error("Failed to stop analysis", { description: err.message });
    }
  }

  // Polling loop for feedback themes analysis progress
  useEffect(() => {
    if (!feedbackThemesId || !feedbackThemesResult || !["pending", "running"].includes(feedbackThemesResult.status)) return;
    const interval = setInterval(async () => {
      try {
        const updated = await getFeedbackThemesAnalysis(feedbackThemesId);
        setFeedbackThemesResult(updated);
        if (updated.status === "completed") {
          clearInterval(interval);
          toast.success(`Identified ${updated.themes.length} themes from ${updated.total_comments} comments`);
        } else if (updated.status === "failed") {
          clearInterval(interval);
          toast.error("Analysis failed", { description: updated.error || "Unknown error" });
        } else if (updated.status === "cancelled") {
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [feedbackThemesId, feedbackThemesResult?.status]);

  const loadFeedbackThemes = useCallback(async () => {
    setFeedbackThemesLoading(true);
    try {
      const data = await getLatestFeedbackThemes();
      setFeedbackThemesResult(data);
      // Resume polling if the latest analysis is still in progress, and surface
      // the live progress by jumping straight to the results view.
      if (["pending", "running"].includes(data.status)) {
        setFeedbackThemesId(data.id);
        setDerivedView("results");
      }
    } catch {
      // No previous analysis found — that's fine
      setFeedbackThemesResult(null);
    } finally {
      setFeedbackThemesLoading(false);
    }
  }, [setDerivedView]);

  return {
    topQuestionsResult,
    topQuestionsLoading,
    topQuestionsTriggering,
    topQuestionsRunning,
    feedbackThemesResult,
    feedbackThemesLoading,
    feedbackThemesTriggering,
    feedbackThemesRunning,
    handleAnalyzeTopQuestions,
    handleStopTopQuestions,
    handleAnalyzeFeedbackThemes,
    handleStopFeedbackThemes,
    loadTopQuestions,
    loadFeedbackThemes,
  };
}
