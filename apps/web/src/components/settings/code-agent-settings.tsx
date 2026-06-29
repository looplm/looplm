"use client";

import { useEffect, useState } from "react";
import { updateProject, type Project } from "@/lib/api";
import { inputClass, labelClass } from "./llm-shared";

interface CodeAgentSettingsProps {
  currentProjectId: string | null;
  projects: Project[];
}

export default function CodeAgentSettings({ currentProjectId, projects }: CodeAgentSettingsProps) {
  const [codeAgentProvider, setCodeAgentProvider] = useState("anthropic");
  const [codeAgentModel, setCodeAgentModel] = useState("");
  const [codeAgentApiKey, setCodeAgentApiKey] = useState("");
  const [codeAgentApiKeyMask, setCodeAgentApiKeyMask] = useState("");
  const [codeAgentAzureEndpoint, setCodeAgentAzureEndpoint] = useState("");
  const [codeAgentAzureApiVersion, setCodeAgentAzureApiVersion] = useState("");
  const [codeAgentSaving, setCodeAgentSaving] = useState(false);
  const [codeAgentMessage, setCodeAgentMessage] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);

  useEffect(() => {
    if (currentProject) {
      const s = currentProject.settings || {};
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProjectId]);

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
  );
}
