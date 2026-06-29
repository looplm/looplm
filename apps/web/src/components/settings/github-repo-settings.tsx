"use client";

import { useEffect, useState } from "react";
import {
  disconnectProjectGithubInstallation,
  getGithubAuthUrl,
  getProjectGithubInstallation,
  listRepoBranches,
  selectProjectGithubInstallation,
  type GithubInstallation,
  type GithubStatus,
  type Project,
} from "@/lib/api";

interface GithubRepoSettingsProps {
  currentProjectId: string | null;
  currentProject: Project | undefined;
  githubStatus: GithubStatus | null;
}

export default function GithubRepoSettings({
  currentProjectId,
  currentProject,
  githubStatus,
}: GithubRepoSettingsProps) {
  const [githubInstallation, setGithubInstallation] = useState<GithubInstallation | null>(null);
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubError, setGithubError] = useState("");

  // Inline branch switcher for an already-connected repo.
  const [branchEditing, setBranchEditing] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchSaving, setBranchSaving] = useState(false);

  useEffect(() => {
    if (!currentProjectId || !githubStatus?.enabled) {
      setGithubInstallation(null);
      return;
    }
    getProjectGithubInstallation()
      .then(setGithubInstallation)
      .catch(() => setGithubInstallation(null));
  }, [currentProjectId, githubStatus?.enabled]);

  async function handleConnectGithub() {
    if (!currentProjectId) return;
    setGithubBusy(true);
    setGithubError("");
    try {
      const redirectUri = `${window.location.origin}/github/callback`;
      const { url } = await getGithubAuthUrl(redirectUri);
      window.location.href = url;
    } catch (e: unknown) {
      setGithubBusy(false);
      setGithubError(e instanceof Error ? e.message : "Failed to start GitHub connect");
    }
  }

  async function handleDisconnectGithub() {
    if (!currentProjectId) return;
    if (!confirm("Disconnect this GitHub repo? The local clone will be removed.")) return;
    setGithubBusy(true);
    setGithubError("");
    try {
      await disconnectProjectGithubInstallation();
      setGithubInstallation(null);
    } catch (e: unknown) {
      setGithubError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setGithubBusy(false);
    }
  }

  async function startEditBranch() {
    const inst = githubInstallation;
    if (!inst || !inst.repo_full_name) return;
    setBranchEditing(true);
    setBranchesLoading(true);
    setGithubError("");
    setBranches([]);
    try {
      const list = await listRepoBranches(inst.installation_id, inst.repo_full_name);
      setBranches(list);
    } catch (e: unknown) {
      setGithubError(e instanceof Error ? e.message : "Failed to load branches");
      setBranchEditing(false);
    } finally {
      setBranchesLoading(false);
    }
  }

  async function handleChangeBranch(branch: string) {
    const inst = githubInstallation;
    if (!inst || !inst.repo_full_name || branch === inst.repo_branch) {
      setBranchEditing(false);
      return;
    }
    setBranchSaving(true);
    setGithubError("");
    try {
      const updated = await selectProjectGithubInstallation({
        installation_id: inst.installation_id,
        account_login: inst.account_login,
        account_type: inst.account_type,
        repo_full_name: inst.repo_full_name,
        repo_default_branch: inst.repo_default_branch,
        repo_branch: branch,
      });
      setGithubInstallation(updated);
      setBranchEditing(false);
    } catch (e: unknown) {
      setGithubError(e instanceof Error ? e.message : "Failed to change branch");
    } finally {
      setBranchSaving(false);
    }
  }

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <h2 className="text-lg font-semibold mb-1">GitHub repository</h2>
      <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
        Connect a GitHub repo so the Code Agent can analyse your source on every run.
      </p>
      {!githubStatus ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : !githubStatus.enabled ? (
        <p className="text-sm text-gray-500 dark:text-slate-400">
          No GitHub App is configured for this project yet. Set up the{" "}
          <span className="font-medium">GitHub App</span> above first, then connect a repo.
        </p>
      ) : !currentProject ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 italic">
          No project selected.
        </p>
      ) : githubInstallation && githubInstallation.repo_full_name ? (
        <div className="space-y-3">
          <div className="text-sm">
            <span className="text-gray-500 dark:text-slate-400">Connected repo:</span>{" "}
            <span className="font-mono">{githubInstallation.repo_full_name}</span>
          </div>
          <div className="text-sm flex items-center gap-2">
            <span className="text-gray-500 dark:text-slate-400">Syncing branch:</span>
            {branchEditing ? (
              branchesLoading ? (
                <span className="text-gray-400 dark:text-slate-500">Loading branches…</span>
              ) : (
                <select
                  autoFocus
                  disabled={branchSaving}
                  defaultValue={
                    githubInstallation.repo_branch ||
                    githubInstallation.repo_default_branch ||
                    ""
                  }
                  onChange={(e) => handleChangeBranch(e.target.value)}
                  className="px-2 py-1 text-sm font-mono rounded-md bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 disabled:opacity-50"
                >
                  {branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                      {b === githubInstallation.repo_default_branch ? " (default)" : ""}
                    </option>
                  ))}
                </select>
              )
            ) : (
              <>
                <span className="font-mono">
                  {githubInstallation.repo_branch ||
                    githubInstallation.repo_default_branch ||
                    "main"}
                </span>
                <button
                  onClick={startEditBranch}
                  disabled={githubBusy}
                  className="text-xs text-indigo-500 hover:underline disabled:opacity-50"
                >
                  Change branch
                </button>
              </>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleConnectGithub}
              disabled={githubBusy}
              className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-md disabled:opacity-50"
            >
              Change repo
            </button>
            <button
              onClick={handleDisconnectGithub}
              disabled={githubBusy}
              className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded-md disabled:opacity-50"
            >
              Disconnect
            </button>
          </div>
          {githubStatus.install_url && (
            <p className="text-xs text-gray-400 dark:text-slate-500">
              Need to install the App on another org or repo?{" "}
              <a
                href={githubStatus.install_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-500 hover:underline"
              >
                Open GitHub
              </a>
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <button
            onClick={handleConnectGithub}
            disabled={githubBusy}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
          >
            {githubBusy ? "Starting…" : "Connect GitHub"}
          </button>
          {githubStatus.install_url && (
            <p className="text-xs text-gray-400 dark:text-slate-500">
              First time?{" "}
              <a
                href={githubStatus.install_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-500 hover:underline"
              >
                Install the App on GitHub
              </a>{" "}
              first, then return here and click Connect.
            </p>
          )}
        </div>
      )}
      {githubError && (
        <p className="text-sm text-red-500 mt-3">{githubError}</p>
      )}
    </div>
  );
}
