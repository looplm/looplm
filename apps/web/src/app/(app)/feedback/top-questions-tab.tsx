"use client";

import { useState } from "react";
import Link from "next/link";
import type { TopQuestionsResponse } from "@/lib/api";

interface TopQuestionsTabProps {
  result: TopQuestionsResponse | null;
  loading: boolean;
  running: boolean;
  triggering: boolean;
  onAnalyze: () => void;
}

export function TopQuestionsTab({
  result,
  loading,
  running,
  triggering,
  onAnalyze,
}: TopQuestionsTabProps) {
  const themes = result?.themes ?? [];
  const hasResults = result?.status === "completed" && themes.length > 0;
  const [expandedRanks, setExpandedRanks] = useState<Set<number>>(new Set());

  const toggleExpand = (rank: number) => {
    setExpandedRanks((prev) => {
      const next = new Set(prev);
      if (next.has(rank)) next.delete(rank);
      else next.add(rank);
      return next;
    });
  };

  return (
    <div>
      {/* Progress indicator */}
      {running && result && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-200 dark:border-indigo-900/50">
          <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span className="text-sm text-indigo-700 dark:text-indigo-300">
            {result.status === "pending"
              ? "Starting analysis..."
              : `Analyzing questions... ${result.processed_questions} of ${result.total_questions}`}
          </span>
          {result.total_questions > 0 && (
            <div className="flex-1 h-2 rounded-full bg-indigo-200 dark:bg-indigo-900/30 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                style={{ width: `${Math.round((result.processed_questions / result.total_questions) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {result?.status === "failed" && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-900/50 text-sm text-red-700 dark:text-red-300">
          Analysis failed: {result.error || "Unknown error"}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : !hasResults && !running ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center">
          <p className="text-gray-500 dark:text-slate-400 mb-4">
            Analyze your feedback to discover the top question themes asked by users.
          </p>
          <button
            onClick={onAnalyze}
            disabled={triggering}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
          >
            {triggering ? "Starting..." : "Analyze Top Questions"}
          </button>
        </div>
      ) : hasResults ? (
        <div>
          {/* Last analyzed timestamp */}
          {result?.completed_at && (
            <p className="text-xs text-gray-400 dark:text-slate-500 mb-4">
              Last analyzed: {new Date(result.completed_at).toLocaleString("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
              {" "}({result.total_questions} questions analyzed)
            </p>
          )}

          <div className="space-y-3">
            {themes.map((theme) => {
              const isExpanded = expandedRanks.has(theme.rank);
              const allQuestions = theme.all_questions ?? [];

              return (
                <div
                  key={theme.rank}
                  className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800"
                >
                  {/* Clickable header */}
                  <button
                    type="button"
                    onClick={() => toggleExpand(theme.rank)}
                    className="w-full p-4 text-left"
                  >
                    <div className="flex items-start gap-4">
                      {/* Rank number */}
                      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                        <span className="text-sm font-bold text-indigo-600 dark:text-indigo-400">
                          {theme.rank}
                        </span>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-2">
                          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                            {theme.theme}
                          </h3>
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
                            {theme.count} questions
                          </span>
                        </div>

                        {/* Sentiment bar */}
                        {(theme.feedback_sentiment.positive > 0 || theme.feedback_sentiment.negative > 0) && (
                          <div className="flex items-center gap-2 mb-3">
                            <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden flex">
                              {(() => {
                                const total = theme.feedback_sentiment.positive + theme.feedback_sentiment.negative;
                                const posPercent = total > 0 ? (theme.feedback_sentiment.positive / total) * 100 : 0;
                                return (
                                  <>
                                    {posPercent > 0 && (
                                      <div
                                        className="h-full bg-green-500"
                                        style={{ width: `${posPercent}%` }}
                                      />
                                    )}
                                    {posPercent < 100 && (
                                      <div
                                        className="h-full bg-red-500"
                                        style={{ width: `${100 - posPercent}%` }}
                                      />
                                    )}
                                  </>
                                );
                              })()}
                            </div>
                            <span className="text-xs text-gray-400 dark:text-slate-500 flex-shrink-0">
                              {theme.feedback_sentiment.positive} positive, {theme.feedback_sentiment.negative} negative
                            </span>
                          </div>
                        )}

                        {/* Summary question */}
                        {theme.summary_question && (
                          <p className="text-xs text-gray-600 dark:text-slate-300 italic pl-3 border-l-2 border-indigo-300 dark:border-indigo-700">
                            {theme.summary_question}
                          </p>
                        )}
                      </div>

                      {/* Expand/collapse chevron */}
                      <svg
                        className={`w-5 h-5 text-gray-400 dark:text-slate-500 flex-shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={1.5}
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
                      </svg>
                    </div>
                  </button>

                  {/* Expanded: all questions */}
                  {isExpanded && allQuestions.length > 0 && (
                    <div className="px-4 pb-4 pt-0 ml-12">
                      <div className="border-t border-gray-100 dark:border-slate-800 pt-3">
                        <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-2">
                          All questions ({allQuestions.length})
                        </p>
                        <ul className="space-y-1.5">
                          {allQuestions.map((q, i) => (
                            <li
                              key={i}
                              className="flex items-start gap-2 text-xs"
                            >
                              {q.feedback_value === 1 ? (
                                <span className="flex-shrink-0 mt-0.5 w-3.5 h-3.5 text-green-500">
                                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M7.493 18.75c-.425 0-.82-.236-.975-.632A7.48 7.48 0 0 1 6 15.375c0-1.75.599-3.358 1.602-4.634.151-.192.373-.309.6-.397.473-.183.89-.514 1.212-.924a9.042 9.042 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V3.75A.75.75 0 0 1 15 3a2.25 2.25 0 0 1 2.25 2.25c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48a4.53 4.53 0 0 1-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.45-.243ZM5.25 15.375a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z" />
                                  </svg>
                                </span>
                              ) : (
                                <span className="flex-shrink-0 mt-0.5 w-3.5 h-3.5 text-red-500">
                                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M15.73 5.25h1.035A7.984 7.984 0 0 1 18 9.375c0 1.886-.65 3.636-1.74 5.01-.163.206-.396.328-.636.42a1.985 1.985 0 0 1-1.178.881 9.042 9.042 0 0 1-2.861 2.4c-.723.384-1.35.956-1.653 1.715a4.498 4.498 0 0 0-.322 1.672v.633a.75.75 0 0 1-.75.75 2.25 2.25 0 0 1-2.25-2.25c0-1.152.26-2.243.723-3.218.266-.558-.107-1.282-.725-1.282H3.622c-1.026 0-1.945-.694-2.054-1.715A12.134 12.134 0 0 1 1.5 12.75c0-2.772.943-5.33 2.523-7.36.388-.5 1.003-.765 1.638-.765h3.659c.497 0 .987.08 1.45.243l3.114 1.04c.462.154.95.233 1.446.242ZM18.75 8.625a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0Z" />
                                  </svg>
                                </span>
                              )}
                              {q.trace_id ? (
                                <Link
                                  href={`/traces/${q.trace_id}`}
                                  className="text-gray-600 dark:text-slate-300 hover:text-indigo-600 dark:hover:text-indigo-400 hover:underline"
                                >
                                  {q.question}
                                </Link>
                              ) : (
                                <span className="text-gray-600 dark:text-slate-300">
                                  {q.question}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
