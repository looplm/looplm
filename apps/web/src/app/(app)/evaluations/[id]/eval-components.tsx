"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { splitSegments, sentenceFoundIn } from "./eval-utils";

/** Copy text to clipboard and show a toast */
function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success("Copied to clipboard"),
    () => toast.error("Failed to copy"),
  );
}

/** Small copy icon button */
export function CopyButton({ getText, className = "" }: { getText: () => string; className?: string }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); copyToClipboard(getText()); }}
      className={`text-gray-300 hover:text-gray-500 dark:text-slate-600 dark:hover:text-slate-300 transition-colors ${className}`}
      title="Copy to clipboard"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
    </button>
  );
}

/** Render expected output with missing sentences highlighted */
export function ExpectedOutputDiff({
  expected,
  actual,
}: {
  expected: string;
  actual: string;
}) {
  const segments = splitSegments(expected);
  if (segments.length === 0) return <span>{expected}</span>;

  return (
    <>
      {segments.map((seg, i) => {
        const missing = !sentenceFoundIn(seg.text, actual);
        return (
          <Fragment key={i}>
            {seg.blockBreak && <br />}
            {i > 0 && !seg.blockBreak && " "}
            {missing ? (
              <mark className="bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300 rounded px-0.5">
                {seg.text}
              </mark>
            ) : (
              <span>{seg.text}</span>
            )}
          </Fragment>
        );
      })}
    </>
  );
}

/** Text that clamps to N lines with a "Show more" toggle */
export function ClampedText({ text, lines = 3 }: { text: string; lines?: number }) {
  const [clamped, setClamped] = useState(true);
  const [needsClamp, setNeedsClamp] = useState(false);
  const ref = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) setNeedsClamp(el.scrollHeight > el.clientHeight + 2);
  }, [text]);

  return (
    <div>
      <p
        ref={ref}
        className={`text-gray-500 dark:text-slate-400 ${clamped ? "line-clamp-3" : ""}`}
        style={clamped ? { WebkitLineClamp: lines } : undefined}
      >
        {text}
      </p>
      {needsClamp && (
        <button
          onClick={(e) => { e.stopPropagation(); setClamped(!clamped); }}
          className="text-sm text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 mt-1"
        >
          {clamped ? "Show more" : "Show less"}
        </button>
      )}
    </div>
  );
}

/** Collapsible section with a toggle header */
export function Section({
  title,
  children,
  defaultOpen = true,
  trailing,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  trailing?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="pt-2 first:pt-0 border-t border-gray-100 dark:border-slate-800/50 first:border-t-0">
      <div
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        role="button"
        className="flex items-center gap-2 w-full text-left mb-1.5 cursor-pointer select-none"
      >
        <span className={`text-gray-400 dark:text-slate-500 text-xs transition-transform ${open ? "rotate-90" : ""}`}>&#9656;</span>
        <span className="font-semibold text-gray-600 dark:text-slate-300 text-base">{title}</span>
        {trailing}
      </div>
      {open && children}
    </div>
  );
}

/** Show found vs missing expected URLs (plus actually retrieved URLs) for source-retrieval graders */
export function UrlDetails({
  found,
  missing,
  retrieved = [],
}: {
  found: string[];
  missing: string[];
  retrieved?: string[];
}) {
  return (
    <div className="text-sm space-y-1.5 mt-1">
      {found.length > 0 && (
        <div>
          <span className="text-green-600 dark:text-green-400 font-medium">
            Found ({found.length})
          </span>
          <ul className="mt-0.5 space-y-0.5">
            {found.map((url) => (
              <li key={url} className="text-gray-500 dark:text-slate-400 truncate" title={url}>
                {url}
              </li>
            ))}
          </ul>
        </div>
      )}
      {missing.length > 0 && (
        <div>
          <span className="text-red-600 dark:text-red-400 font-medium">
            Missing ({missing.length})
          </span>
          <ul className="mt-0.5 space-y-0.5">
            {missing.map((url) => (
              <li key={url} className="text-gray-500 dark:text-slate-400 truncate" title={url}>
                {url}
              </li>
            ))}
          </ul>
        </div>
      )}
      {retrieved.length > 0 && (
        <div>
          <span className="text-gray-600 dark:text-slate-300 font-medium">
            Retrieved ({retrieved.length})
          </span>
          <ul className="mt-0.5 space-y-0.5">
            {retrieved.map((url) => (
              <li key={url} className="text-gray-500 dark:text-slate-400 truncate" title={url}>
                {url}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Box with a max-height that can be expanded to show full content */
export function ExpandableBox({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [children]);

  return (
    <div className="relative group/box">
      <div
        ref={ref}
        className={`p-3 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-y-auto ${
          expanded ? "max-h-[80vh]" : "max-h-72"
        } ${className}`}
      >
        {children}
      </div>
      <div className="absolute bottom-2 right-2 flex items-center gap-1">
        <CopyButton
          getText={() => ref.current?.innerText ?? ""}
          className="opacity-0 group-hover/box:opacity-100 p-1 rounded bg-gray-100 dark:bg-slate-800"
        />
        {(overflows || expanded) && (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
            className="text-sm px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 transition-colors"
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        )}
      </div>
    </div>
  );
}
