"use client";

import { useEffect, useState } from "react";
import { updateProject, type Project } from "@/lib/api";

interface EvaluationsSettingsProps {
  currentProjectId: string | null;
  projects: Project[];
  reloadProjects: () => Promise<void>;
}

export default function EvaluationsSettings({
  currentProjectId,
  projects,
  reloadProjects,
}: EvaluationsSettingsProps) {
  const [endpoint, setEndpoint] = useState("");
  const [requestTemplate, setRequestTemplate] = useState("");
  const [responsePath, setResponsePath] = useState("");
  const [extraHeaders, setExtraHeaders] = useState("");
  const [maxTurns, setMaxTurns] = useState(1);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; response?: string; error?: string } | null>(null);

  // Code Agent settings (non-LLM — LLM config is on the AI Models tab)
  const [repoPath, setRepoPath] = useState("");
  const [filePatterns, setFilePatterns] = useState("");
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const [codeAgentSaving, setOpencodeSaving] = useState(false);
  const [codeAgentMessage, setCodeAgentMessage] = useState("");

  const currentProject = projects.find((p) => p.id === currentProjectId);

  useEffect(() => {
    if (currentProject) {
      const s = currentProject.settings || {};
      setEndpoint((s.eval_target_endpoint as string) || "");
      setRequestTemplate(
        s.eval_request_template
          ? JSON.stringify(s.eval_request_template, null, 2)
          : '{\n  "messages": [{"role": "user", "content": "{prompt}"}]\n}'
      );
      setResponsePath((s.eval_response_path as string) || "choices.0.message.content");
      setExtraHeaders(
        s.eval_extra_headers
          ? JSON.stringify(s.eval_extra_headers, null, 2)
          : "{}"
      );
      setMaxTurns((s.eval_max_turns as number) || 1);
      // Code Agent
      setRepoPath((s.code_agent_repo_path as string) || "");
      const patterns = s.code_agent_file_patterns as string[] | undefined;
      setFilePatterns(patterns ? patterns.join("\n") : "**/*.py\n**/*.ts\n**/*.js");
      setAutoAnalyze(Boolean(s.code_agent_auto_analyze));
    }
    setMessage("");
    setTestResult(null);
    setCodeAgentMessage("");
  }, [currentProjectId]);

  async function handleSave() {
    if (!currentProjectId) return;
    setSaving(true);
    setMessage("");
    try {
      let parsedTemplate: unknown;
      try {
        parsedTemplate = JSON.parse(requestTemplate);
      } catch {
        setMessage("Invalid JSON in Request Body Template");
        setSaving(false);
        return;
      }

      let parsedHeaders: unknown;
      try {
        parsedHeaders = JSON.parse(extraHeaders);
      } catch {
        setMessage("Invalid JSON in Extra Headers");
        setSaving(false);
        return;
      }

      await updateProject(currentProjectId, {
        settings: {
          eval_target_endpoint: endpoint.trim() || null,
          eval_request_template: parsedTemplate,
          eval_response_path: responsePath.trim() || null,
          eval_extra_headers: parsedHeaders,
          eval_max_turns: maxTurns,
        },
      });
      await reloadProjects();
      setMessage("Evaluation settings saved");
    } catch (e: any) {
      setMessage(e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      let parsedTemplate: unknown;
      try {
        parsedTemplate = JSON.parse(requestTemplate);
      } catch {
        setTestResult({ success: false, error: "Invalid JSON in Request Body Template" });
        setTesting(false);
        return;
      }

      let parsedHeaders: unknown;
      try {
        parsedHeaders = JSON.parse(extraHeaders);
      } catch {
        setTestResult({ success: false, error: "Invalid JSON in Extra Headers" });
        setTesting(false);
        return;
      }

      const { request } = await import("@/lib/api/client");
      const result = await request<{ success: boolean; response?: string; error?: string }>(
        "/api/evals/trigger/test-connection",
        {
          method: "POST",
          body: JSON.stringify({
            endpoint: endpoint.trim(),
            request_template: parsedTemplate,
            response_path: responsePath.trim(),
            extra_headers: parsedHeaders,
            prompt: "Hello, this is a test.",
          }),
        }
      );
      setTestResult(result);
    } catch (e: any) {
      setTestResult({ success: false, error: e.message || "Connection test failed" });
    } finally {
      setTesting(false);
    }
  }

  async function handleSaveCodeAgent() {
    if (!currentProjectId) return;
    setOpencodeSaving(true);
    setCodeAgentMessage("");
    try {
      const patterns = filePatterns
        .split("\n")
        .map((p) => p.trim())
        .filter(Boolean);

      await updateProject(currentProjectId, {
        settings: {
          code_agent_repo_path: repoPath.trim() || null,
          code_agent_file_patterns: patterns.length > 0 ? patterns : null,
          code_agent_auto_analyze: autoAnalyze,
        },
      });
      await reloadProjects();
      setCodeAgentMessage("Code Agent settings saved");
    } catch (e: any) {
      setCodeAgentMessage(e.message || "Failed to save");
    } finally {
      setOpencodeSaving(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-4">Evaluations</h2>
        {currentProject && (
          <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
            Settings for project: <span className="font-medium text-gray-600 dark:text-slate-300">{currentProject.name}</span>
          </p>
        )}
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Target API Endpoint
            </label>
            <input
              type="text"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="http://localhost:3000/api/chat"
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              URL of the API to evaluate. Required for running evaluations.
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Request Body Template
            </label>
            <textarea
              value={requestTemplate}
              onChange={(e) => setRequestTemplate(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
              placeholder='{"messages": [{"role": "user", "content": "{prompt}"}]}'
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              JSON body template. Use <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">{"{prompt}"}</code> as a placeholder for the test case prompt.
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Response Answer Path
            </label>
            <input
              type="text"
              value={responsePath}
              onChange={(e) => setResponsePath(e.target.value)}
              placeholder="choices.0.message.content"
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Dot-notation path to extract the answer from the API response (e.g. <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">choices.0.message.content</code> or <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">answer</code>).
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Extra Headers
            </label>
            <textarea
              value={extraHeaders}
              onChange={(e) => setExtraHeaders(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
              placeholder='{"Authorization": "Bearer ..."}'
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Additional HTTP headers as JSON (e.g. Authorization).
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Max Conversation Turns
            </label>
            <input
              type="number"
              value={maxTurns}
              onChange={(e) => setMaxTurns(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
              min={1}
              max={10}
              className="w-24 px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Maximum follow-up turns for multi-turn test cases (1-10). Set to 1 to disable multi-turn.
              Use <code className="bg-gray-200 dark:bg-slate-700 px-1 rounded">{"{thread_id}"}</code> in your request template to enable conversation threading.
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
              onClick={handleTestConnection}
              disabled={testing || !endpoint.trim()}
              className="px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-300 rounded-lg text-sm hover:bg-gray-200 dark:hover:bg-slate-700 disabled:opacity-50"
            >
              {testing ? "Testing..." : "Test Connection"}
            </button>
          </div>

          {message && (
            <p className="text-sm text-gray-500 dark:text-slate-400">{message}</p>
          )}

          {testResult && (
            <div className={`p-3 rounded-lg text-sm ${
              testResult.success
                ? "bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
                : "bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300"
            }`}>
              {testResult.success ? (
                <div>
                  <p className="font-medium mb-1">Connection successful</p>
                  <p className="text-xs font-mono whitespace-pre-wrap">{testResult.response}</p>
                </div>
              ) : (
                <div>
                  <p className="font-medium mb-1">Connection failed</p>
                  <p className="text-xs">{testResult.error}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Code Agent Settings */}
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">Code Agent</h2>
        <p className="text-sm text-gray-400 dark:text-slate-500 mb-4">
          Configure repository access and automation for the Code Agent. LLM provider settings are on the AI Models tab.
        </p>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              Repository Path (optional)
            </label>
            <input
              type="text"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/your/project"
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Local path to your codebase. When set, the AI agent will explore your code and provide file-level suggestions with diffs.
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-500 dark:text-slate-400 mb-1">
              File Patterns
            </label>
            <textarea
              value={filePatterns}
              onChange={(e) => setFilePatterns(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-mono"
              placeholder={"**/*.py\n**/*.ts\n**/*.js"}
            />
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">
              Glob patterns (one per line) to hint which files the agent should explore first. The agent may look beyond these patterns.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="auto-analyze"
              checked={autoAnalyze}
              onChange={(e) => setAutoAnalyze(e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="auto-analyze" className="text-sm text-gray-600 dark:text-slate-300">
              Auto-analyze after evaluation runs
            </label>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveCodeAgent}
              disabled={codeAgentSaving}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
            >
              {codeAgentSaving ? "Saving..." : "Save"}
            </button>
          </div>

          {codeAgentMessage && (
            <p className="text-sm text-gray-500 dark:text-slate-400">{codeAgentMessage}</p>
          )}
        </div>
      </div>
    </div>
  );
}
