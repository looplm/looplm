"use client";

import { useEffect, useState } from "react";
import {
  getUserSettings,
  updateUserSettings,
  updateProject,
  type UserSettings,
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
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const [provider, setProvider] = useState<Provider>("openai");
  const [openaiKey, setOpenaiKey] = useState("");
  const [azureKey, setAzureKey] = useState("");
  const [azureEndpoint, setAzureEndpoint] = useState("");
  const [azureDeployment, setAzureDeployment] = useState("");
  const [azureApiVersion, setAzureApiVersion] = useState("");

  // Masked values from API (shown as placeholders)
  const [masked, setMasked] = useState<UserSettings | null>(null);

  // Code Agent LLM (project-level)
  const [codeAgentProvider, setCodeAgentProvider] = useState("anthropic");
  const [codeAgentModel, setCodeAgentModel] = useState("");
  const [codeAgentApiKey, setCodeAgentApiKey] = useState("");
  const [codeAgentApiKeyMask, setCodeAgentApiKeyMask] = useState("");
  const [codeAgentFoundryResource, setCodeAgentFoundryResource] = useState("");
  const [codeAgentSaving, setCodeAgentSaving] = useState(false);
  const [codeAgentMessage, setCodeAgentMessage] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);

  async function loadSettings() {
    try {
      const data = await getUserSettings();
      setMasked(data);
      if (data.llm_provider === "openai" || data.llm_provider === "azure_openai") {
        setProvider(data.llm_provider);
      }
      // Non-secret fields can be pre-filled
      setAzureEndpoint(data.azure_openai_endpoint);
      setAzureDeployment(data.azure_openai_deployment);
      setAzureApiVersion(data.azure_openai_api_version);
    } catch {
      // Settings not available yet — use defaults
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSettings();
  }, []);

  useEffect(() => {
    if (currentProject) {
      const s = currentProject.settings || {};
      setCodeAgentProvider((s.code_agent_provider as string) || "anthropic");
      setCodeAgentModel((s.code_agent_model as string) || "");
      setCodeAgentApiKey("");
      setCodeAgentApiKeyMask((s.code_agent_api_key as string) || "");
      setCodeAgentFoundryResource((s.code_agent_foundry_resource as string) || "");
    }
    setCodeAgentMessage("");
  }, [currentProjectId]);

  async function handleSave() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const body: Record<string, string> = { llm_provider: provider };
      if (provider === "openai") {
        if (openaiKey) body.openai_api_key = openaiKey;
      } else {
        if (azureKey) body.azure_openai_api_key = azureKey;
        body.azure_openai_endpoint = azureEndpoint;
        body.azure_openai_deployment = azureDeployment;
        body.azure_openai_api_version = azureApiVersion;
      }
      const data = await updateUserSettings(body);
      setMasked(data);
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

  async function handleSaveCodeAgent() {
    if (!currentProjectId) return;
    setCodeAgentSaving(true);
    setCodeAgentMessage("");
    try {
      const settings: Record<string, unknown> = {
        code_agent_provider: codeAgentProvider,
        code_agent_model: codeAgentModel.trim() || null,
        code_agent_foundry_resource:
          codeAgentProvider === "azure_foundry"
            ? codeAgentFoundryResource.trim() || null
            : null,
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

  if (loading) {
    return (
      <div className="max-w-2xl">
        <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-sm text-gray-400">Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-4">Evaluator LLM</h2>
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
                placeholder={masked?.openai_api_key || "sk-..."}
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
                  placeholder={masked?.azure_openai_api_key || "Enter API key"}
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
                  <option value="azure_foundry">Azure AI Foundry</option>
                </select>
              </div>
              <div>
                <label className={labelClass}>Model</label>
                <input
                  type="text"
                  value={codeAgentModel}
                  onChange={(e) => setCodeAgentModel(e.target.value)}
                  placeholder="claude-sonnet-4-6"
                  className={`${inputClass} font-mono`}
                />
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                  Leave blank for the SDK default.
                </p>
              </div>
            </div>

            <div>
              <label className={labelClass}>API Key</label>
              <input
                type="password"
                value={codeAgentApiKey}
                onChange={(e) => setCodeAgentApiKey(e.target.value)}
                placeholder={codeAgentApiKeyMask || (codeAgentProvider === "azure_foundry" ? "Azure AI Foundry API key" : "sk-ant-...")}
                className={inputClass}
              />
              <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                {codeAgentApiKeyMask
                  ? "Key saved. Leave blank to keep current key, or enter a new one to replace it."
                  : codeAgentProvider === "azure_foundry"
                    ? "Your Azure AI Foundry API key."
                    : "Your Anthropic API key."}
              </p>
            </div>

            {codeAgentProvider === "azure_foundry" && (
              <div>
                <label className={labelClass}>Azure AI Foundry Resource</label>
                <input
                  type="text"
                  value={codeAgentFoundryResource}
                  onChange={(e) => setCodeAgentFoundryResource(e.target.value)}
                  placeholder="my-azure-resource"
                  className={`${inputClass} font-mono`}
                />
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
                  The Azure resource name (used as https://&#123;resource&#125;.services.ai.azure.com/anthropic).
                </p>
              </div>
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
