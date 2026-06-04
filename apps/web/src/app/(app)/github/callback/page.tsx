"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  completeGithubCallback,
  listInstallationRepos,
  listRepoBranches,
  selectProjectGithubInstallation,
  type GithubInstallationSummary,
  type GithubRepo,
} from "@/lib/api";

type Phase =
  | "exchanging"
  | "pick-installation"
  | "pick-repo"
  | "pick-branch"
  | "saving"
  | "done"
  | "error";

// OAuth `code` is single-use. React StrictMode runs effects twice in dev, which
// would submit the same code to GitHub twice — the second submission always
// fails with bad_verification_code. Cache the in-flight Promise at module scope
// so both mounts await the same network call.
const inflight = new Map<string, ReturnType<typeof completeGithubCallback>>();

function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function RepoIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden>
      <path
        fill="currentColor"
        d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 0 1-1.072 1.05A2.5 2.5 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.49 2.49 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.25.25 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"
      />
    </svg>
  );
}

function BranchIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden>
      <path
        fill="currentColor"
        d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.49 2.49 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"
      />
    </svg>
  );
}

function LockIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden>
      <path
        fill="currentColor"
        d="M4 4a4 4 0 0 1 8 0v2h.25c.97 0 1.75.78 1.75 1.75v5.5c0 .97-.78 1.75-1.75 1.75H3.75A1.75 1.75 0 0 1 2 13.25v-5.5C2 6.78 2.78 6 3.75 6H4Zm6.5 2V4a2.5 2.5 0 0 0-5 0v2Z"
      />
    </svg>
  );
}

