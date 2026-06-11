"use client";

import { useEffect, useState } from "react";
import {
  deleteProjectGithubAppConfig,
  disconnectProjectGithubInstallation,
  getGithubAuthUrl,
  getGithubStatus,
  getProjectGithubAppConfig,
  getProjectGithubInstallation,
  listRepoBranches,
  saveProjectGithubAppConfig,
  selectProjectGithubInstallation,
  updateProject,
  type GithubAppConfig,
  type GithubInstallation,
  type GithubStatus,
  type Project,
} from "@/lib/api";

type Provider = "openai" | "azure_openai";

const inputClass =
  "w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm";
const labelClass = "block text-sm text-gray-500 dark:text-slate-400 mb-1";

interface GeneralSettingsProps {
  currentProjectId: string | null;
  projects: Project[];
}

export default function GeneralSettings({ currentProjectId, projects }: GeneralSettingsProps) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // Evaluator LLM (project-level — shared by all project members)
  const [provider, setProvider] = useState<Provider>("openai");
  const [openaiKey, setOpenaiKey] = useState("");
  const [azureKey, setAzureKey] = useState("");
  const [azureEndpoint, setAzureEndpoint] = useState("");
  const [azureDeployment, setAzureDeployment] = useState("");
  const [azureApiVersion, setAzureApiVersion] = useState("");
  // Masked secret values from the projects API (shown as placeholders)
  const [openaiKeyMask, setOpenaiKeyMask] = useState("");
  const [azureKeyMask, setAzureKeyMask] = useState("");

  // GitHub bridge (project-level)
  const [githubStatus, setGithubStatus] = useState<GithubStatus | null>(null);
  const [githubInstallation, setGithubInstallation] = useState<GithubInstallation | null>(null);
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubError, setGithubError] = useState("");

  // Inline branch switcher for an already-connected repo.
  const [branchEditing, setBranchEditing] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchSaving, setBranchSaving] = useState(false);

  // GitHub App identity (per-project; admins only)
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

  // Code Agent LLM (project-level)
  const [codeAgentProvider, setCodeAgentProvider] = useState("anthropic");
  const [codeAgentModel, setCodeAgentModel] = useState("");
  const [codeAgentApiKey, setCodeAgentApiKey] = useState("");
  const [codeAgentApiKeyMask, setCodeAgentApiKeyMask] = useState("");
  const [codeAgentAzureEndpoint, setCodeAgentAzureEndpoint] = useState("");
  const [codeAgentAzureApiVersion, setCodeAgentAzureApiVersion] = useState("");
  const [codeAgentSaving, setCodeAgentSaving] = useState(false);
  const [codeAgentMessage, setCodeAgentMessage] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);

  // GitHub status, App config and the repo link are all per-project, so they
  // re-fetch whenever the active project changes.
  useEffect(() => {
    if (!currentProjectId) {
      setGithubStatus(null);
      setGithubInstallation(null);
      setAppConfig(null);
      return;
    }
    setAppEditing(false);
    setAppSaved(false);
    getGithubStatus()
      .then(setGithubStatus)
      .catch(() => setGithubStatus({ enabled: false, app_name: null, install_url: null }));
    getProjectGithubAppConfig()
      .then(setAppConfig)
      .catch(() => setAppConfig(null));
  }, [currentProjectId]);

  useEffect(() => {
    if (!currentProjectId || !githubStatus?.enabled) {
      setGithubInstallation(null);
      return;
    }
    getProjectGithubInstallation()
      .then(setGithubInstallation)
      .catch(() => setGithubInstallation(null));
  }, [currentProjectId, githubStatus?.enabled]);

  useEffect(() => {
    if (currentProject) {
      const s = currentProject.settings || {};

      // Evaluator LLM (project-level)
      const evalProvider = (s.llm_provider as string) || "openai";
      setProvider(evalProvider === "azure_openai" ? "azure_openai" : "openai");
      setOpenaiKey("");
      setAzureKey("");
      setOpenaiKeyMask((s.openai_api_key as string) || "");
      setAzureKeyMask((s.azure_openai_api_key as string) || "");
      setAzureEndpoint((s.azure_openai_endpoint as string) || "");
      setAzureDeployment((s.azure_openai_deployment as string) || "");
      setAzureApiVersion((s.azure_openai_api_version as string) || "");
      setError("");
      setSaved(false);

      // Code Agent LLM (project-level)
      const storedProvider = (s.code_agent_provider as string) || "anthropic";
      // Legacy values that are no longer supported fall back to anthropic in the UI.
      const isSupported = ["openai", "anthropic", "azure_openai"].includes(storedProvider);
      setCodeAgentProvider(isSupported ? storedProvider : "anthropic");
      setCodeAgentModel((s.code_agent_model as string) || "");
      setCodeAgentApiKey("");
      setCodeAgentApiKeyMask((s.code_agent_api_key as string) || "");
      setCodeAgentAzureEndpoint((s.code_agent_azure_endpoint as string) || "");
      setCodeAgentAzureApiVersion((s.code_agent_azure_api_version as string) || "");
    }
    setCodeAgentMessage("");
  }, [currentProjectId]);

  async function handleSave() {
    if (!currentProjectId) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const settings: Record<string, unknown> = { llm_provider: provider };
      if (provider === "openai") {
        if (openaiKey.trim()) settings.openai_api_key = openaiKey.trim();
      } else {
        if (azureKey.trim()) settings.azure_openai_api_key = azureKey.trim();
        settings.azure_openai_endpoint = azureEndpoint.trim();
        settings.azure_openai_deployment = azureDeployment.trim();
        settings.azure_openai_api_version = azureApiVersion.trim();
      }
      const updated = await updateProject(currentProjectId, { settings });
      const s = updated.settings || {};
      setOpenaiKeyMask((s.openai_api_key as string) || "");
      setAzureKeyMask((s.azure_openai_api_key as string) || "");
      // Clear password fields after save
      setOpenaiKey("");
      setAzureKey("");
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

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

  async function handleSaveCodeAgent() {
    if (!currentProjectId) return;
    setCodeAgentSaving(true);
    setCodeAgentMessage("");
    try {
      const isAzure = codeAgentProvider === "azure_openai";
      const settings: Record<string, unknown> = {
        code_agent_provider: codeAgentProvider,
        code_agent_model: codeAgentModel.trim() || null,
        code_agent_azure_endpoint: isAzure ? codeAgentAzureEndpoint.trim() || null : null,
        code_agent_azure_api_version: isAzure ? codeAgentAzureApiVersion.trim() || null : null,
      };
      if (codeAgentApiKey.trim()) {
        settings.code_agent_api_key = codeAgentApiKey.trim();
      }

      const updated = await updateProject(currentProjectId, { settings });
      const s = updated.settings || {};
      setCodeAgentApiKey("");
      setCodeAgentApiKeyMask((s.code_agent_api_key as string) || "");
      setCodeAgentMessage("Code Agent LLM settings saved");
    } catch (e: unknown) {
      setCodeAgentMessage(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setCodeAgentSaving(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">Evaluator LLM</h2>
        <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
          {currentProject
            ? <>LLM used for analysis, evaluations and feedback insights in project: <span className="font-medium text-gray-600 dark:text-slate-300">{currentProject.name}</span>. Shared by all members.</>
            : "Select a project to configure the Evaluator LLM."}
        </p>
        {currentProject ? (
        <div className="space-y-4">
          {/* Provider selector */}
          <div>
            <label className={labelClass}>Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as Provider)}
              className={inputClass}
            >
              <option value="openai">OpenAI</option>
              <option value="azure_openai">Azure OpenAI</option>
            </select>
          </div>

          {provider === "openai" && (
            <div>
              <label className={labelClass}>OpenAI API Key</label>
              <input
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder={openaiKeyMask || "sk-..."}
                className={inputClass}
              />
            </div>
          )}

          {provider === "azure_openai" && (
            <>
              <div>
                <label className={labelClass}>Azure OpenAI API Key</label>
                <input
                  type="password"
                  value={azureKey}
                  onChange={(e) => setAzureKey(e.target.value)}
                  placeholder={azureKeyMask || "Enter API key"}
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Endpoint</label>
                <input
                  type="url"
                  value={azureEndpoint}
                  onChange={(e) => setAzureEndpoint(e.target.value)}
                  placeholder="https://your-resource.openai.azure.com"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Deployment Name</label>
                <input
                  type="text"
                  value={azureDeployment}
                  onChange={(e) => setAzureDeployment(e.target.value)}
                  placeholder="gpt-4o"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>API Version</label>
                <input
                  type="text"
                  value={azureApiVersion}
                  onChange={(e) => setAzureApiVersion(e.target.value)}
                  placeholder="2024-10-21"
                  className={inputClass}
                />
              </div>
            </>
          )}

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {saving ? "Saving..." : saved ? "Saved!" : "Save"}
          </button>
        </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-slate-500 italic">
            No project selected. Go to the Project tab to create or select one.
          </p>
        )}
      </div>

      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">GitHub App</h2>
        <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
          Each project authenticates to GitHub with its own GitHub App. Register one at{" "}
          <span className="font-mono text-xs">github.com/settings/apps</span> and paste its
          credentials here. Leave it blank to use the instance default, if one is set.
        </p>
        {!currentProject ? (
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

      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">Code Agent LLM</h2>
        <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
          {currentProject
            ? <>LLM provider for AI code suggestions in project: <span className="font-medium text-gray-600 dark:text-slate-300">{currentProject.name}</span></>
            : "Select a project to configure the Code Agent LLM."}
        </p>
        {currentProject ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Provider</label>
                <select
                  value={codeAgentProvider}
                  onChange={(e) => setCodeAgentProvider(e.target.value)}
                  className={inputClass}
                >
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="azure_openai">Azure OpenAI</option>
                </select>
              </div>
              <div>
                <label className={labelClass}>
                  {codeAgentProvider === "azure_openai" ? "Deployment Name" : "Model"}
                </label>
                <input
                  type="text"
                  value={codeAgentModel}
                  onChange={(e) => setCodeAgentModel(e.target.value)}
                  placeholder={
                    codeAgentProvider === "azure_openai"
                      ? "gpt-4o"
                      : codeAgentProvider === "openai"
                        ? "gpt-4o"
                        : "claude-sonnet-4-20250514"
                  }
                  className={`${inputClass} font-mono`}
                />
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                  {codeAgentProvider === "azure_openai"
                    ? "Required: the Azure deployment name."
                    : "Leave blank for the provider's default model."}
                </p>
              </div>
            </div>

            <div>
              <label className={labelClass}>API Key</label>
              <input
                type="password"
                value={codeAgentApiKey}
                onChange={(e) => setCodeAgentApiKey(e.target.value)}
                placeholder={
                  codeAgentApiKeyMask ||
                  (codeAgentProvider === "openai"
                    ? "sk-..."
                    : codeAgentProvider === "azure_openai"
                      ? "Azure OpenAI API key"
                      : "sk-ant-...")
                }
                className={inputClass}
              />
              <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                {codeAgentApiKeyMask
                  ? "Key saved. Leave blank to keep current key, or enter a new one to replace it."
                  : codeAgentProvider === "openai"
                    ? "Your OpenAI API key."
                    : codeAgentProvider === "azure_openai"
                      ? "Your Azure OpenAI API key."
                      : "Your Anthropic API key."}
              </p>
            </div>

            {codeAgentProvider === "azure_openai" && (
              <>
                <div>
                  <label className={labelClass}>Endpoint</label>
                  <input
                    type="url"
                    value={codeAgentAzureEndpoint}
                    onChange={(e) => setCodeAgentAzureEndpoint(e.target.value)}
                    placeholder="https://your-resource.openai.azure.com"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>API Version</label>
                  <input
                    type="text"
                    value={codeAgentAzureApiVersion}
                    onChange={(e) => setCodeAgentAzureApiVersion(e.target.value)}
                    placeholder="2024-10-21"
                    className={inputClass}
                  />
                </div>
              </>
            )}

            {codeAgentMessage && (
              <p className="text-sm text-gray-500 dark:text-slate-400">{codeAgentMessage}</p>
            )}

            <button
              onClick={handleSaveCodeAgent}
              disabled={codeAgentSaving}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {codeAgentSaving ? "Saving..." : "Save"}
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-slate-500 italic">
            No project selected. Go to the Project tab to create or select one.
          </p>
        )}
      </div>
    </div>
  );
}
