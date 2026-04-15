"use client";

import Link from "next/link";
import type { FeedbackScoreItem } from "@/lib/api";
import { extractUserQuestion } from "./feedback-utils";

const VERDICT_BADGE_COLORS = [
  "bg-red-100 text-red-700 dark:bg-red-900/20 dark:text-red-400",
  "bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400",
  "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  "bg-blue-100 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400",
  "bg-amber-100 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400",
];

function getBadgeColorClass(verdict: string, configuredVerdicts: string[]) {
  const idx = configuredVerdicts.indexOf(verdict);
  return VERDICT_BADGE_COLORS[idx >= 0 ? idx % VERDICT_BADGE_COLORS.length : 2];
}

interface FeedbackTableRowProps {
  item: FeedbackScoreItem;
  tab: string;
  configuredVerdicts: string[];
  onSelect: (item: FeedbackScoreItem) => void;
}

export function FeedbackTableRow({ item, tab, configuredVerdicts, onSelect }: FeedbackTableRowProps) {
  return (
    <tr
      onClick={() => onSelect(item)}
      className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30 cursor-pointer"
    >
      <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap text-xs">
        {item.scored_at
          ? new Date(item.scored_at).toLocaleString("de-DE", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })
          : "\u2014"}
      </td>
      {tab === "graders" && (
        <td className="px-4 py-3 text-xs text-gray-600 dark:text-slate-300">
          {item.score_name.replace("grader_", "").replace(/_/g, " ")}
        </td>
      )}
      <td
        className="px-4 py-3 text-gray-700 dark:text-slate-200 max-w-md text-xs whitespace-normal line-clamp-3"
        title={extractUserQuestion(item.trace_input)}
      >
        {extractUserQuestion(item.trace_input)}
      </td>
      <td className="px-4 py-3 text-center">
        {item.value === 1 ? (
          <span className="text-green-500 text-lg" title="Positive / Passed">
            {tab === "feedback" ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 inline-block">
                <path d="M7.493 18.75c-.425 0-.82-.236-.975-.632A7.48 7.48 0 0 1 6 15.375c0-1.75.599-3.358 1.602-4.634.151-.192.373-.309.6-.397.473-.183.89-.514 1.212-.924a9.042 9.042 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V3.75A.75.75 0 0 1 15 3a2.25 2.25 0 0 1 2.25 2.25c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48a4.53 4.53 0 0 1-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.45-.243ZM5.25 15.375a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z" />
              </svg>
            ) : "\u2713"}
          </span>
        ) : (
          <span className="text-red-500 text-lg" title="Negative / Failed">
            {tab === "feedback" ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 inline-block">
                <path d="M15.73 5.25h1.035A7.984 7.984 0 0 1 18 9.375c0 1.886-.65 3.636-1.74 5.01-.163.206-.396.328-.636.42a1.985 1.985 0 0 1-1.178.881 9.042 9.042 0 0 1-2.861 2.4c-.723.384-1.35.956-1.653 1.715a4.498 4.498 0 0 0-.322 1.672v.633a.75.75 0 0 1-.75.75 2.25 2.25 0 0 1-2.25-2.25c0-1.152.26-2.243.723-3.218.266-.558-.107-1.282-.725-1.282H3.622c-1.026 0-1.945-.694-2.054-1.715A12.134 12.134 0 0 1 1.5 12.75c0-2.772.943-5.33 2.523-7.36.388-.5 1.003-.765 1.638-.765h3.659c.497 0 .987.08 1.45.243l3.114 1.04c.462.154.95.233 1.446.242ZM18.75 8.625a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0Z" />
              </svg>
            ) : "\u2717"}
          </span>
        )}
      </td>
      <td
        className="px-4 py-3 text-gray-500 dark:text-slate-400 max-w-xs text-xs whitespace-normal line-clamp-3"
        title={item.comment || undefined}
      >
        {item.comment || "\u2014"}
      </td>
      {tab === "feedback" && (
        <td className="px-4 py-3">
          {item.eval_verdict ? (
            <span
              className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getBadgeColorClass(item.eval_verdict, configuredVerdicts)}`}
              title={item.eval_reasoning || undefined}
            >
              {item.eval_verdict}
            </span>
          ) : (
            <span className="text-gray-300 dark:text-slate-600 text-xs">{"\u2014"}</span>
          )}
        </td>
      )}
      {tab === "feedback" && (
        <td className="px-4 py-3 text-center text-xs text-gray-500 dark:text-slate-400">
          {item.eval_confidence != null
            ? `${Math.round(item.eval_confidence * 100)}%`
            : "\u2014"}
        </td>
      )}
      <td className="px-4 py-3">
        {item.trace_id ? (
          <Link
            href={`/traces/${item.trace_id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-indigo-600 dark:text-indigo-400 hover:underline text-xs"
          >
            View →
          </Link>
        ) : (
          <span className="text-gray-300 dark:text-slate-600 text-xs">{"\u2014"}</span>
        )}
      </td>
    </tr>
  );
}
