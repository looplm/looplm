"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useFeedbackList, MAX_SELECTABLE, type Tab } from "./use-feedback-list";
import { useFeedbackEvaluation } from "./use-feedback-evaluation";
import { useFeedbackSuggestions } from "./use-feedback-suggestions";
import { useFeedbackDerived } from "./use-feedback-derived";

type DerivedView = "picker" | "results";
type GenerateOutput = "suggestions" | "top-questions" | "themes";

export function useFeedbackPage() {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("feedback-tab");
      if (saved === "feedback" || saved === "suggestions" || saved === "top-questions" || saved === "themes") return saved as Tab;
    }
    return "feedback";
  });
  // Derived tabs (suggestions/top-questions/themes) are a two-step flow:
  // "picker" (select source feedback) → "results". The User Feedback tab
  // ignores this. Reset to "picker" on every tab switch (decision: always
  // start at the picker), except when a generate action jumps straight to
  // "results" — those set the view explicitly without going through selectTab.
  const [derivedView, setDerivedView] = useState<DerivedView>("picker");

  // When we programmatically switch to a derived tab to start a run from a
  // selection, the tab-change effect must NOT also load that tab's latest run —
  // that would race with and clobber the freshly-kicked-off run. Holds the tab
  // whose latest-load should be skipped exactly once.
  const skipLatestForTabRef = useRef<Tab | null>(null);

  // Evaluation owns the eval-completed counter, which feeds the list hook's
  // loadFeedback deps; declare it before the list hook to avoid a TDZ ref.
  const evaluation = useFeedbackEvaluation(loadFeedbackProxy);
  const list = useFeedbackList(tab, evaluation.evalCompleted);
  const suggestions = useFeedbackSuggestions(setDerivedView);
  const derived = useFeedbackDerived(setDerivedView);

  // The evaluation hook needs to refresh the feedback table on stop/completion,
  // but the list hook (which owns loadFeedback) is declared after it. Bridge the
  // call through a ref-backed proxy that always points at the latest loader.
  const loadFeedbackRef = useRef(list.loadFeedback);
  useEffect(() => {
    loadFeedbackRef.current = list.loadFeedback;
  }, [list.loadFeedback]);
  function loadFeedbackProxy() {
    loadFeedbackRef.current();
  }

  // Switch tabs from the nav. Always returns derived tabs to their picker step.
  const selectTab = useCallback((t: Tab) => {
    setTab(t);
    setDerivedView("picker");
  }, []);

  // Generate any of the three outputs from the current feedback selection
  // (or, when nothing is selected, the current filters). Jumps to the target
  // tab's results view and kicks off the run. Plain function (not memoized) so
  // it always closes over the latest filter-aware analyze handlers.
  function handleGenerateFrom(output: GenerateOutput, idsOverride?: string[]) {
    const ids = idsOverride ?? (list.selectedFeedbackIds.size > 0 ? Array.from(list.selectedFeedbackIds) : undefined);
    skipLatestForTabRef.current = output;
    setTab(output);
    setDerivedView("results");
    if (output === "suggestions") {
      suggestions.loadSuggestions(ids);
    } else if (output === "top-questions") {
      derived.handleAnalyzeTopQuestions(ids);
    } else {
      derived.handleAnalyzeFeedbackThemes(ids);
    }
  }

  // Load the latest saved run for the active derived tab — unless a generate
  // action just kicked off a fresh run for it (skipLatestForTabRef), which
  // would otherwise race with and clobber that run.
  useEffect(() => {
    if (tab === "feedback") return;
    if (skipLatestForTabRef.current === tab) {
      skipLatestForTabRef.current = null;
      return;
    }
    if (tab === "suggestions") suggestions.loadLatestSuggestions();
    else if (tab === "top-questions") derived.loadTopQuestions();
    else if (tab === "themes") derived.loadFeedbackThemes();
  }, [tab, derived.loadTopQuestions, derived.loadFeedbackThemes, suggestions.loadLatestSuggestions]);

  // Saved suggestion runs persist across filter changes — wiping them on every
  // filter tweak would defeat the persistence the user expects, and racing
  // against the async traceNames fetch was wiping freshly-loaded suggestions.
  // Users regenerate explicitly when they want fresh data for new filters.

  useEffect(() => {
    localStorage.setItem("feedback-tab", tab);
  }, [tab]);

  const tabClass = (t: Tab) =>
    `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
      tab === t
        ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
        : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
    }`;

  return {
    // State
    tab, setTab, selectTab,
    derivedView, setDerivedView,
    stats: list.stats,
    feedbackResp: list.feedbackResp, setFeedbackResp: list.setFeedbackResp,
    loading: list.loading,
    page: list.page, setPage: list.setPage,
    filterValue: list.filterValue, setFilterValue: list.setFilterValue,
    filterVerdict: list.filterVerdict, setFilterVerdict: list.setFilterVerdict,
    selectedFeedbackIds: list.selectedFeedbackIds,
    hoveredBar: list.hoveredBar, setHoveredBar: list.setHoveredBar,
    fileInputRef: list.fileInputRef,
    suggestions: suggestions.suggestions,
    sugLoading: suggestions.sugLoading,
    sugGenerated: suggestions.sugGenerated,
    sugFilter: suggestions.sugFilter, setSugFilter: suggestions.setSugFilter,
    suggestionRun: suggestions.suggestionRun,
    datasets: suggestions.datasets,
    selectedSuggestion: suggestions.selectedSuggestion, setSelectedSuggestion: suggestions.setSelectedSuggestion,
    saving: suggestions.saving,
    evalResult: evaluation.evalResult,
    evalTriggering: evaluation.evalTriggering,
    evalConfig: evaluation.evalConfig,
    showConfigModal: evaluation.showConfigModal, setShowConfigModal: evaluation.setShowConfigModal,
    configSaving: evaluation.configSaving,
    selectedFeedback: evaluation.selectedFeedback, setSelectedFeedback: evaluation.setSelectedFeedback,
    reevaluate: evaluation.reevaluate, setReevaluate: evaluation.setReevaluate,
    topQuestionsResult: derived.topQuestionsResult,
    topQuestionsLoading: derived.topQuestionsLoading,
    topQuestionsTriggering: derived.topQuestionsTriggering,
    topQuestionsRunning: derived.topQuestionsRunning,
    feedbackThemesResult: derived.feedbackThemesResult,
    feedbackThemesLoading: derived.feedbackThemesLoading,
    feedbackThemesTriggering: derived.feedbackThemesTriggering,
    feedbackThemesRunning: derived.feedbackThemesRunning,
    // Computed
    evalRunning: evaluation.evalRunning,
    configuredVerdicts: evaluation.configuredVerdicts,
    tabClass,
    // Handlers
    handleSaveConfig: evaluation.handleSaveConfig,
    handleImport: list.handleImport,
    handleStop: evaluation.handleStop,
    handleEvaluate: evaluation.handleEvaluate,
    handleAcceptSuggestion: suggestions.handleAcceptSuggestion,
    handleAnalyzeTopQuestions: derived.handleAnalyzeTopQuestions,
    handleStopTopQuestions: derived.handleStopTopQuestions,
    handleAnalyzeFeedbackThemes: derived.handleAnalyzeFeedbackThemes,
    handleStopFeedbackThemes: derived.handleStopFeedbackThemes,
    handleGenerateSuggestions: suggestions.loadSuggestions,
    handleStopSuggestionRun: suggestions.handleStopSuggestionRun,
    toggleFeedbackId: list.toggleFeedbackId,
    setPageSelection: list.setPageSelection,
    clearSelectedFeedback: list.clearSelectedFeedback,
    selectAllMatching: list.selectAllMatching,
    selectingAll: list.selectingAll,
    maxSelectable: MAX_SELECTABLE,
    handleGenerateFrom,
  };
}
