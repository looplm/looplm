"use client";

import { useEffect, useState } from "react";
import { buildApiUrl } from "./api";

type StatusState =
  | { state: "loading" }
  | { state: "ready"; connected: boolean }
  | { state: "error" };

export default function StatsCards() {
  const [status, setStatus] = useState<StatusState>({ state: "loading" });

  useEffect(() => {
    const url = buildApiUrl("/api/v1/langsmith/ping");
    fetch(url)
      .then((res) => {
        if (!res.ok) {
          throw new Error("bad status");
        }
        return res.json();
      })
      .then(() => setStatus({ state: "ready", connected: true }))
      .catch(() => setStatus({ state: "error" }));
  }, []);

  const connected = status.state === "ready" && status.connected;
  const subText = connected ? "LangSmith connected" : "No data sources connected";
  const subTextMid = connected ? "LangSmith connected" : "Connect a data source to begin";
  const subTextEnd = connected ? "LangSmith connected" : "Analysis pending";

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-12">
      {[
        { label: "Traces Analyzed", value: "—", sub: subText },
        { label: "Failures Detected", value: "—", sub: subTextMid },
        { label: "Fixes Suggested", value: "—", sub: subTextEnd },
      ].map((stat) => (
        <div
          key={stat.label}
          className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800"
        >
          <p className="text-sm text-gray-500 dark:text-slate-400 mb-1">{stat.label}</p>
          <p className="text-3xl font-bold">{stat.value}</p>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{stat.sub}</p>
        </div>
      ))}
    </div>
  );
}
