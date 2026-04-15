"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { getEvalJobs, type EvalJob } from "@/lib/api";
import { JobStatusBadge, JobProgressBar, formatDuration } from "@/components/eval-shared";

type StatusFilter = "all" | "running" | "completed" | "failed" | "cancelled";

export default function EvalJobsPage() {
  const [jobs, setJobs] = useState<EvalJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");

  const loadJobs = useCallback(async () => {
    try {
      const data = await getEvalJobs();
      setJobs(data.data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Poll while active jobs exist
  useEffect(() => {
    const hasActive = jobs.some((j) => j.status === "pending" || j.status === "running" || j.status === "batch_pending");
    if (!hasActive) return;
    // Batch jobs are long-running — poll less frequently
    const hasRealtime = jobs.some((j) => j.status === "pending" || j.status === "running");
    const interval = setInterval(loadJobs, hasRealtime ? 3000 : 30000);
    return () => clearInterval(interval);
  }, [jobs, loadJobs]);

  const filtered = filter === "all"
    ? jobs
    : filter === "running"
      ? jobs.filter((j) => j.status === "running" || j.status === "pending" || j.status === "batch_pending")
      : jobs.filter((j) => j.status === filter);

  const counts = {
    all: jobs.length,
    running: jobs.filter((j) => j.status === "running" || j.status === "pending" || j.status === "batch_pending").length,
    completed: jobs.filter((j) => j.status === "completed").length,
    failed: jobs.filter((j) => j.status === "failed").length,
    cancelled: jobs.filter((j) => j.status === "cancelled").length,
  };

  if (loading) {
    return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
        No eval jobs yet. Click &quot;Run Eval&quot; to start one.
      </div>
    );
  }

  return (
    <div>
      {/* Status filter tabs */}
      <div className="flex gap-2 mb-4">
        {(["all", "running", "completed", "failed", "cancelled"] as StatusFilter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === f
                ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
                : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
            }`}
          >
            {f === "running" ? "Running" : f.charAt(0).toUpperCase() + f.slice(1)} ({counts[f]})
          </button>
        ))}
      </div>

      {/* Job cards */}
      <div className="space-y-3">
        {filtered.map((job) => (
          <Link
            key={job.id}
            href={`/evaluations/jobs/${job.id}`}
            className="block rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4 hover:border-indigo-300 dark:hover:border-indigo-700 transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm">{job.test_suite}</span>
                  <JobStatusBadge status={job.status} />
                  {(job.status === "running" || job.status === "pending" || job.status === "batch_pending") && (
                    <span className={`inline-block w-2 h-2 rounded-full animate-pulse ${job.status === "batch_pending" ? "bg-amber-500" : "bg-blue-500"}`} />
                  )}
                </div>
                <p className="text-xs text-gray-400 dark:text-slate-500">
                  Started {new Date(job.started_at).toLocaleString("de-DE", {
                    day: "2-digit",
                    month: "2-digit",
                    year: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>

              <div className="flex items-center gap-4 shrink-0">
                {(job.status === "running" || job.status === "pending" || job.status === "batch_pending") && (
                  <JobProgressBar job={job} />
                )}
                <span className="text-xs text-gray-500 dark:text-slate-400 whitespace-nowrap">
                  {formatDuration(job.started_at, job.completed_at)}
                  {(job.status === "running" || job.status === "pending" || job.status === "batch_pending") && (
                    <span className={`ml-0.5 ${job.status === "batch_pending" ? "text-amber-500" : "text-blue-500"}`}>...</span>
                  )}
                </span>
              </div>
            </div>

            {/* Failed: truncated error */}
            {job.status === "failed" && job.error && (
              <p className="mt-2 text-xs text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-900/10 rounded px-2 py-1 truncate">
                {job.error}
              </p>
            )}

            {/* Cancelled */}
            {job.status === "cancelled" && (
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/10 rounded px-2 py-1">
                Cancelled by user
              </p>
            )}

            {/* Completed with results */}
            {job.status === "completed" && job.run_id && (
              <div className="mt-2">
                <span className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                  View Results &rarr;
                </span>
              </div>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
