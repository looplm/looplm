"use client";

import { FeedbackEvaluatorModal } from "./feedback-evaluator-modal";
import { FeedbackDetailModal } from "./feedback-detail-modal";
import { StatCard } from "@/components/eval-shared";
import { TrendBarChart } from "./feedback-chart";
import { SuggestionsTab } from "./suggestions-tab";
import { TopQuestionsTab } from "./top-questions-tab";
import { FeedbackThemesTab } from "./feedback-themes-tab";
import { FeedbackSourcePicker } from "./feedback-source-picker";
import { useFeedbackPage } from "./use-feedback-page";
import { downloadTopQuestionsPdf } from "./top-questions-pdf";
import { toast } from "sonner";
import { usePermissions } from "@/components/permissions-context";

const FEEDBACK_READ_ONLY_TITLE = "Read-only access. Ask an admin to grant write permission.";

export default function FeedbackPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("feedback");
  const {
    tab, selectTab,
    derivedView, setDerivedView,
    stats,
    feedbackResp, setFeedbackResp,
    loading,
    page, setPage,
    filterValue, setFilterValue,
    filterVerdict, setFilterVerdict,
    selectedFeedbackIds,
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
    topQuestionsRunning,
    topQuestionsTriggering,
    feedbackThemesResult,
    feedbackThemesLoading,
    feedbackThemesRunning,
    feedbackThemesTriggering,
    evalRunning,
    configuredVerdicts,
    tabClass,
    handleSaveConfig,
    handleImport,
    handleStop,
    handleEvaluate,
    handleAcceptSuggestion,
    handleStopTopQuestions,
    handleStopFeedbackThemes,
    handleGenerateSuggestions,
    handleStopSuggestionRun,
    toggleFeedbackId,
    setPageSelection,
    clearSelectedFeedback,
    selectAllMatching,
    selectingAll,
    maxSelectable,
    handleGenerateFrom,
  } = useFeedbackPage();

  const isDerivedTab = tab !== "feedback";
  const inResults = isDerivedTab && derivedView === "results";

  // Source-picker props shared by every tab that renders it.
  const pickerProps = {
    feedbackResp,
    loading,
    page,
    setPage,
    filterValue,
    setFilterValue,
    filterVerdict,
    setFilterVerdict,
    configuredVerdicts,
    selectedFeedbackIds,
    toggleFeedbackId,
    setPageSelection,
    clearSelectedFeedback,
    selectAllMatching,
    selectingAll,
    maxSelectable,
    onSelectFeedback: setSelectedFeedback,
    onGenerate: handleGenerateFrom,
    canEdit,
  };

  // "Last run" banner shown above the picker on derived tabs.
  const lastRun = (() => {
    if (tab === "suggestions") {
      if (suggestionRun && ["pending", "running"].includes(suggestionRun.status)) {
        return { running: true, label: "Generation in progress" };
      }
      if (suggestionRun?.status === "completed" && suggestions.length > 0) {
        return { running: false, label: `${suggestions.length} suggestion${suggestions.length === 1 ? "" : "s"}` };
      }
    } else if (tab === "top-questions") {
      if (topQuestionsRunning) return { running: true, label: "Analysis in progress" };
      const themes = topQuestionsResult?.themes ?? [];
      if (topQuestionsResult?.status === "completed" && themes.length > 0) {
        return { running: false, label: `${themes.length} question theme${themes.length === 1 ? "" : "s"} from ${topQuestionsResult.total_questions} questions` };
      }
    } else if (tab === "themes") {
      if (feedbackThemesRunning) return { running: true, label: "Analysis in progress" };
      const themes = feedbackThemesResult?.themes ?? [];
      if (feedbackThemesResult?.status === "completed" && themes.length > 0) {
        return { running: false, label: `${themes.length} theme${themes.length === 1 ? "" : "s"} from ${feedbackThemesResult.total_comments} comments` };
      }
    }
    return null;
  })();

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Feedback</h1>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImport}
          />
          {/* Top Questions — results view controls */}
          {tab === "top-questions" && inResults && topQuestionsRunning && (
            <button
              onClick={handleStopTopQuestions}
              disabled={!canEdit}
              title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Stop ({topQuestionsResult?.processed_questions ?? 0}/{topQuestionsResult?.total_questions ?? 0})
            </button>
          )}
          {tab === "top-questions" && inResults && !topQuestionsRunning &&
            topQuestionsResult?.status === "completed" && topQuestionsResult.themes.length > 0 && (
              <button
                onClick={() => {
                  downloadTopQuestionsPdf(topQuestionsResult);
                  toast.success("PDF downloaded");
                }}
                className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
              >
                Export PDF
              </button>
            )}
          {/* Themes — results view controls */}
          {tab === "themes" && inResults && feedbackThemesRunning && (
            <button
              onClick={handleStopFeedbackThemes}
              disabled={!canEdit}
              title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Stop ({feedbackThemesResult?.processed_comments ?? 0}/{feedbackThemesResult?.total_comments ?? 0})
            </button>
          )}
          {/* User Feedback — evaluator config + run */}
          {tab === "feedback" && (
            <>
              <button
                onClick={() => setShowConfigModal(true)}
                disabled={!canEdit}
                className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title={canEdit ? "Configure feedback evaluator" : FEEDBACK_READ_ONLY_TITLE}
              >
                <svg className="w-4 h-4 inline-block" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                </svg>
              </button>
              {evalRunning ? (
                <button
                  onClick={handleStop}
                  disabled={!canEdit}
                  title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
                  className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Stop ({evalResult?.summary.evaluated_count}/{evalResult?.summary.total_count})
                </button>
              ) : (
                <button
                  onClick={handleEvaluate}
                  disabled={evalTriggering || !canEdit}
                  title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {evalTriggering ? "Starting..." : "Evaluate Feedback"}
                </button>
              )}
            </>
          )}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={!canEdit}
            title={!canEdit ? FEEDBACK_READ_ONLY_TITLE : undefined}
            className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Import JSON
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <button onClick={() => selectTab("feedback")} className={tabClass("feedback")}>
          User Feedback
        </button>
        <button onClick={() => selectTab("suggestions")} className={tabClass("suggestions")}>
          Suggestions
        </button>
        <button onClick={() => selectTab("top-questions")} className={tabClass("top-questions")}>
          Top Questions
        </button>
        <button onClick={() => selectTab("themes")} className={tabClass("themes")}>
          Themes
        </button>
      </div>

      {/* === User Feedback tab === */}
      {tab === "feedback" ? (
        <>
          {/* Feedback Trends Chart */}
          {stats && stats.trends.length > 0 && (
            <TrendBarChart
              title="Feedback Trend"
              data={stats.trends.map((t) => ({ date: t.date, positive: t.positive, negative: t.negative, total: t.total }))}
              positiveLabel="Positive"
              negativeLabel="Negative"
              hoveredBar={hoveredBar}
              hoverOffset={0}
              onHover={setHoveredBar}
            />
          )}

          {/* Stats Cards */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <StatCard label="Total Feedback" value={stats.total_feedback} />
              <StatCard
                label="Positive"
                value={stats.positive}
                sub={`${(stats.positive_rate * 100).toFixed(1)}%`}
              />
              <StatCard label="Negative" value={stats.negative} />
              <StatCard label="No Feedback" value={stats.no_feedback_traces} sub="traces without feedback" />
            </div>
          )}

          {/* Evaluation progress indicator */}
          {evalRunning && evalResult && (
            <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-200 dark:border-indigo-900/50">
              <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <span className="text-sm text-indigo-700 dark:text-indigo-300">
                {evalResult.status === "pending"
                  ? "Starting evaluation..."
                  : `Evaluating feedback... ${evalResult.summary.evaluated_count} of ${evalResult.summary.total_count}`}
              </span>
              {evalResult.summary.total_count > 0 && (
                <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                    style={{ width: `${Math.round((evalResult.summary.evaluated_count / evalResult.summary.total_count) * 100)}%` }}
                  />
                </div>
              )}
            </div>
          )}

          <FeedbackSourcePicker output={null} {...pickerProps} />
        </>
      ) : derivedView === "picker" ? (
        /* === Derived tab — step 1: pick source feedback === */
        <>
          <p className="text-sm text-gray-500 dark:text-slate-400 mb-4">
            Select the feedback to generate{" "}
            {tab === "suggestions" ? "test case suggestions" : tab === "top-questions" ? "top questions" : "themes"} from.
            Leave everything unselected to use all feedback matching the current filters.
          </p>
          {lastRun && (
            <div className="mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700">
              <span className="text-sm text-gray-600 dark:text-slate-300">
                {lastRun.running ? lastRun.label : `Last run: ${lastRun.label}`}
              </span>
              <button
                onClick={() => setDerivedView("results")}
                className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-indigo-600 dark:text-indigo-300 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
              >
                {lastRun.running ? "View progress" : "View results"}
              </button>
            </div>
          )}
          <FeedbackSourcePicker output={tab} {...pickerProps} />
        </>
      ) : (
        /* === Derived tab — step 2: results === */
        <>
          <button
            onClick={() => setDerivedView("picker")}
            className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
            </svg>
            Select feedback
          </button>
          {tab === "suggestions" && (
            <SuggestionsTab
              suggestions={suggestions}
              sugLoading={sugLoading}
              sugGenerated={sugGenerated}
              sugFilter={sugFilter}
              setSugFilter={setSugFilter}
              suggestionRun={suggestionRun}
              datasets={datasets}
              selectedSuggestion={selectedSuggestion}
              setSelectedSuggestion={setSelectedSuggestion}
              saving={saving}
              onAccept={handleAcceptSuggestion}
              onGenerate={() => handleGenerateSuggestions()}
              onStop={handleStopSuggestionRun}
              canEdit={canEdit}
            />
          )}
          {tab === "top-questions" && (
            <TopQuestionsTab
              result={topQuestionsResult}
              loading={topQuestionsLoading}
              running={topQuestionsRunning}
              triggering={topQuestionsTriggering}
              onAnalyze={() => setDerivedView("picker")}
            />
          )}
          {tab === "themes" && (
            <FeedbackThemesTab
              result={feedbackThemesResult}
              loading={feedbackThemesLoading}
              running={feedbackThemesRunning}
              triggering={feedbackThemesTriggering}
              onAnalyze={() => setDerivedView("picker")}
            />
          )}
        </>
      )}

      {/* Feedback Detail Modal */}
      {selectedFeedback && (
        <FeedbackDetailModal
          item={selectedFeedback}
          onClose={() => setSelectedFeedback(null)}
          onUpdate={(updated) => {
            setSelectedFeedback(updated);
            // Update the item in the table too
            if (feedbackResp) {
              setFeedbackResp({
                ...feedbackResp,
                data: feedbackResp.data.map((f) => f.id === updated.id ? updated : f),
              });
            }
          }}
          configuredVerdicts={configuredVerdicts}
        />
      )}

      {/* Feedback Evaluator Config Modal */}
      {showConfigModal && evalConfig && (
        <FeedbackEvaluatorModal
          config={evalConfig}
          onClose={() => setShowConfigModal(false)}
          onSave={handleSaveConfig}
          saving={configSaving}
          reevaluate={reevaluate}
          onReevaluateChange={setReevaluate}
        />
      )}
    </div>
  );
}