function ChevronRight({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden>
      <path
        fill="currentColor"
        d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06L7.28 11.78a.75.75 0 1 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
      />
    </svg>
  );
}

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
  const [filter, setFilter] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<GithubRepo | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchFilter, setBranchFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!code || !state) {
        setPhase("error");
        setError("Missing code or state in callback URL.");
        return;
      }
      let promise = inflight.get(code);
      if (!promise) {
        promise = completeGithubCallback(code, state);
        inflight.set(code, promise);
      }
      try {
        const data = await promise;
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
    setFilter("");
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
    setSelectedRepo(repo);
    setPhase("pick-branch");
    setBranchesLoading(true);
    setBranchFilter("");
    setBranches([]);
    try {
      const list = await listRepoBranches(selectedInstallation.installation_id, repo.full_name);
      setBranches(list);
    } catch (e: unknown) {
      setPhase("error");
      setError(e instanceof Error ? e.message : "Failed to load branches.");
    } finally {
      setBranchesLoading(false);
    }
  }

  async function handlePickBranch(branch: string) {
    if (!selectedInstallation || !selectedRepo) return;
    setPhase("saving");
    try {
      await selectProjectGithubInstallation({
        installation_id: selectedInstallation.installation_id,
        account_login: selectedInstallation.account_login,
        account_type: selectedInstallation.account_type,
        repo_full_name: selectedRepo.full_name,
        repo_default_branch: selectedRepo.default_branch,
        repo_branch: branch,
      });
      setPhase("done");
      // Hand control back to Settings so the user lands where they came from.
      setTimeout(() => router.replace("/settings"), 800);
    } catch (e: unknown) {
      setPhase("error");
      setError(e instanceof Error ? e.message : "Failed to save selection.");
    }
  }

  const filteredRepos = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter((r) => r.full_name.toLowerCase().includes(q));
  }, [repos, filter]);

  const filteredBranches = useMemo(() => {
    const q = branchFilter.trim().toLowerCase();
    if (!q) return branches;
    return branches.filter((b) => b.toLowerCase().includes(q));
  }, [branches, branchFilter]);

  return (
    <div className="max-w-2xl mx-auto p-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold mb-1">Connect a GitHub repository</h1>
        <p className="text-sm text-gray-500 dark:text-slate-400">
          Link a repo so the Code Agent can analyse your source.
        </p>
      </div>

      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        {phase === "exchanging" && (
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-slate-400">
            <Spinner className="w-4 h-4" />
            Finishing GitHub authorization…
          </div>
        )}

        {phase === "pick-installation" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-500 dark:text-slate-400">
              Choose where the GitHub App is installed:
            </p>
            <ul className="space-y-2">
              {installations.map((inst) => (
                <li key={inst.installation_id}>
                  <button
                    onClick={() => handlePickInstallation(inst)}
                    className="w-full flex items-center justify-between text-left p-3 rounded-lg border border-gray-100 dark:border-slate-800 hover:border-indigo-500 hover:bg-indigo-50/40 dark:hover:bg-indigo-950/30 transition-colors"
                  >
                    <div>
                      <div className="font-medium">{inst.account_login}</div>
                      <div className="text-xs text-gray-400 capitalize">{inst.account_type}</div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {phase === "pick-repo" && selectedInstallation && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-gray-500 dark:text-slate-400">
                Pick a repo from{" "}
                <span className="font-medium text-gray-700 dark:text-slate-300">
                  {selectedInstallation.account_login}
                </span>
              </p>
              {installations.length > 1 && (
                <button
                  onClick={() => {
                    setSelectedInstallation(null);
                    setRepos([]);
                    setFilter("");
                    setPhase("pick-installation");
                  }}
                  className="text-xs text-indigo-500 hover:underline shrink-0"
                >
                  Switch account
                </button>
              )}
            </div>

            {reposLoading && (
              <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-slate-400">
                <Spinner className="w-4 h-4" />
                Loading repos…
              </div>
            )}

            {!reposLoading && repos.length === 0 && (
              <div className="p-6 text-center text-sm text-gray-400 dark:text-slate-500 border border-dashed border-gray-200 dark:border-slate-800 rounded-lg">
                No repos available. Adjust the App&apos;s repo access on GitHub.
              </div>
            )}

            {!reposLoading && repos.length > 0 && (
              <>
                {repos.length > 5 && (
                  <input
                    type="text"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter repos…"
                    className="w-full px-3 py-2 text-sm rounded-md bg-gray-50 dark:bg-slate-800/60 border border-gray-100 dark:border-slate-800 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
                  />
                )}

                <div className="max-h-96 overflow-y-auto -mx-1 px-1">
                  {filteredRepos.length === 0 ? (
                    <p className="text-sm text-gray-400 dark:text-slate-500 py-6 text-center">
                      No repos match &ldquo;{filter}&rdquo;.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {filteredRepos.map((r) => (
                        <li key={r.full_name}>
                          <button
                            onClick={() => handlePickRepo(r)}
                            className="group w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
                          >
                            <RepoIcon className="w-4 h-4 text-gray-400 group-hover:text-indigo-500 shrink-0" />
                            <span className="font-mono text-sm truncate flex-1">{r.full_name}</span>
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono text-gray-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 shrink-0">
                              <BranchIcon className="w-3 h-3" />
                              {r.default_branch}
                            </span>
                            {r.private && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 shrink-0">
                                <LockIcon className="w-3 h-3" />
                                private
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {phase === "pick-branch" && selectedRepo && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-gray-500 dark:text-slate-400">
                Pick the branch to sync from{" "}
                <span className="font-mono text-gray-700 dark:text-slate-300">
                  {selectedRepo.full_name}
                </span>
              </p>
              <button
                onClick={() => {
                  setSelectedRepo(null);
                  setBranches([]);
                  setBranchFilter("");
                  setPhase("pick-repo");
                }}
                className="text-xs text-indigo-500 hover:underline shrink-0"
              >
                Switch repo
              </button>
            </div>

            {branchesLoading && (
              <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-slate-400">
                <Spinner className="w-4 h-4" />
                Loading branches…
              </div>
            )}

            {!branchesLoading && branches.length === 0 && (
              <div className="p-6 text-center text-sm text-gray-400 dark:text-slate-500 border border-dashed border-gray-200 dark:border-slate-800 rounded-lg">
                No branches found for this repo.
              </div>
            )}

            {!branchesLoading && branches.length > 0 && (
              <>
                {branches.length > 5 && (
                  <input
                    type="text"
                    value={branchFilter}
                    onChange={(e) => setBranchFilter(e.target.value)}
                    placeholder="Filter branches…"
                    className="w-full px-3 py-2 text-sm rounded-md bg-gray-50 dark:bg-slate-800/60 border border-gray-100 dark:border-slate-800 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
                  />
                )}

                <div className="max-h-96 overflow-y-auto -mx-1 px-1">
                  {filteredBranches.length === 0 ? (
                    <p className="text-sm text-gray-400 dark:text-slate-500 py-6 text-center">
                      No branches match &ldquo;{branchFilter}&rdquo;.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {filteredBranches.map((b) => (
                        <li key={b}>
                          <button
                            onClick={() => handlePickBranch(b)}
                            className="group w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
                          >
                            <BranchIcon className="w-4 h-4 text-gray-400 group-hover:text-indigo-500 shrink-0" />
                            <span className="font-mono text-sm truncate flex-1">{b}</span>
                            {b === selectedRepo.default_branch && (
                              <span className="px-2 py-0.5 rounded text-xs text-gray-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 shrink-0">
                                default
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {phase === "saving" && (
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-slate-400">
            <Spinner className="w-4 h-4" />
            Saving…
          </div>
        )}

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

      {phase !== "error" && phase !== "done" && (
        <div className="mt-4 text-center">
          <button
            onClick={() => router.push("/settings")}
            className="text-xs text-gray-500 dark:text-slate-500 hover:text-gray-700 dark:hover:text-slate-300"
          >
            Cancel and go back to Settings
          </button>
        </div>
      )}
    </div>
  );
}
