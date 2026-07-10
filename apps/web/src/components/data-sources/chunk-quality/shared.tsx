"use client";

import { useState } from "react";

import type { Severity } from "@/lib/api-types/chunk-quality";

export const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  warn: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  info: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300",
};

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${SEVERITY_STYLE[severity]}`}>
      {severity}
    </span>
  );
}

export function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-3.5 h-3.5 flex-shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

/** A collapsible family card with a title, a one-line summary, and content. */
export function FamilyCard({
  title,
  summary,
  accent,
  defaultOpen = false,
  children,
}: {
  title: string;
  summary: string;
  accent?: Severity;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const dot =
    accent === "critical"
      ? "bg-red-500"
      : accent === "warn"
        ? "bg-amber-500"
        : "bg-green-500";
  return (
    <section className="rounded-xl border border-gray-100 dark:border-slate-800 mb-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <Chevron open={open} />
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
        <span className="font-semibold">{title}</span>
        <span className="ml-auto truncate text-xs text-gray-500 dark:text-slate-400 max-w-[60%] text-right">
          {summary}
        </span>
      </button>
      {open && <div className="border-t border-gray-100 dark:border-slate-800 p-4">{children}</div>}
    </section>
  );
}

/**
 * A plain-language intro at the top of a family card: what this family
 * measures and why a reader should care, written for non-experts.
 */
export function Explainer({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs leading-relaxed text-gray-500 dark:text-slate-400 bg-gray-50 dark:bg-slate-800/40 rounded-lg px-3 py-2">
      {children}
    </p>
  );
}

/** A small labelled metric, used in the per-family stat strips. */
export function Metric({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="min-w-[6rem]">
      <p className="text-xs text-gray-500 dark:text-slate-400">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
      {sub && <p className="text-[11px] text-gray-400 dark:text-slate-500">{sub}</p>}
    </div>
  );
}

/** A horizontal proportion bar (0–100), optionally tinted by severity. */
export function Bar({ pct, tone }: { pct: number; tone?: "good" | "warn" | "bad" }) {
  const color =
    tone === "bad" ? "bg-red-500" : tone === "warn" ? "bg-amber-500" : "bg-indigo-500";
  return (
    <div className="h-2 rounded bg-gray-100 dark:bg-slate-800 overflow-hidden">
      <div className={`h-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v}%`;
}

export function scoreTone(score: number): { label: string; cls: string } {
  if (score >= 80) return { label: "Healthy", cls: "text-green-600 dark:text-green-400" };
  if (score >= 55) return { label: "Needs attention", cls: "text-amber-600 dark:text-amber-400" };
  return { label: "Poor", cls: "text-red-600 dark:text-red-400" };
}
