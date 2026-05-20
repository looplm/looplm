"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  completeGithubCallback,
  listInstallationRepos,
  selectProjectGithubInstallation,
  type GithubInstallationSummary,
  type GithubRepo,
} from "@/lib/api";

type Phase = "exchanging" | "pick-installation" | "pick-repo" | "saving" | "done" | "error";

export default function GithubCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const code = params.get("code");
  const state = params.get("state");

  const [phase, setPhase] = useState<Phase>("exchanging");
  const [error, setError] = useState("");
  const [installations, setInstallations] = useState<GithubInstallationSummary[]>([]);
  const [selectedInstallation, setSelectedInstallation] = useState<GithubInstallationSummary | null>(null);
  const [repos, setRepos] = useState<GithubRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!code || !state) {
        setPhase("error");
        setError("Missing code or state in callback URL.");
        return;
      }
      try {
        const data = await completeGithubCallback(code, state);
        if (cancelled) return;
        setInstallations(data.installations);
        if (data.installations.length === 0) {
          setPhase("error");
          setError(
            "No GitHub App installations found. Install the App on an organisation or your account first, then connect again.",
          );
          return;
        }
        if (data.installations.length === 1) {
          handlePickInstallation(data.installations[0]);
        } else {
          setPhase("pick-installation");
        }
      } catch (e: unknown) {
        if (cancelled) return;
        setPhase("error");
        setError(e instanceof Error ? e.message : "GitHub callback failed.");
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [code, state]);

  async function handlePickInstallation(inst: GithubInstallationSummary) {
    setSelectedInstallation(inst);
    setPhase("pick-repo");
    setReposLoading(true);
    try {
      const list = await listInstallationRepos(inst.installation_id);
      setRepos(list);
    } catch (e: unknown) {
      setPhase("error");
      setError(e instanceof Error ? e.message : "Failed to load repos.");
    } finally {
      setReposLoading(false);
    }
  }

  async function handlePickRepo(repo: GithubRepo) {
    if (!selectedInstallation) return;
    setPhase("saving");
    try {
      await selectProjectGithubInstallation({
        installation_id: selectedInstallation.installation_id,
        account_login: selectedInstallation.account_login,
        account_type: selectedInstallation.account_type,
        repo_full_name: repo.full_name,
        repo_default_branch: repo.default_branch,
      });
      setPhase("done");
      // Hand control back to Settings so the user lands where they came from.
      setTimeout(() => router.replace("/settings"), 800);
    } catch (e: unknown) {
      setPhase("error");
      setError(e instanceof Error ? e.message : "Failed to save selection.");
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <h1 className="text-xl font-semibold mb-1">Connect a GitHub repository</h1>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-6">
        Link a repo so the Code Agent can analyse your source.
      </p>

      {phase === "exchanging" && <p className="text-sm">Finishing GitHub authorization…</p>}

      {phase === "pick-installation" && (
        <div className="space-y-2">
          <p className="text-sm text-gray-500 dark:text-slate-400">
            Choose where the GitHub App is installed:
          </p>
          {installations.map((inst) => (
            <button
              key={inst.installation_id}
              onClick={() => handlePickInstallation(inst)}
              className="w-full text-left p-3 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 hover:border-indigo-500 transition-colors"
            >
              <div className="font-medium">{inst.account_login}</div>
              <div className="text-xs text-gray-400">{inst.account_type}</div>
            </button>
          ))}
        </div>
      )}

      {phase === "pick-repo" && selectedInstallation && (
        <div className="space-y-2">
          <p className="text-sm text-gray-500 dark:text-slate-400">
            Pick a repo from{" "}
            <span className="font-medium text-gray-700 dark:text-slate-300">
              {selectedInstallation.account_login}
            </span>
            :
          </p>
          {reposLoading && <p className="text-sm">Loading repos…</p>}
          {!reposLoading && repos.length === 0 && (
            <p className="text-sm text-gray-400">
              No repos available. Adjust the App&apos;s repo access on GitHub.
            </p>
          )}
          <div className="max-h-96 overflow-y-auto space-y-1">
            {repos.map((r) => (
              <button
                key={r.full_name}
                onClick={() => handlePickRepo(r)}
                className="w-full text-left px-3 py-2 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 text-sm font-mono"
              >
                {r.full_name}
                <span className="text-gray-400 dark:text-slate-500 ml-2">
                  · {r.default_branch}
                  {r.private && " · private"}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {phase === "saving" && <p className="text-sm">Saving…</p>}
      {phase === "done" && (
        <p className="text-sm text-green-600 dark:text-green-400">
          Connected. Redirecting back to Settings…
        </p>
      )}
      {phase === "error" && (
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-900">
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
          <button
            onClick={() => router.push("/settings")}
            className="mt-3 px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-md"
          >
            Back to Settings
          </button>
        </div>
      )}
    </div>
  );
}
