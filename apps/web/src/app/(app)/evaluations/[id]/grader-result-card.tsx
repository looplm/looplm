"use client";

import type { EvalGraderResult, EvaluatorItem } from "@/lib/api";
import { graderDisplayName } from "./eval-utils";
import { ClampedText, CopyButton, UrlDetails } from "./eval-components";

function ExternalLinkIcon({ className = "" }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`inline-block ${className}`}>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

export function getGraderCardCopyText(
  name: string,
  g: EvalGraderResult,
  evaluatorMap: Record<string, EvaluatorItem>,
) {
  const displayName = graderDisplayName(name, evaluatorMap);
  const status = g.skipped ? "SKIPPED" : g.pass ? "PASS" : "FAIL";
  let body = "";
  if (g.details && (g.details.found_urls || g.details.missing_urls || g.details.retrieved_urls)) {
    const found = (g.details.found_urls ?? []) as string[];
    const missing = (g.details.missing_urls ?? []) as string[];
    const retrieved = (g.details.retrieved_urls ?? []) as string[];
    if (found.length) body += `Found URLs:\n${found.join("\n")}\n`;
    if (missing.length) body += `Missing URLs:\n${missing.join("\n")}\n`;
    if (retrieved.length) body += `Retrieved URLs:\n${retrieved.join("\n")}`;
  } else if (g.reason) {
    body = g.reason;
  }
  return `${displayName}: ${status}\n${body}`.trim();
}

export function GraderResultCard({
  name,
  grader: g,
  evaluatorMap,
  disabledGraders,
  datasetId,
  testId,
  canEdit,
}: {
  name: string;
  grader: EvalGraderResult;
  evaluatorMap: Record<string, EvaluatorItem>;
  disabledGraders: Set<string>;
  datasetId?: string;
  testId?: string;
  canEdit?: boolean;
}) {
  const meta = evaluatorMap[name];
  const isCriticalFail = !g.pass && !g.skipped && meta?.affects_pass;
  return (
    <div
      className={`p-3 rounded-lg border group/card relative ${
        disabledGraders.has(name)
          ? "border-gray-200 dark:border-slate-700 opacity-50"
          : isCriticalFail
          ? "border-red-400 dark:border-red-600 border-l-4"
          : g.skipped
          ? "border-gray-200 dark:border-slate-700"
          : g.pass
          ? "border-green-200 dark:border-green-800"
          : "border-red-200 dark:border-red-800"
      }`}
    >
      <div className="flex items-center justify-between mb-1">
        <a
          href={`/evaluators?highlight=${encodeURIComponent(name)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium hover:text-indigo-500 dark:hover:text-indigo-400 transition-colors flex items-center gap-1 group/link"
          onClick={(e) => e.stopPropagation()}
        >
          {graderDisplayName(name, evaluatorMap)}
          <ExternalLinkIcon className="opacity-0 group-hover/link:opacity-100 transition-opacity" />
        </a>
        <div className="flex items-center gap-2">
          <CopyButton
            getText={() => getGraderCardCopyText(name, g, evaluatorMap)}
            className="opacity-0 group-hover/card:opacity-100"
          />
          {g.skipped ? (
            <span className="text-gray-400 dark:text-slate-500">SKIPPED</span>
          ) : g.pass ? (
            <span className="text-green-600 dark:text-green-400">PASS</span>
          ) : (
            <span className="text-red-600 dark:text-red-400">FAIL</span>
          )}
        </div>
      </div>
      {g.details && (g.details.found_urls || g.details.missing_urls || g.details.retrieved_urls) ? (
        <UrlDetails
          found={(g.details.found_urls ?? []) as string[]}
          missing={(g.details.missing_urls ?? []) as string[]}
          retrieved={(g.details.retrieved_urls ?? []) as string[]}
          datasetId={datasetId}
          testId={testId}
          canEdit={canEdit}
        />
      ) : (
        g.reason ? <ClampedText text={g.reason} /> : null
      )}
    </div>
  );
}
