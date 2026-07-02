"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";

/** Build the copy-pasteable text for a caught error, including a server traceback when present. */
function copyText(error: unknown): string {
  if (error instanceof ApiError) return error.details;
  if (error instanceof Error) return error.stack || error.message;
  return String(error);
}

function displayMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/**
 * Inline error banner with a "Copy details" button. The copied payload includes the full
 * server-side traceback when the API provided one (debug builds), so a report can be pasted
 * straight into an issue or chat.
 */
export function ErrorNotice({ error, className = "" }: { error: unknown; className?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(copyText(error));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable — ignore
    }
  };

  const hasTrace = error instanceof ApiError && !!error.trace;

  return (
    <div
      className={`flex items-start justify-between gap-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm ${className}`}
    >
      <span className="min-w-0 break-words">{displayMessage(error)}</span>
      <button
        type="button"
        onClick={copy}
        title={hasTrace ? "Copy the full server traceback" : "Copy error details"}
        className="shrink-0 rounded-md border border-red-500/30 px-2 py-1 text-xs font-medium text-red-300 hover:bg-red-500/20"
      >
        {copied ? "Copied!" : hasTrace ? "Copy stack" : "Copy details"}
      </button>
    </div>
  );
}
