"use client";

import { useEffect, useState } from "react";
import { getVersion, type VersionInfo } from "@/lib/api";

const WEB_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "unknown";

export default function AboutSettings() {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getVersion()
      .then(setInfo)
      .catch(() => setError("Could not load API version"));
  }, []);

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <h2 className="text-lg font-semibold mb-4">About</h2>

      <dl className="grid grid-cols-1 sm:grid-cols-[160px_1fr] gap-x-6 gap-y-3 text-sm">
        <dt className="text-gray-500 dark:text-slate-400">Web</dt>
        <dd className="font-mono">v{WEB_VERSION}</dd>

        <dt className="text-gray-500 dark:text-slate-400">API</dt>
        <dd className="font-mono">
          {info ? `v${info.api}` : error ? <span className="text-red-500">{error}</span> : "…"}
        </dd>

        <dt className="text-gray-500 dark:text-slate-400">Connectors</dt>
        <dd className="font-mono">{info?.connectors ? `v${info.connectors}` : "—"}</dd>

        <dt className="text-gray-500 dark:text-slate-400">Commit</dt>
        <dd className="font-mono">
          {info?.commit ? info.commit.slice(0, 12) : "—"}
        </dd>
      </dl>

      <p className="mt-6 text-xs text-gray-500 dark:text-slate-400">
        LoopLM is open source —{" "}
        <a
          href="https://github.com/looplm/looplm"
          target="_blank"
          rel="noreferrer"
          className="text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          github.com/looplm/looplm
        </a>
      </p>
    </div>
  );
}
