"use client";

import { useEffect, useState } from "react";
import { updateProject, type Project } from "@/lib/api";

// Custom-agent retrieval: an external endpoint that returns a ranked chunk list without
// generating an answer, scored as its own stage on the Retrieval page and (opt-in) pooled as
// its own head for labeling.
export default function AgentRetrievalCard({
  currentProjectId,
  currentProject,
  reloadProjects,
}: {
  currentProjectId: string | null;
  currentProject: Project | undefined;
  reloadProjects: () => Promise<void>;
}) {
  const [endpoint, setEndpoint] = useState("");
  const [token, setToken] = useState("");
  const [label, setLabel] = useState("");
  const [pool, setPool] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const s = currentProject?.settings || {};
    // The token comes back masked; leaving it as-is is a no-op on save.
    setEndpoint((s.agent_retrieval_endpoint as string) || "");
    setToken((s.agent_retrieval_token as string) || "");
    setLabel((s.agent_retrieval_label as string) || "");
    setPool(Boolean(s.agent_retrieval_pool));
    setMessage("");
  }, [currentProjectId]);

  async function handleSave() {
    if (!currentProjectId) return;
    setSaving(true);
    setMessage("");
    try {
      await updateProject(currentProjectId, {
        settings: {
          agent_retrieval_endpoint: endpoint.trim() || null,
          // A masked token (contains "...") left untouched is skipped server-side, so the
          // stored secret is preserved; a cleared field (null) removes it.
          agent_retrieval_token: token.trim() || null,
          agent_retrieval_label: label.trim() || null,
          agent_retrieval_pool: pool,
        },
      });
      await reloadProjects();
      setMessage("Custom agent retrieval settings saved");
    } catch (e: any) {
      setMessage(e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <h2 className="text-lg font-semibold mb-1">Custom agent retrieval</h2>
      <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
        A retrieval-only endpoint on your agent that returns a ranked chunk list without
        generating an answer (e.g. rde-gpt&apos;s <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">/api/chat/retrieval</code>).
        When set, your agent&apos;s real ranking is scored as its own stage on the Retrieval page,
        alongside sparse/dense/RRF/reranked/agentic.
      </p>
      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
            Retrieval Endpoint
          </label>
          <input
            type="text"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="https://your-agent/api/chat/retrieval"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            URL that, given a query, returns <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">rankedChunks</code> (or
            <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">searchSources</code>) at chunk granularity. Leave blank to disable the stage.
          </p>
        </div>

        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">Token</label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="X-Eval-Token value"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            Sent as the <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">X-Eval-Token</code> header. Stored masked; leave unchanged to keep the current value.
          </p>
        </div>

        <div>
          <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
            Display Label (optional)
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Custom agent"
            className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
          />
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
            Name shown for this stage on the Retrieval page (defaults to &quot;Custom agent&quot;).
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
              Add the agent&apos;s chunks to labeling pools
            </span>
          </label>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-1 ml-6">
            The agent&apos;s top chunks become their own head in the candidate pool, so its finds
            get judged instead of counting as misses. Judging volume grows by roughly one head;
            existing labels are kept and only the new chunks need grading. Gold changes, so scores
            shift for every stage and stop matching runs computed before this.
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
        </div>

        {message && <p className="text-sm text-gray-500 dark:text-slate-400">{message}</p>}
      </div>
    </div>
  );
}
