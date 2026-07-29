"use client";

import { useEffect, useState } from "react";
import { testCohereRerank, updateProject, type Project } from "@/lib/api";

// Cohere Rerank: a cross-encoder that rescores retrieved chunks against the question. Configured
// here per project (Azure AI Foundry serverless deployment or Cohere's own API), it adds two
// stages on the Retrieval page next to the Azure semantic reranker they are comparable with.
export default function CohereRerankCard({
  currentProjectId,
  currentProject,
  reloadProjects,
}: {
  currentProjectId: string | null;
  currentProject: Project | undefined;
  reloadProjects: () => Promise<void>;
}) {
  const [endpoint, setEndpoint] = useState("");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [pool, setPool] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const s = currentProject?.settings || {};
    // The key comes back masked; leaving it as-is is a no-op on save.
    setEndpoint((s.cohere_rerank_endpoint as string) || "");
    setKey((s.cohere_rerank_key as string) || "");
    setModel((s.cohere_rerank_model as string) || "");
    setPool(Boolean(s.cohere_rerank_pool));
    setMessage("");
  }, [currentProjectId]);

  async function handleSave() {
    if (!currentProjectId) return;
    setSaving(true);
    setMessage("");
    try {
      await updateProject(currentProjectId, {
        settings: {
          cohere_rerank_endpoint: endpoint.trim() || null,
          // A masked key left untouched is skipped server-side, so the stored secret is
          // preserved; a cleared field (null) removes it.
          cohere_rerank_key: key.trim() || null,
          cohere_rerank_model: model.trim() || null,
          cohere_rerank_pool: pool,
        },
      });
      await reloadProjects();
      setMessage("Cohere rerank settings saved");
    } catch (e: any) {
      setMessage(e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!currentProjectId) return;
    setTesting(true);
    setMessage("");
    try {
      const result = await testCohereRerank(currentProjectId);
      setMessage(
        result.ok
          ? `Reranker reachable (${result.model})`
          : result.error || "The reranker did not return a score",
      );
    } catch (e: any) {
      setMessage(e.message || "Test failed");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <h2 className="text-lg font-semibold mb-1">Cohere rerank</h2>
      <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
        A cross-encoder that rescores retrieved chunks against the question. When set, two stages
        appear on the Retrieval page: <strong>Cohere rerank</strong> (the same hybrid top-50 the
        Azure semantic reranker sees, so the two are directly comparable) and{" "}
        <strong>Agentic + Cohere</strong> (the whole agentic pool scored against your original
        question in one pass, which the positional first-wins merge cannot do).
      </p>
      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Endpoint</label>
          <input
            type="text"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="https://your-deployment.eastus.models.ai.azure.com"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            An Azure AI Foundry serverless Cohere deployment, or{" "}
            <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">https://api.cohere.com</code>{" "}
            for Cohere&apos;s own API.{" "}
            <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">/v2/rerank</code> is
            appended unless the URL already names a route. Leave blank to disable both stages.
          </p>
        </div>

        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">API key</label>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Deployment key"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            Sent as a bearer token, falling back to the{" "}
            <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">api-key</code> header for
            deployments that require it. Stored masked; leave unchanged to keep the current value.
          </p>
        </div>

        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
            Model (optional)
          </label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="rerank-v3.5"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            Defaults to <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">rerank-v3.5</code>{" "}
            (multilingual). Changing it re-scores from scratch rather than reusing cached scores.
          </p>
        </div>

        <div>
          <label className="flex items-start gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={pool}
              onChange={(e) => setPool(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-500 dark:text-slate-400">
              Order labeling pools by Cohere relevance
            </span>
          </label>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1 ml-6">
            Each candidate gets a Cohere score badge and the pool leads with the highest-scoring
            chunks, whichever head found them. Nothing is hidden, only reordered. Costs one rerank
            call per case the first time it is opened (cached for 6 hours). The Retrieval page
            scores both Cohere stages regardless of this setting.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onClick={handleTest}
            disabled={testing || saving}
            className="px-4 py-2 border border-gray-200 dark:border-slate-700 rounded-lg text-sm hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            {testing ? "Testing..." : "Test connection"}
          </button>
        </div>

        {message && <p className="text-sm text-gray-500 dark:text-slate-400">{message}</p>}
      </div>
    </div>
  );
}
