"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import type { FeedbackScoreItem } from "@/lib/api";
import { evaluateSingleFeedback } from "@/lib/api/feedback-api";

function extractFullText(data: unknown, role?: string): string {
  if (!data) return "\u2014";
  if (typeof data === "string") return data;
  if (Array.isArray(data)) {
    const msgs = role ? data.filter((m: any) => m.role === role) : data;
    const last = msgs.pop();
    if (last?.content) return typeof last.content === "string" ? last.content : JSON.stringify(last.content, null, 2);
  }
  if (typeof data === "object" && data !== null) {
    const obj = data as Record<string, unknown>;
    if (typeof obj.text === "string") return obj.text;
    if (typeof obj.content === "string") return obj.content;
    if (typeof obj.answer === "string") return obj.answer;
    if (obj.messages && Array.isArray(obj.messages)) return extractFullText(obj.messages, role);
    return JSON.stringify(data, null, 2);
  }
  return String(data);
}

export function FeedbackDetailModal({
  item,
  onClose,
  onUpdate,
  configuredVerdicts,
}: {
  item: FeedbackScoreItem;
  onClose: () => void;
  onUpdate?: (updated: FeedbackScoreItem) => void;
  configuredVerdicts: string[];
}) {
  const [evaluating, setEvaluating] = useState(false);
  const [currentItem, setCurrentItem] = useState(item);
  const userQuestion = extractFullText(currentItem.trace_input, "user");
  const aiResponse = extractFullText(currentItem.trace_output, "assistant");

  async function handleReEvaluate() {
    setEvaluating(true);
    try {
      const result = await evaluateSingleFeedback(currentItem.id);
      const updated = { ...currentItem, eval_verdict: result.verdict, eval_reasoning: result.reasoning, eval_confidence: result.confidence };
      setCurrentItem(updated);
      onUpdate?.(updated);
      toast.success("Re-evaluated", { description: `Verdict: ${result.verdict}` });
    } catch (err: any) {
      toast.error("Evaluation failed", { description: err.message });
    } finally {
      setEvaluating(false);
    }
  }

  const verdictBadgeColor = (() => {
    if (!currentItem.eval_verdict) return "";
    const idx = configuredVerdicts.indexOf(currentItem.eval_verdict);
    const colors = [
      "bg-red-100 text-red-700 dark:bg-red-900/20 dark:text-red-400",
      "bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400",
      "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
      "bg-blue-100 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400",
      "bg-amber-100 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400",
    ];
    return colors[idx >= 0 ? idx % colors.length : 2];
  })();

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col z-[70]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <span className={`text-lg ${currentItem.value === 1 ? "text-green-500" : "text-red-500"}`}>
              {currentItem.value === 1 ? "\uD83D\uDC4D" : "\uD83D\uDC4E"}
            </span>
            <div>
              <h2 className="text-lg font-semibold">Feedback Detail</h2>
              <p className="text-xs text-gray-400 dark:text-slate-500">
                {currentItem.scored_at
                  ? new Date(currentItem.scored_at).toLocaleString("de-DE", {
                      day: "2-digit",
                      month: "2-digit",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : ""}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-300 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* User Question */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide mb-2">
              User Question
            </h3>
            <div className="text-sm text-gray-700 dark:text-slate-200 bg-gray-50 dark:bg-slate-800 rounded-lg p-3 max-h-40 overflow-y-auto whitespace-pre-wrap">
              {userQuestion}
            </div>
          </div>

          {/* AI Response */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide mb-2">
              AI Response
            </h3>
            <div className="text-sm text-gray-700 dark:text-slate-200 bg-gray-50 dark:bg-slate-800 rounded-lg p-3 max-h-48 overflow-y-auto whitespace-pre-wrap">
              {aiResponse}
            </div>
          </div>

          {/* Comment */}
          {currentItem.comment && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide mb-2">
                Feedback Comment
              </h3>
              <p className="text-sm text-gray-700 dark:text-slate-200 italic">
                &ldquo;{currentItem.comment}&rdquo;
              </p>
            </div>
          )}

          {/* Trace Metadata */}
          {currentItem.trace_metadata && Object.keys(currentItem.trace_metadata).length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide mb-2">
                Metadata
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 bg-gray-50 dark:bg-slate-800 rounded-lg p-3">
                {Object.entries(currentItem.trace_metadata!).map(([key, val]) => (
                  <div key={key} className="min-w-0">
                    <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wide">{key}</p>
                    <p className="text-xs text-gray-700 dark:text-slate-200 truncate" title={String(val)}>
                      {typeof val === "boolean" ? (
                        <span className={val ? "text-green-600" : "text-red-500"}>{String(val)}</span>
                      ) : Array.isArray(val) ? (
                        val.length > 0 ? val.join(", ") : "\u2014"
                      ) : typeof val === "object" && val !== null ? (
                        JSON.stringify(val)
                      ) : (
                        String(val ?? "\u2014")
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Evaluation */}
          {/* Evaluation */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide">
                Evaluation
              </h3>
              <button
                onClick={handleReEvaluate}
                disabled={evaluating}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50 transition-colors"
              >
                {evaluating ? "Evaluating..." : currentItem.eval_verdict ? "Re-evaluate" : "Evaluate"}
              </button>
            </div>
            {currentItem.eval_verdict ? (
              <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-3">
                  <span className={`inline-block px-2.5 py-0.5 rounded text-xs font-medium ${verdictBadgeColor}`}>
                    {currentItem.eval_verdict}
                  </span>
                  {currentItem.eval_confidence != null && (
                    <span className="text-xs text-gray-500 dark:text-slate-400">
                      {Math.round(currentItem.eval_confidence * 100)}% confidence
                    </span>
                  )}
                </div>
                {currentItem.eval_reasoning && (
                  <p className="text-sm text-gray-600 dark:text-slate-300">
                    {currentItem.eval_reasoning}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-gray-400 dark:text-slate-500 italic">
                Not yet evaluated. Click &ldquo;Evaluate&rdquo; to run.
              </p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-slate-800">
          {currentItem.trace_id && (
            <Link
              href={`/traces/${currentItem.trace_id}`}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 transition-colors"
            >
              View Trace
            </Link>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
