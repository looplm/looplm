"use client";

/**
 * Expandable list of flagged example chunks (id, issue label, text snippet),
 * shared by the extended family cards.
 */

import { useState } from "react";

import { Chevron } from "./shared";

export interface FlaggedChunk {
  id: string;
  label: string;
  snippet: string;
}

export function FlaggedChunks({ items }: { items: FlaggedChunk[] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium text-gray-500 dark:text-slate-400"
        aria-expanded={open}
      >
        <Chevron open={open} />
        Flagged chunks ({items.length})
      </button>
      {open && (
        <ul className="mt-2 space-y-2">
          {items.map((c, i) => (
            <li key={`${c.id}-${i}`} className="text-xs rounded-lg bg-gray-50 dark:bg-slate-800/50 p-2">
              <p className="flex items-center gap-2 mb-1">
                <span className="px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  {c.label}
                </span>
                <span className="truncate font-mono text-gray-400 dark:text-slate-500">{c.id}</span>
              </p>
              <p className="text-gray-600 dark:text-slate-300 line-clamp-2">{c.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
