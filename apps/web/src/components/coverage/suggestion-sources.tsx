"use client";

import type { CoverageSuggestionSource } from "@/lib/api";

/** Readable label for a source: its indexed title, else the URL's last path segment. */
function labelFor(source: CoverageSuggestionSource): string {
  if (source.title) return source.title;
  if (source.url) {
    try {
      const url = new URL(source.url);
      const last = url.pathname.split("/").filter(Boolean).pop();
      return decodeURIComponent(last || url.hostname);
    } catch {
      return source.url;
    }
  }
  return source.doc_id || "Untitled document";
}

/**
 * The indexed documents a suggested question was drafted from, as links so the
 * reviewer can open the page and check the drafted criteria against it.
 */
export function SuggestionSources({
  sources,
  label = "Drafted from",
}: {
  sources: CoverageSuggestionSource[] | undefined;
  label?: string;
}) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-2">
      {label && (
        <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">
          {label}
        </span>
      )}
      <ul className="mt-1 space-y-0.5">
        {sources.map((source, i) => {
          const text = labelFor(source);
          return (
            <li key={`${source.url || source.doc_id || text}-${i}`} className="text-xs leading-snug">
              {source.url ? (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={source.url}
                  className="text-indigo-600 dark:text-indigo-400 hover:underline break-all"
                >
                  {text}
                </a>
              ) : (
                <span className="text-gray-500 dark:text-slate-400 break-all" title="No URL indexed for this document">
                  {text}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
