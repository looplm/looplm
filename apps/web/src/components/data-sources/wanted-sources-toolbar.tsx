"use client";

/**
 * Action toolbar for the wanted-sources panel: import a CSV, run (or stop) a
 * gap analysis, and download the report. The gap analysis reads the whole
 * index, so starting one is gated behind a confirmation modal; while it runs,
 * the primary action becomes a Stop button wired to the cancel endpoint.
 */

import { useRef, useState } from "react";

import type { GapRunDetail } from "@/lib/api-types/source-registry";

import { ConfirmModal } from "../confirm-modal";

function IconUpload() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      className="h-4 w-4"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 13V4m0 0L6.5 7.5M10 4l3.5 3.5" />
      <path d="M4 13v2.5A1.5 1.5 0 0 0 5.5 17h9a1.5 1.5 0 0 0 1.5-1.5V13" />
    </svg>
  );
}

function IconRun() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4" aria-hidden="true">
      <path d="M6.5 4.3c0-.6.66-.98 1.18-.66l8 5.7a.8.8 0 0 1 0 1.32l-8 5.7A.79.79 0 0 1 6.5 15.7z" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4" aria-hidden="true">
      <rect x="5" y="5" width="10" height="10" rx="1.5" />
    </svg>
  );
}

function IconDownload() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      className="h-4 w-4"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 4v9m0 0L6.5 9.5M10 13l3.5-3.5" />
      <path d="M4 15.5h12" />
    </svg>
  );
}

function IconSpinner() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4 animate-spin" aria-hidden="true">
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="2.2" opacity="0.25" fill="none" />
      <path
        d="M10 3a7 7 0 0 1 7 7"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

const SECONDARY =
  "inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border " +
  "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 " +
  "hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50";

export function WantedSourcesToolbar({
  canEdit,
  hasExpectations,
  running,
  run,
  onImport,
  onRun,
  onCancel,
  onDownloadReport,
}: {
  canEdit: boolean;
  hasExpectations: boolean;
  running: boolean;
  run: GapRunDetail | null;
  onImport: (file: File) => void;
  onRun: () => void;
  onCancel: () => void;
  onDownloadReport: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [confirmRun, setConfirmRun] = useState(false);

  const total = run?.total ?? 0;
  const processed = run?.processed ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-2 ml-auto">
      {canEdit && (
        <>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onImport(f);
              e.target.value = "";
            }}
          />
          <button onClick={() => fileRef.current?.click()} className={SECONDARY}>
            <IconUpload />
            Import CSV
          </button>
        </>
      )}

      {canEdit &&
        hasExpectations &&
        (running ? (
          <>
            <span className="inline-flex items-center gap-2 px-2 text-sm text-gray-500 dark:text-slate-400">
              <IconSpinner />
              Analyzing… {processed}/{total || "?"}
            </span>
            <button
              onClick={onCancel}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-500 transition-colors"
            >
              <IconStop />
              Stop
            </button>
          </>
        ) : (
          <button
            onClick={() => setConfirmRun(true)}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 transition-colors"
          >
            <IconRun />
            Run gap analysis
          </button>
        ))}

      {run?.status === "completed" && (
        <button onClick={onDownloadReport} className={SECONDARY}>
          <IconDownload />
          Download report
        </button>
      )}

      {confirmRun && (
        <ConfirmModal
          title="Run gap analysis?"
          message={
            "This searches the connected index for every wanted source and " +
            "recomputes each coverage verdict. It can take a while on large " +
            "source lists and replaces the results of the previous run."
          }
          confirmLabel="Run analysis"
          onConfirm={() => {
            setConfirmRun(false);
            onRun();
          }}
          onCancel={() => setConfirmRun(false)}
        />
      )}
    </div>
  );
}
