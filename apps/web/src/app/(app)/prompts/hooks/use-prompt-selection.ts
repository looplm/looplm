"use client";

import { useState } from "react";
import {
  reviewPrompt,
  getPromptReviews,
  getPromptVersions,
  recheckPrompt,
  updatePromptCluster,
  type PromptItem,
  type PromptReviewResult,
} from "@/lib/api";

interface UsePromptSelectionOptions {
  refreshPromptsQuietly: () => void;
  setError: (msg: string | null) => void;
}

export function usePromptSelection({
  refreshPromptsQuietly,
  setError,
}: UsePromptSelectionOptions) {
  const [selectedPrompt, setSelectedPrompt] = useState<PromptItem | null>(null);
  const [review, setReview] = useState<PromptReviewResult | null>(null);
  const [reviewHistory, setReviewHistory] = useState<PromptReviewResult[]>([]);
  const [versions, setVersions] = useState<PromptItem[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [recheckMsg, setRecheckMsg] = useState<string | null>(null);
  const [clusterDraft, setClusterDraft] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"review" | "history" | "versions">("review");
  const [compareA, setCompareA] = useState<number | null>(null);
  const [compareB, setCompareB] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const selectPrompt = async (p: PromptItem) => {
    setSelectedPrompt(p);
    setReview(null);
    setRecheckMsg(null);
    setClusterDraft((p.cluster_path ?? []).join(" / "));
    setActiveTab("review");
    setCompareA(null);
    setCompareB(null);
    try {
      const [reviewsRes, versionsRes] = await Promise.all([
        getPromptReviews(p.id),
        getPromptVersions(p.id),
      ]);
      setReviewHistory(reviewsRes.data ?? []);
      setVersions(versionsRes.data ?? []);
    } catch {
      setReviewHistory([]);
      setVersions([]);
    }
  };

  const handleReview = async (promptId: string) => {
    setReviewing(true);
    setError(null);
    try {
      const result = await reviewPrompt(promptId);
      setReview(result);
      setReviewHistory((prev) => [result, ...prev]);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReviewing(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApply = async () => {
    // Stub: would call Langfuse API to update the prompt
    alert("Apply to Langfuse: This would update the prompt in your connected platform. (Stubbed)");
  };

  const handleRecheck = async (promptId: string) => {
    setRechecking(true);
    setRecheckMsg(null);
    setError(null);
    try {
      const res = await recheckPrompt(promptId);
      if (res.changed) {
        setSelectedPrompt(res.prompt);
        setRecheckMsg("Updated — the prompt changed in the codebase.");
        refreshPromptsQuietly();
      } else {
        setRecheckMsg("No changes since last extraction.");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRechecking(false);
    }
  };

  const handleSaveCluster = async () => {
    if (!selectedPrompt) return;
    const path = clusterDraft.split("/").map((s) => s.trim()).filter(Boolean);
    try {
      const updated = await updatePromptCluster(selectedPrompt.id, path);
      setSelectedPrompt(updated);
      refreshPromptsQuietly();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return {
    selectedPrompt,
    setSelectedPrompt,
    review,
    reviewHistory,
    versions,
    reviewing,
    rechecking,
    recheckMsg,
    clusterDraft,
    setClusterDraft,
    activeTab,
    setActiveTab,
    compareA,
    setCompareA,
    compareB,
    setCompareB,
    copied,
    selectPrompt,
    handleReview,
    handleCopy,
    handleApply,
    handleRecheck,
    handleSaveCluster,
  };
}
