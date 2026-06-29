"use client";

import { useEffect, useRef, useState } from "react";
import {
  getIntegrations,
  getPrompts,
  syncPrompts,
  importPrompts,
  getProjectGithubInstallation,
  clusterPrompts,
  deletePrompt,
  excludePrompt,
  getExclusions,
  removeExclusion,
  type Integration,
  type PromptItem,
  type ExclusionItem,
} from "@/lib/api";
import { PromptTree } from "./prompt-tree";
import { ImportSelectionModal } from "./import-selection-modal";
import { SOURCE_BADGES, SOURCE_LABELS, timeAgo } from "./constants";
import { useGithubExtraction } from "./hooks/use-github-extraction";
import { usePromptSelection } from "./hooks/use-prompt-selection";
import { PromptHeader } from "@/components/prompts/prompt-header";
import { GithubExtractionStatus } from "@/components/prompts/github-extraction-status";
import { ExclusionsList } from "@/components/prompts/exclusions-list";
import { PromptDetailPanel } from "@/components/prompts/prompt-detail-panel";
import { usePermissions } from "@/components/permissions-context";

export default function PromptsPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("prompts");
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [githubRepo, setGithubRepo] = useState<string | null>(null);
  const [reclustering, setReclustering] = useState(false);
  const [exclusions, setExclusions] = useState<ExclusionItem[]>([]);
  const [showExclusions, setShowExclusions] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const githubCount = prompts.filter((p) => p.source === "github").length;

  const loadExclusions = () => {
    getExclusions().then((r) => setExclusions(r.data ?? [])).catch(() => setExclusions([]));
  };

  const loadPrompts = () => {
    setLoading(true);
    getPrompts()
      .then((r) => setPrompts(r.data ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  // Reload the list without flipping the loading state — used to surface
  // prompts as they're extracted one by one.
  const refreshPromptsQuietly = () => {
    getPrompts().then((r) => setPrompts(r.data ?? [])).catch(() => {});
  };

  const {
    extraction,
    confirming,
    now,
    inProgress,
    awaitingSelection,
    lastRunIncomplete,
    handleDiscover,
    handleConfirmImport,
    handleCancelExtraction,
  } = useGithubExtraction({ refreshPromptsQuietly, loadPrompts, setError });

  const {
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
  } = usePromptSelection({ refreshPromptsQuietly, setError });

  useEffect(() => {
    getIntegrations().then((r) => setIntegrations(r.data)).catch((e) => setError(e.message));
    loadPrompts();
    loadExclusions();
    getProjectGithubInstallation()
      .then((inst) => setGithubRepo(inst?.repo_full_name ?? null))
      .catch(() => setGithubRepo(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRecluster = async () => {
    setReclustering(true);
    setError(null);
    try {
      await clusterPrompts();
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReclustering(false);
    }
  };

  const handleDelete = async (promptId: string) => {
    if (!confirm("Delete this prompt? Synced prompts may reappear on the next import — use Exclude to remove permanently.")) return;
    try {
      await deletePrompt(promptId);
      setSelectedPrompt(null);
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleExclude = async (promptId: string) => {
    if (!confirm("Exclude this prompt from sync? It will be removed and never re-imported (you can lift the exclusion later).")) return;
    try {
      await excludePrompt(promptId);
      setSelectedPrompt(null);
      loadPrompts();
      loadExclusions();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleRemoveExclusion = async (externalId: string) => {
    try {
      await removeExclusion(externalId);
      loadExclusions();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleSync = async (integrationId: string) => {
    setSyncing(true);
    setError(null);
    try {
      await syncPrompts(integrationId);
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleImportJson = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const prompts = Array.isArray(parsed) ? parsed : parsed.prompts;
      if (!Array.isArray(prompts)) throw new Error("Expected { \"prompts\": [...] } or a flat array");
      await importPrompts(prompts, file.name);
      loadPrompts();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div>
      <PromptHeader
        integrations={integrations}
        canEdit={canEdit}
        syncing={syncing}
        importing={importing}
        reclustering={reclustering}
        githubRepo={githubRepo}
        githubCount={githubCount}
        exclusionsCount={exclusions.length}
        inProgress={inProgress}
        awaitingSelection={awaitingSelection}
        lastRunIncomplete={lastRunIncomplete}
        fileInputRef={fileInputRef}
        onSync={handleSync}
        onToggleExclusions={() => setShowExclusions((v) => !v)}
        onRecluster={handleRecluster}
        onCancelExtraction={handleCancelExtraction}
        onDiscover={handleDiscover}
        onImportJson={handleImportJson}
      />

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      <GithubExtractionStatus
        extraction={extraction}
        githubRepo={githubRepo}
        inProgress={inProgress}
        now={now}
      />

      {awaitingSelection && extraction && (
        <ImportSelectionModal
          locations={extraction.planned_locations}
          repo={githubRepo}
          busy={confirming}
          onConfirm={handleConfirmImport}
          onCancel={handleCancelExtraction}
        />
      )}

      {showExclusions && (
        <ExclusionsList
          exclusions={exclusions}
          canEdit={canEdit}
          onClose={() => setShowExclusions(false)}
          onRemoveExclusion={handleRemoveExclusion}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Prompt list */}
        <div className="lg:col-span-1 space-y-2 max-h-[calc(100vh-10rem)] overflow-y-auto pr-1">
          {loading ? (
            <div className="text-gray-500 dark:text-slate-400 text-sm p-4">Loading...</div>
          ) : prompts.length === 0 ? (
            <div className="text-gray-500 dark:text-slate-400 text-sm p-4">No prompts imported yet. Click Sync to import.</div>
          ) : (
            <PromptTree
              prompts={prompts}
              renderPrompt={(p) => (
                <button
                  key={p.id}
                  onClick={() => selectPrompt(p)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedPrompt?.id === p.id
                      ? "bg-indigo-50 dark:bg-indigo-600/20 border-indigo-500/30"
                      : "bg-white dark:bg-slate-900 border-gray-100 dark:border-slate-800 hover:border-gray-200 dark:hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm truncate flex-1">{p.name}</span>
                    <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded border shrink-0 ${SOURCE_BADGES[p.source] ?? "bg-slate-500/20 text-slate-600 dark:text-slate-300 border-slate-500/40"}`}>
                      {SOURCE_LABELS[p.source] ?? p.source}
                    </span>
                  </div>
                  <div className="text-[10px] text-gray-400 dark:text-slate-500" title={p.updated_at ? new Date(p.updated_at).toLocaleString() : undefined}>
                    v{p.version} · {p.variables?.length ?? 0} vars{p.updated_at ? ` · updated ${timeAgo(p.updated_at)}` : ""}
                  </div>
                </button>
              )}
            />
          )}
        </div>

        {/* Detail panel */}
        <div className="lg:col-span-2">
          {selectedPrompt ? (
            <PromptDetailPanel
              selectedPrompt={selectedPrompt}
              canEdit={canEdit}
              githubRepo={githubRepo}
              rechecking={rechecking}
              reviewing={reviewing}
              recheckMsg={recheckMsg}
              clusterDraft={clusterDraft}
              review={review}
              reviewHistory={reviewHistory}
              versions={versions}
              activeTab={activeTab}
              compareA={compareA}
              compareB={compareB}
              copied={copied}
              onClusterDraftChange={setClusterDraft}
              onSaveCluster={handleSaveCluster}
              onExclude={handleExclude}
              onDelete={handleDelete}
              onRecheck={handleRecheck}
              onReview={handleReview}
              onTabChange={setActiveTab}
              onCompareAChange={setCompareA}
              onCompareBChange={setCompareB}
              onCopy={handleCopy}
              onApply={handleApply}
            />
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-12 text-center text-gray-500 dark:text-slate-400">
              Select a prompt to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
