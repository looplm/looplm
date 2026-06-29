"use client";

import { useEffect, useState } from "react";
import { updateProject, type Project } from "@/lib/api";
import { inputClass, labelClass, type Provider } from "./llm-shared";

interface EvaluatorLlmProps {
  currentProjectId: string | null;
  projects: Project[];
}

export default function EvaluatorLlm({ currentProjectId, projects }: EvaluatorLlmProps) {
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
  // Query embeddings (vector/hybrid retrieval) — reuse the creds above, dedicated model.
  const [azureEmbeddingDeployment, setAzureEmbeddingDeployment] = useState("");
  const [openaiEmbeddingModel, setOpenaiEmbeddingModel] = useState("");
  const [embeddingDimensions, setEmbeddingDimensions] = useState("");
  // Masked secret values from the projects API (shown as placeholders)
  const [openaiKeyMask, setOpenaiKeyMask] = useState("");
  const [azureKeyMask, setAzureKeyMask] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);

  useEffect(() => {
    if (currentProject) {
      const s = currentProject.settings || {};
      const evalProvider = (s.llm_provider as string) || "openai";
      setProvider(evalProvider === "azure_openai" ? "azure_openai" : "openai");
      setOpenaiKey("");
      setAzureKey("");
      setOpenaiKeyMask((s.openai_api_key as string) || "");
      setAzureKeyMask((s.azure_openai_api_key as string) || "");
      setAzureEndpoint((s.azure_openai_endpoint as string) || "");
      setAzureDeployment((s.azure_openai_deployment as string) || "");
      setAzureApiVersion((s.azure_openai_api_version as string) || "");
      setAzureEmbeddingDeployment((s.azure_openai_embedding_deployment as string) || "");
      setOpenaiEmbeddingModel((s.openai_embedding_model as string) || "");
      setEmbeddingDimensions(s.embedding_dimensions != null ? String(s.embedding_dimensions) : "");
      setError("");
      setSaved(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        settings.openai_embedding_model = openaiEmbeddingModel.trim();
      } else {
        if (azureKey.trim()) settings.azure_openai_api_key = azureKey.trim();
        settings.azure_openai_endpoint = azureEndpoint.trim();
        settings.azure_openai_deployment = azureDeployment.trim();
        settings.azure_openai_api_version = azureApiVersion.trim();
        settings.azure_openai_embedding_deployment = azureEmbeddingDeployment.trim();
      }
      const dims = parseInt(embeddingDimensions.trim(), 10);
      settings.embedding_dimensions = Number.isFinite(dims) && dims > 0 ? dims : null;
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

  return (
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
          <>
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
            <div>
              <label className={labelClass}>Embedding Model</label>
              <input
                type="text"
                value={openaiEmbeddingModel}
                onChange={(e) => setOpenaiEmbeddingModel(e.target.value)}
                placeholder="text-embedding-3-large"
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">
                Used to embed queries for vector/hybrid retrieval. Must match the model that built
                your index&apos;s vector field, or results are meaningless.
              </p>
            </div>
            <div>
              <label className={labelClass}>Embedding Dimensions</label>
              <input
                type="number"
                value={embeddingDimensions}
                onChange={(e) => setEmbeddingDimensions(e.target.value)}
                placeholder="3072"
                className={inputClass}
              />
            </div>
          </>
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
            <div>
              <label className={labelClass}>Embedding Deployment</label>
              <input
                type="text"
                value={azureEmbeddingDeployment}
                onChange={(e) => setAzureEmbeddingDeployment(e.target.value)}
                placeholder="text-embedding-3-large"
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">
                Used to embed queries for vector/hybrid retrieval (reuses the key/endpoint above).
                Must match the model that built your index&apos;s vector field, or results are
                meaningless. Leave blank to disable vector search.
              </p>
            </div>
            <div>
              <label className={labelClass}>Embedding Dimensions</label>
              <input
                type="number"
                value={embeddingDimensions}
                onChange={(e) => setEmbeddingDimensions(e.target.value)}
                placeholder="3072"
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
  );
}
