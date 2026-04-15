"use client";

import { useEffect, useState } from "react";
import {
  updateProject,
  deleteProject,
  setSelectedProjectId,
  type Project,
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

  const currentProject = projects.find((p) => p.id === currentProjectId);

  useEffect(() => {
    if (currentProject) {
      setEditName(currentProject.name);
      setEditDescription(currentProject.description || "");
    }
    setMessage("");
  }, [currentProjectId]);

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
    </div>
  );
}
