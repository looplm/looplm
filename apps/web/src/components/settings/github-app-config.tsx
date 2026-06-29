"use client";

import { useEffect, useState } from "react";
import {
  deleteProjectGithubAppConfig,
  getGithubStatus,
  getProjectGithubAppConfig,
  saveProjectGithubAppConfig,
  type GithubAppConfig,
  type GithubStatus,
} from "@/lib/api";
import { inputClass, labelClass } from "./llm-shared";

interface GithubAppConfigSectionProps {
  currentProjectId: string | null;
  setGithubStatus: (status: GithubStatus) => void;
}

export default function GithubAppConfigSection({
  currentProjectId,
  setGithubStatus,
}: GithubAppConfigSectionProps) {
  const [appConfig, setAppConfig] = useState<GithubAppConfig | null>(null);
  const [appForm, setAppForm] = useState({
    app_id: "",
    app_name: "",
    client_id: "",
    client_secret: "",
    private_key: "",
  });
  const [appEditing, setAppEditing] = useState(false);
  const [appBusy, setAppBusy] = useState(false);
  const [appError, setAppError] = useState("");
  const [appSaved, setAppSaved] = useState(false);

  useEffect(() => {
    if (!currentProjectId) {
      setAppConfig(null);
      return;
    }
    setAppEditing(false);
    setAppSaved(false);
    getProjectGithubAppConfig()
      .then(setAppConfig)
      .catch(() => setAppConfig(null));
  }, [currentProjectId]);

  function startEditAppConfig() {
    setAppForm({
      app_id: appConfig?.source === "project" ? appConfig.app_id ?? "" : "",
      app_name: appConfig?.source === "project" ? appConfig.app_name ?? "" : "",
      client_id: appConfig?.source === "project" ? appConfig.client_id ?? "" : "",
      client_secret: "",
      private_key: "",
    });
    setAppError("");
    setAppSaved(false);
    setAppEditing(true);
  }

  async function handleSaveAppConfig() {
    if (!currentProjectId) return;
    setAppBusy(true);
    setAppError("");
    setAppSaved(false);
    try {
      const isNew = appConfig?.source !== "project";
      const body = {
        app_id: appForm.app_id.trim(),
        app_name: appForm.app_name.trim() || null,
        client_id: appForm.client_id.trim(),
        // Write-only: only send secrets when provided.
        ...(appForm.client_secret.trim() ? { client_secret: appForm.client_secret.trim() } : {}),
        ...(appForm.private_key.trim() ? { private_key: appForm.private_key } : {}),
      };
      if (isNew && (!body.client_secret || !body.private_key)) {
        throw new Error("Client secret and private key are required when first configuring the App.");
      }
      const updated = await saveProjectGithubAppConfig(body);
      setAppConfig(updated);
      setAppForm((f) => ({ ...f, client_secret: "", private_key: "" }));
      setAppEditing(false);
      setAppSaved(true);
      setTimeout(() => setAppSaved(false), 3000);
      // Creds changed — refresh repo status (it may have just become enabled).
      getGithubStatus()
        .then(setGithubStatus)
        .catch(() => undefined);
    } catch (e: unknown) {
      setAppError(e instanceof Error ? e.message : "Failed to save GitHub App config");
    } finally {
      setAppBusy(false);
    }
  }

  async function handleDeleteAppConfig() {
    if (!currentProjectId) return;
    if (!confirm("Remove this project's GitHub App credentials? It will fall back to the instance default if one is configured.")) {
      return;
    }
    setAppBusy(true);
    setAppError("");
    try {
      await deleteProjectGithubAppConfig();
      const [cfg] = await Promise.all([getProjectGithubAppConfig()]);
      setAppConfig(cfg);
      setAppEditing(false);
      getGithubStatus()
        .then(setGithubStatus)
        .catch(() => undefined);
    } catch (e: unknown) {
      setAppError(e instanceof Error ? e.message : "Failed to remove GitHub App config");
    } finally {
      setAppBusy(false);
    }
  }

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <h2 className="text-lg font-semibold mb-1">GitHub App</h2>
      <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
        Each project authenticates to GitHub with its own GitHub App. Register one at{" "}
        <span className="font-mono text-xs">github.com/settings/apps</span> and paste its
        credentials here. Leave it blank to use the instance default, if one is set.
      </p>
      {!currentProjectId ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 italic">No project selected.</p>
      ) : !appConfig ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : appEditing ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>App ID</label>
              <input
                type="text"
                value={appForm.app_id}
                onChange={(e) => setAppForm((f) => ({ ...f, app_id: e.target.value }))}
                placeholder="123456"
                className={`${inputClass} font-mono`}
              />
            </div>
            <div>
              <label className={labelClass}>App name (slug)</label>
              <input
                type="text"
                value={appForm.app_name}
                onChange={(e) => setAppForm((f) => ({ ...f, app_name: e.target.value }))}
                placeholder="my-looplm-app"
                className={`${inputClass} font-mono`}
              />
            </div>
          </div>
          <div>
            <label className={labelClass}>Client ID</label>
            <input
              type="text"
              value={appForm.client_id}
              onChange={(e) => setAppForm((f) => ({ ...f, client_id: e.target.value }))}
              placeholder="Iv1.abc123..."
              className={`${inputClass} font-mono`}
            />
          </div>
          <div>
            <label className={labelClass}>Client secret</label>
            <input
              type="password"
              value={appForm.client_secret}
              onChange={(e) => setAppForm((f) => ({ ...f, client_secret: e.target.value }))}
              placeholder={
                appConfig.source === "project"
                  ? "Saved — leave blank to keep current secret"
                  : "GitHub App client secret"
              }
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass}>Private key (PEM)</label>
            <textarea
              value={appForm.private_key}
              onChange={(e) => setAppForm((f) => ({ ...f, private_key: e.target.value }))}
              rows={4}
              placeholder={
                appConfig.source === "project"
                  ? "Saved — leave blank to keep current key"
                  : "-----BEGIN RSA PRIVATE KEY-----\n…"
              }
              className={`${inputClass} font-mono text-xs`}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleSaveAppConfig}
              disabled={appBusy}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
            >
              {appBusy ? "Saving…" : "Save App"}
            </button>
            <button
              onClick={() => {
                setAppEditing(false);
                setAppError("");
              }}
              disabled={appBusy}
              className="px-3 py-2 text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-sm space-y-1">
            {appConfig.source === "project" ? (
              <>
                <div>
                  <span className="text-gray-500 dark:text-slate-400">App:</span>{" "}
                  <span className="font-mono">{appConfig.app_name || appConfig.app_id}</span>
                  <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-300">
                    this project
                  </span>
                </div>
                <div className="text-xs text-gray-400 dark:text-slate-500">
                  Client ID <span className="font-mono">{appConfig.client_id}</span> · secret &amp; key saved
                </div>
              </>
            ) : appConfig.source === "env" ? (
              <div className="text-gray-500 dark:text-slate-400">
                Using the instance default App{" "}
                <span className="font-mono">{appConfig.app_name || appConfig.app_id}</span>. Add
                project-specific credentials to override it.
              </div>
            ) : (
              <div className="text-gray-500 dark:text-slate-400">
                No GitHub App configured for this project.
              </div>
            )}
          </div>
          {appConfig.can_manage ? (
            <div className="flex gap-2">
              <button
                onClick={startEditAppConfig}
                disabled={appBusy}
                className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-md disabled:opacity-50"
              >
                {appConfig.source === "project" ? "Edit credentials" : "Configure App"}
              </button>
              {appConfig.source === "project" && (
                <button
                  onClick={handleDeleteAppConfig}
                  disabled={appBusy}
                  className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded-md disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-400 dark:text-slate-500">
              Only project admins can change the GitHub App credentials.
            </p>
          )}
        </div>
      )}
      {appError && <p className="text-sm text-red-500 mt-3">{appError}</p>}
      {appSaved && <p className="text-sm text-green-600 mt-3">GitHub App saved.</p>}
    </div>
  );
}
