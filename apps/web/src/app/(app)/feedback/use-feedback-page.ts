"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  getFeedback,
  getFeedbackStats,
  importFeedback,
  generateSuggestions,
  getLatestSuggestions,
  acceptSuggestion,
  getDatasets,
  type FeedbackScoreItem,
  type FeedbackStatsResponse,
  type FeedbackListResponse,
  type FeedbackEvaluateResponse,
  type FeedbackEvaluatorConfig,
  type TestCaseSuggestion,
  type TestDatasetItem,
  type TestCaseCreateBody,
} from "@/lib/api";
import { evaluateFeedback, getFeedbackEvaluation, stopFeedbackEvaluation, getFeedbackEvaluatorConfig, updateFeedbackEvaluatorConfig } from "@/lib/api/feedback-api";
import { analyzeTopQuestions, getTopQuestionsAnalysis, getLatestTopQuestions, stopTopQuestionsAnalysis, analyzeFeedbackThemes, getFeedbackThemesAnalysis, getLatestFeedbackThemes, stopFeedbackThemesAnalysis, getSuggestionRun, stopSuggestionRun } from "@/lib/api/evals-api";
import type { TopQuestionsResponse, FeedbackThemesResponse, SuggestionRunResponse } from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import type { TestCaseFormData } from "../datasets/[id]/test-case-modal";

type Tab = "feedback" | "suggestions" | "top-questions" | "themes";

