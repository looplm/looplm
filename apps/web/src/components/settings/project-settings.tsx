"use client";

import { useEffect, useState } from "react";
import {
  updateProject,
  deleteProject,
  detectRetrievalSource,
  setSelectedProjectId,
  type Project,
  type RetrievalSourceDetection,
} from "@/lib/api";

interface ProjectSettingsProps {
  currentProjectId: string | null;
  onProjectChange: (id: string) => void;
  projects: Project[];
  reloadProjects: () => Promise<void>;
}

export default function ProjectSettings({
  currentProjectId,
  onProjectChange,
  projects,
  reloadProjects,
}: ProjectSettingsProps) {
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState("");

  const [detecting, setDetecting] = useState(false);
  const [detection, setDetection] = useState<RetrievalSourceDetection | null>(null);
  const [savingSource, setSavingSource] = useState(false);
  const [sourceMessage, setSourceMessage] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);
  const configuredSource = currentProject?.settings?.retrieval_source as
    | { kind?: string; value?: string; confidence?: string; reasoning?: string }
    | undefined;

  useEffect(() => {
    if (currentProject) {
      setEditName(currentProject.name);
      setEditDescription(currentProject.description || "");
    }
    setMessage("");
    setDetection(null);
    setSourceMessage("");
  }, [currentProjectId]);

  async function handleDetect() {
    if (!currentProjectId) return;
    setDetecting(true);
    setSourceMessage("");
    setDetection(null);
    try {
      setDetection(await detectRetrievalSource(currentProjectId));
    } catch (e: any) {
      setSourceMessage(e.message || "Detection failed");
    } finally {
      setDetecting(false);
    }
  }

  async function handleSaveSource() {
    if (!currentProjectId || !detection?.suggestion) return;
    setSavingSource(true);
    setSourceMessage("");
    try {
      await updateProject(currentProjectId, {
        settings: {
          retrieval_source: {
            ...detection.suggestion,
            detected_at: new Date().toISOString(),
          },
        },
      });
      await reloadProjects();
      setDetection(null);
      setSourceMessage("Retrieval source saved");
    } catch (e: any) {
      setSourceMessage(e.message || "Failed to save");
    } finally {
      setSavingSource(false);
    }
  }

  async function handleSave() {
    if (!currentProjectId || !editName.trim()) return;
    setSaving(true);
    setMessage("");
    try {
      await updateProject(currentProjectId, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
      });
      await reloadProjects();
      setMessage("Project updated");
    } catch (e: any) {
      setMessage(e.message || "Failed to update");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!currentProjectId || projects.length <= 1) return;
    if (!confirm("Delete this project and all its data? This cannot be undone.")) return;
    setDeleting(true);
    setMessage("");
    try {
      await deleteProject(currentProjectId);
      await reloadProjects();
      const remaining = projects.filter((p) => p.id !== currentProjectId);
      if (remaining.length > 0) {
        onProjectChange(remaining[0].id);
        setSelectedProjectId(remaining[0].id);
      }
      setMessage("Project deleted");
    } catch (e: any) {
      setMessage(e.message || "Failed to delete");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-4">Projects</h2>

        {/* Project selector */}
        <div className="mb-4">
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Current Project</label>
          <select
            value={currentProjectId || ""}
            onChange={(e) => onProjectChange(e.target.value)}
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Edit current project */}
        {currentProject && (
          <div className="space-y-3 mb-4">
            <div>
              <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Project Name</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Description</label>
              <input
                type="text"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="Optional description"
                className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Changes"}
              </button>
              {projects.length > 1 && (
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="px-4 py-2 bg-red-600/20 text-red-400 rounded-lg text-sm hover:bg-red-600/30 disabled:opacity-50"
                >
                  {deleting ? "Deleting..." : "Delete Project"}
                </button>
              )}
            </div>
          </div>
        )}

        {message && (
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-3">{message}</p>
        )}
      </div>

      {/* Retrieval context source */}
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">Retrieval context source</h2>
        <p className="text-sm text-gray-500 dark:text-slate-400 mb-4">
          Which field or span holds your RAG retrieved context. Used for retrieval-vs-generation
          failure attribution. Let the analysis LLM detect it from recent traces.
        </p>

        <div className="mb-4 text-sm">
          <span className="text-gray-500 dark:text-slate-400">Current: </span>
          {configuredSource?.kind && configuredSource?.value ? (
            <code className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200">
              {configuredSource.kind === "payload_key" ? "payload key" : "span"} ·{" "}
              {configuredSource.value}
            </code>
          ) : (
            <span className="text-gray-400 dark:text-slate-500">
              not set — default keys / span name are used
            </span>
          )}
        </div>

        <button
          onClick={handleDetect}
          disabled={detecting || !currentProjectId}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {detecting ? "Detecting…" : "Auto-detect retrieval field"}
        </button>

        {detection && (
          <div className="mt-4 space-y-3">
            {detection.suggestion ? (
              <div className="rounded-lg border border-indigo-200 dark:border-indigo-900 bg-indigo-50/50 dark:bg-indigo-950/30 p-3">
                <div className="text-sm text-gray-700 dark:text-slate-200">
                  Suggested:{" "}
                  <code className="px-1.5 py-0.5 rounded bg-white dark:bg-slate-800">
                    {detection.suggestion.kind === "payload_key" ? "payload key" : "span"} ·{" "}
                    {detection.suggestion.value}
                  </code>{" "}
                  <span className="text-xs text-gray-500 dark:text-slate-400">
                    ({detection.suggestion.confidence} confidence)
                  </span>
                </div>
                {detection.suggestion.reasoning && (
                  <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                    {detection.suggestion.reasoning}
                  </p>
                )}
                <button
                  onClick={handleSaveSource}
                  disabled={savingSource}
                  className="mt-3 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {savingSource ? "Saving…" : "Save this source"}
                </button>
              </div>
            ) : (
              <p className="text-sm text-gray-500 dark:text-slate-400">
                No retrieval context field could be identified in recent traces.
              </p>
            )}

            <details className="text-xs text-gray-500 dark:text-slate-400">
              <summary className="cursor-pointer">
                Candidates considered ({detection.candidates.payload_keys.length} keys,{" "}
                {detection.candidates.spans.length} spans)
              </summary>
              <div className="mt-2 space-y-1">
                {detection.candidates.payload_keys.map((c) => (
                  <div key={`k-${c.key}`}>
                    <code>{c.key}</code> — {c.sample}
                  </div>
                ))}
                {detection.candidates.spans.map((c) => (
                  <div key={`s-${c.name}`}>
                    <code>{c.name}</code> — {c.sample}
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}

        {sourceMessage && (
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-3">{sourceMessage}</p>
        )}
      </div>
    </div>
  );
}
