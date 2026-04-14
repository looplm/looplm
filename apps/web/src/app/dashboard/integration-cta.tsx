"use client";

import { useEffect, useState } from "react";
import { buildApiUrl } from "./api";

type LangsmithPing = {
  status: "ok";
  endpoint: string;
  project: string | null;
  sessions_found: number;
  project_found: boolean | null;
};

type ConnectionState =
  | { state: "loading" }
  | { state: "ready"; data: LangsmithPing }
  | { state: "error" };

export default function IntegrationCta() {
  const [connection, setConnection] = useState<ConnectionState>({
    state: "loading",
  });

  useEffect(() => {
    const url = buildApiUrl("/api/v1/langsmith/ping");
    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error("bad status");
        }
        return res.json() as Promise<LangsmithPing>;
      })
      .then((data) => setConnection({ state: "ready", data }))
      .catch(() => setConnection({ state: "error" }));
  }, []);

  if (connection.state === "loading") {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center">
        <p className="text-gray-500 dark:text-slate-400">Checking data source connection…</p>
      </div>
    );
  }

  if (connection.state === "ready") {
    const hasSessions = connection.data.sessions_found > 0;

    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center">
        <p className="text-gray-700 dark:text-slate-200">LangSmith connected.</p>
        <p className="text-gray-500 dark:text-slate-400 mt-2 text-sm">
          {hasSessions
            ? "We're pulling your latest runs for analysis."
            : "No sessions yet. Send a trace to LangSmith to start analysis."}
        </p>
        <button className="mt-6 px-4 py-2 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg text-sm font-medium transition-colors">
          Add another integration
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center">
      <p className="text-gray-500 dark:text-slate-400 mb-4">
        Connect your first data source to start analyzing traces.
      </p>
      <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white transition-colors">
        + Add Integration
      </button>
    </div>
  );
}