export function useFeedbackPage() {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("feedback-tab");
      if (saved === "feedback" || saved === "suggestions" || saved === "top-questions" || saved === "themes") return saved as Tab;
    }
    return "feedback";
  });
  const [stats, setStats] = useState<FeedbackStatsResponse | null>(null);
  const [feedbackResp, setFeedbackResp] = useState<FeedbackListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [filterValue, setFilterValue] = useState<string>("all");
  const [filterVerdict, setFilterVerdict] = useState<string>("all");
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const globalFilters = useGlobalFilters();

  // Suggestions state
  const [suggestions, setSuggestions] = useState<TestCaseSuggestion[]>([]);
  const [sugLoading, setSugLoading] = useState(false);
  const [sugGenerated, setSugGenerated] = useState(false);
  const [sugFilter, setSugFilter] = useState<"all" | "positive" | "negative">("all");
  const [datasets, setDatasets] = useState<TestDatasetItem[]>([]);
  const [selectedSuggestion, setSelectedSuggestion] = useState<TestCaseSuggestion | null>(null);
  const [saving, setSaving] = useState(false);
  const [suggestionRun, setSuggestionRun] = useState<SuggestionRunResponse | null>(null);

  // Feedback evaluation state
  const [evalResult, setEvalResult] = useState<FeedbackEvaluateResponse | null>(null);
  const [evalId, setEvalId] = useState<string | null>(null);
  const [evalTriggering, setEvalTriggering] = useState(false);

  // Feedback evaluator config state
  const [evalConfig, setEvalConfig] = useState<FeedbackEvaluatorConfig | null>(null);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);

  // Detail modal state
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackScoreItem | null>(null);

  // Reevaluate toggle
  const [reevaluate, setReevaluate] = useState(false);

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

  const evalRunning = evalResult ? ["pending", "running"].includes(evalResult.status) : false;
  const configuredVerdicts = evalConfig?.verdicts ?? ["suspicious", "helpful", "unhelpful"];

  // Load feedback evaluator config
  useEffect(() => {
    getFeedbackEvaluatorConfig()
      .then(setEvalConfig)
      .catch(() => {});
  }, []);

  async function handleSaveConfig(data: { prompt: string; verdicts: string[]; default_verdict: string; model: string | null }) {
    setConfigSaving(true);
    try {
      const updated = await updateFeedbackEvaluatorConfig(data);
      setEvalConfig(updated);
      setShowConfigModal(false);
      toast.success("Evaluator config saved");
    } catch (err: any) {
      toast.error("Failed to save config", { description: err.message });
    } finally {
      setConfigSaving(false);
    }
  }

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

  async function handleStop() {
    if (!evalId) return;
    try {
      await stopFeedbackEvaluation(evalId);
      setEvalResult(null);
      setEvalId(null);
      toast.success("Evaluation stopped");
      loadFeedback();
    } catch (err: any) {
      toast.error("Failed to stop", { description: err.message });
    }
  }

  async function handleEvaluate() {
    setEvalTriggering(true);
    try {
      const body: Record<string, unknown> = { limit: 50, reevaluate };
      if (globalFilters.startDate) body.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) body.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.environment && globalFilters.environment !== "all") {
        body.environment = globalFilters.environment;
      }
      const { evaluation_id } = await evaluateFeedback(body as any);
      setEvalId(evaluation_id);
      const data = await getFeedbackEvaluation(evaluation_id);
      setEvalResult(data);
    } catch (err: any) {
      toast.error("Evaluation failed", { description: err.message });
    } finally {
      setEvalTriggering(false);
    }
  }

  const topQuestionsRunning = topQuestionsResult ? ["pending", "running"].includes(topQuestionsResult.status) : false;

  async function handleAnalyzeTopQuestions() {
    setTopQuestionsTriggering(true);
    try {
      const body: Record<string, unknown> = { limit: 200 };
      if (globalFilters.startDate) body.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) body.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.environment && globalFilters.environment !== "all") {
        body.environment = globalFilters.environment;
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

  const feedbackThemesRunning = feedbackThemesResult ? ["pending", "running"].includes(feedbackThemesResult.status) : false;

  async function handleAnalyzeFeedbackThemes() {
    setFeedbackThemesTriggering(true);
    try {
      const body: Record<string, unknown> = { limit: 200 };
      if (globalFilters.startDate) body.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) body.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.environment && globalFilters.environment !== "all") {
        body.environment = globalFilters.environment;
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

  // Eval completion flag — triggers feedback list refresh
  const [evalCompleted, setEvalCompleted] = useState(0);

  // Polling loop for feedback evaluation progress
  useEffect(() => {
    if (!evalId || !evalResult || !["pending", "running"].includes(evalResult.status)) return;
    const interval = setInterval(async () => {
      try {
        const updated = await getFeedbackEvaluation(evalId);
        setEvalResult(updated);
        if (updated.status === "completed") {
          clearInterval(interval);
          const vc = updated.summary.verdict_counts ?? {};
          const parts = Object.entries(vc).map(([k, v]) => `${v} ${k}`);
          toast.success(`Evaluated ${updated.summary.evaluated_count} items`, {
            description: parts.join(", "),
          });
          // Trigger feedback list refresh
          setEvalCompleted((c) => c + 1);
        } else if (updated.status === "failed") {
          clearInterval(interval);
          toast.error("Evaluation failed", { description: updated.error || "Unknown error" });
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [evalId, evalResult?.status]);

  const loadFeedback = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        page: String(page),
        per_page: "30",
      };

      if (tab === "feedback") {
        params.score_name = "user-feedback";
        if (filterValue === "positive") params.value = "1";
        else if (filterValue === "negative") params.value = "0";
        if (filterVerdict !== "all") params.verdict = filterVerdict;
      }

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

  const loadSuggestions = useCallback(async () => {
    setSugLoading(true);
    try {
      const params: Record<string, string> = {
        feedback_type: sugFilter,
        limit: "100",
      };
      if (globalFilters.startDate) params.from_date = new Date(globalFilters.startDate).toISOString();
      if (globalFilters.endDate) params.to_date = new Date(globalFilters.endDate).toISOString();
      if (globalFilters.environment && globalFilters.environment !== "all") {
        params.environment = globalFilters.environment;
      }
      if (globalFilters.filteredUsers.length > 0) {
        const key = globalFilters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
        params[key] = globalFilters.filteredUsers.join(",");
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

  const loadTopQuestions = useCallback(async () => {
    setTopQuestionsLoading(true);
    try {
      const data = await getLatestTopQuestions();
      setTopQuestionsResult(data);
      // Resume polling if the latest analysis is still in progress.
      if (["pending", "running"].includes(data.status)) setTopQuestionsId(data.id);
    } catch {
      // No previous analysis found — that's fine
      setTopQuestionsResult(null);
    } finally {
      setTopQuestionsLoading(false);
    }
  }, []);

  const loadFeedbackThemes = useCallback(async () => {
    setFeedbackThemesLoading(true);
    try {
      const data = await getLatestFeedbackThemes();
      setFeedbackThemesResult(data);
      // Resume polling if the latest analysis is still in progress.
      if (["pending", "running"].includes(data.status)) setFeedbackThemesId(data.id);
    } catch {
      // No previous analysis found — that's fine
      setFeedbackThemesResult(null);
    } finally {
      setFeedbackThemesLoading(false);
    }
  }, []);

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
      }
      // If pending/running, the polling effect picks it up and clears loading.
    } catch {
      setSugLoading(false);
    }
  }, []);

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

  useEffect(() => {
    if (tab === "suggestions") {
      loadLatestSuggestions();
      return;
    }
    if (tab === "top-questions") {
      loadTopQuestions();
    } else if (tab === "themes") {
      loadFeedbackThemes();
    } else {
      loadFeedback();
    }
  }, [tab, loadFeedback, loadTopQuestions, loadFeedbackThemes, loadLatestSuggestions]);

  // Saved suggestion runs persist across filter changes — wiping them on every
  // filter tweak would defeat the persistence the user expects, and racing
  // against the async traceNames fetch was wiping freshly-loaded suggestions.
  // Users regenerate explicitly when they want fresh data for new filters.

  useEffect(() => {
    setPage(1);
  }, [tab, filterValue, filterVerdict, globalFilters.startDate, globalFilters.endDate, globalFilters.environment, globalFilters.userFilterMode, globalFilters.filteredUsers, globalFilters.traceNames]);

  useEffect(() => {
    localStorage.setItem("feedback-tab", tab);
  }, [tab]);

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
      await acceptSuggestion(datasetId, body);
      toast.success("Test case added to dataset");
      setSuggestions((prev) => prev.filter((s) => s.feedback_id !== selectedSuggestion.feedback_id));
      setSelectedSuggestion(null);
    } catch (err: any) {
      toast.error("Failed to add test case", { description: err.message });
    } finally {
      setSaving(false);
    }
  }

  const tabClass = (t: Tab) =>
    `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
      tab === t
        ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
        : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
    }`;

  return {
    // State
    tab, setTab,
    stats,
    feedbackResp, setFeedbackResp,
    loading,
    page, setPage,
    filterValue, setFilterValue,
    filterVerdict, setFilterVerdict,
    hoveredBar, setHoveredBar,
    fileInputRef,
    suggestions,
    sugLoading,
    sugGenerated,
    sugFilter, setSugFilter,
    suggestionRun,
    datasets,
    selectedSuggestion, setSelectedSuggestion,
    saving,
    evalResult,
    evalTriggering,
    evalConfig,
    showConfigModal, setShowConfigModal,
    configSaving,
    selectedFeedback, setSelectedFeedback,
    reevaluate, setReevaluate,
    topQuestionsResult,
    topQuestionsLoading,
    topQuestionsTriggering,
    topQuestionsRunning,
    feedbackThemesResult,
    feedbackThemesLoading,
    feedbackThemesTriggering,
    feedbackThemesRunning,
    // Computed
    evalRunning,
    configuredVerdicts,
    tabClass,
    // Handlers
    handleSaveConfig,
    handleImport,
    handleStop,
    handleEvaluate,
    handleAcceptSuggestion,
    handleAnalyzeTopQuestions,
    handleStopTopQuestions,
    handleAnalyzeFeedbackThemes,
    handleStopFeedbackThemes,
    handleGenerateSuggestions: loadSuggestions,
    handleStopSuggestionRun,
  };
}
