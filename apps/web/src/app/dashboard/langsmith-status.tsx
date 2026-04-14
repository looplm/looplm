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

type StatusState =
  | { state: "loading" }
  | { state: "ready"; data: LangsmithPing }
  | { state: "error"; message: string };

export default function LangsmithStatus() {
  const [status, setStatus] = useState<StatusState>({ state: "loading" });

  useEffect(() => {
    const url = buildApiUrl("/api/v1/langsmith/ping");
    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        return res.json() as Promise<LangsmithPing>;
      })
      .then((data) => setStatus({ state: "ready", data }))
      .catch((err) =>
        setStatus({ state: "error", message: err.message || "Request failed" })
      );
  }, []);

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold mb-2">LangSmith Status</h2>
      {status.state === "loading" && (
        <p className="text-sm text-gray-500 dark:text-slate-400">Checking connection…</p>
      )}
      {status.state === "error" && (
        <p className="text-sm text-red-300">Error: {status.message}</p>
      )}
      {status.state === "ready" && (
        <div className="text-sm text-gray-600 dark:text-slate-300 space-y-1">
          <div>Status: {status.data.status}</div>
          <div>Endpoint: {status.data.endpoint}</div>
          <div>Project: {status.data.project || "—"}</div>
          <div>Sessions found: {status.data.sessions_found}</div>
          <div>
            Project found:{" "}
            {status.data.project_found === null
              ? "—"
              : status.data.project_found
              ? "yes"
              : "no"}
          </div>
        </div>
      )}
    </div>
  );
}
