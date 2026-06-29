"use client";

import type { PromptExtractionStatus } from "@/lib/api";
import { fmtDuration } from "@/app/(app)/prompts/constants";

interface GithubExtractionStatusProps {
  extraction: PromptExtractionStatus | null;
  githubRepo: string | null;
  inProgress: boolean;
  now: number;
}

export function GithubExtractionStatus({
  extraction,
  githubRepo,
  inProgress,
  now,
}: GithubExtractionStatusProps) {
  return (
    <>
      {inProgress && (() => {
        const log = extraction?.progress_log ?? [];
        const startTs = extraction?.started_at
          ? Date.parse(extraction.started_at)
          : (log[0] ? Date.parse(log[0].t) : now);
        const visible = log.slice(-6);
        const base = log.length - visible.length;
        return (
          <div className="mb-4 p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-lg text-sm">
            <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-300 font-medium">
              <span className="inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
              <span className="flex-1">
                Extracting prompts from {githubRepo}
                {extraction?.progress_message ? ` — ${extraction.progress_message}` : "…"}
              </span>
              <span className="tabular-nums text-xs text-indigo-500/80 dark:text-indigo-400/80">
                {fmtDuration(now - startTs)}
              </span>
            </div>
            {visible.length > 0 && (
              <ul className="mt-2 ml-5 space-y-0.5 font-mono text-[11px] text-gray-500 dark:text-slate-400">
                {visible.map((entry, i) => {
                  const fi = base + i;
                  const isLast = fi === log.length - 1;
                  const endTs = isLast ? now : Date.parse(log[fi + 1].t);
                  return (
                    <li
                      key={`${entry.t}-${fi}`}
                      className={`flex items-baseline gap-2 ${isLast ? "text-indigo-600 dark:text-indigo-300" : ""}`}
                    >
                      <span className="flex-1 truncate">
                        <span className="text-gray-400 dark:text-slate-600">›</span> {entry.msg}
                      </span>
                      <span className="tabular-nums text-gray-400 dark:text-slate-600 shrink-0">
                        {fmtDuration(endTs - Date.parse(entry.t))}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })()}
      {extraction?.status === "completed" && (
        <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-600 dark:text-emerald-300 text-sm">
          Extracted {extraction.extracted_count} prompt{extraction.extracted_count !== 1 ? "s" : ""} from {githubRepo}
          {extraction.started_at && extraction.completed_at
            ? ` in ${fmtDuration(Date.parse(extraction.completed_at) - Date.parse(extraction.started_at))}`
            : ""}
          .
        </div>
      )}
    </>
  );
}
