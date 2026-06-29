"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type {
  FeedbackScoreItem,
  FeedbackEvaluateResponse,
  FeedbackEvaluatorConfig,
} from "@/lib/api";
import {
  evaluateFeedback,
  getFeedbackEvaluation,
  stopFeedbackEvaluation,
  getFeedbackEvaluatorConfig,
  updateFeedbackEvaluatorConfig,
} from "@/lib/api/feedback-api";
import { useGlobalFilters } from "@/components/global-filters-context";

// `loadFeedback` lives in the list hook; the evaluation flow refreshes the
// feedback table on stop and on completion, so it is threaded in here.
export function useFeedbackEvaluation(loadFeedback: () => void) {
  const globalFilters = useGlobalFilters();

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

  // Eval completion flag — triggers feedback list refresh
  const [evalCompleted, setEvalCompleted] = useState(0);

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

  return {
    evalResult,
    evalTriggering,
    evalConfig,
    showConfigModal,
    setShowConfigModal,
    configSaving,
    selectedFeedback,
    setSelectedFeedback,
    reevaluate,
    setReevaluate,
    evalCompleted,
    evalRunning,
    configuredVerdicts,
    handleSaveConfig,
    handleStop,
    handleEvaluate,
  };
}
