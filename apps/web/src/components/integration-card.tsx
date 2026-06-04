"use client";

import { useEffect, useState } from "react";
import type { Integration } from "@/lib/api";
import StatusBadge from "@/components/status-badge";

const PHASE_LABELS: Record<NonNullable<Integration["sync_phase"]>, string> = {
  fetching_traces: "Fetching traces",
  processing_traces: "Processing traces",
  fetching_scores: "Fetching scores",
  processing_scores: "Processing scores",
};

// Preset auto-sync cadences. Values (minutes) must match ALLOWED_SYNC_INTERVALS
// in the API; null = disabled.
const AUTO_SYNC_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Off", value: null },
  { label: "Every 15 min", value: 15 },
  { label: "Every 30 min", value: 30 },
  { label: "Hourly", value: 60 },
  { label: "Every 3h", value: 180 },
  { label: "Every 6h", value: 360 },
  { label: "Every 12h", value: 720 },
  { label: "Daily", value: 1440 },
];

function formatElapsed(startedAt: string, now: number): string {
  const diffMs = Math.max(0, now - new Date(startedAt).getTime());
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

function formatSince(iso: string): string | null {
  const date = new Date(iso);
  // Treat anything before 2021 as "all time" — that's the 2020-01-01 fallback
  if (date.getUTCFullYear() < 2021) return null;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

interface IntegrationCardProps {
  integration: Integration;
  updateExisting: boolean;
  customSinceDate: string;
  onEdit: (i: Integration) => void;
  onDelete: (i: Integration) => void;
  onSyncPreset: (id: string, days: number | null) => void;
  onSync: (id: string, since: string) => void;
  onStopSync: (id: string) => void;
  onUpdateExistingChange: (checked: boolean) => void;
  onCustomSinceDateChange: (date: string) => void;
  onAutoSyncChange: (id: string, intervalMinutes: number | null) => void;
}

export function IntegrationCard({
  integration: i,
  updateExisting,
  customSinceDate,
  onEdit,
  onDelete,
  onSyncPreset,
  onSync,
  onStopSync,
  onUpdateExistingChange,
  onCustomSinceDateChange,
  onAutoSyncChange,
}: IntegrationCardProps) {
  const isSyncing = i.sync_status === "syncing";
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isSyncing || !i.sync_started_at) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isSyncing, i.sync_started_at]);

  const phaseLabel = i.sync_phase ? PHASE_LABELS[i.sync_phase] : "Starting sync…";
  const showDeterminate =
    i.sync_phase === "processing_traces" &&
    i.sync_progress_total != null &&
    i.sync_progress_total > 0;
  const sinceLabel = i.sync_since ? formatSince(i.sync_since) : null;

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h3 className="font-semibold">{i.name}</h3>
            <StatusBadge status={i.type} />
            <StatusBadge status={i.sync_status} />
          </div>
          <div className="text-sm text-gray-500 dark:text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
            <span>{i.base_url || "Default endpoint"}</span>
            {i.config?.project ? <span>Project: {String(i.config.project)}</span> : null}
            <span>Last synced: {i.last_synced_at ? new Date(i.last_synced_at).toLocaleString() : "Never"}</span>
            <span className="flex items-center gap-1.5">
              Auto-sync:
              <select
                value={i.auto_sync_interval_minutes ?? ""}
                onChange={(e) =>
                  onAutoSyncChange(i.id, e.target.value === "" ? null : Number(e.target.value))
                }
                className="px-2 py-0.5 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded text-xs"
              >
                {AUTO_SYNC_OPTIONS.map((opt) => (
                  <option key={opt.label} value={opt.value ?? ""}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {i.auto_sync_interval_minutes && i.next_sync_at && i.sync_status !== "syncing" ? (
                <span className="text-gray-400 dark:text-slate-500">
                  · next {new Date(i.next_sync_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              ) : null}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onEdit(i)}
            className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg text-sm"
          >
            Edit
          </button>
          {i.sync_status === "syncing" && (
            <button
              onClick={() => onStopSync(i.id)}
              className="px-3 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-700 dark:bg-amber-600/20 dark:hover:bg-amber-600/40 dark:text-amber-400 rounded-lg text-sm font-medium"
            >
              Stop Sync
            </button>
          )}
          <button
            onClick={() => onDelete(i)}
            disabled={i.sync_status === "syncing"}
            className="px-3 py-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded-lg text-sm disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>
      {i.sync_status !== "syncing" && (
        <div className="mt-4 flex items-center gap-2 flex-wrap">
          <span className="text-sm text-gray-500 dark:text-slate-400 mr-1">Sync:</span>
          <button
            disabled={!i.last_synced_at}
            onClick={() => onSync(i.id, i.last_synced_at!)}
            className="px-3 py-1 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Since last sync
          </button>
          {[
            { label: "1d", days: 1 },
            { label: "3d", days: 3 },
            { label: "7d", days: 7 },
            { label: "30d", days: 30 },
            { label: "All", days: null },
          ].map((preset) => (
            <button
              key={preset.label}
              onClick={() => onSyncPreset(i.id, preset.days)}
              className="px-3 py-1 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded text-sm"
            >
              {preset.label}
            </button>
          ))}
          <span className="text-gray-300 dark:text-slate-600 mx-1">|</span>
          <label className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={updateExisting}
              onChange={(e) => onUpdateExistingChange(e.target.checked)}
              className="rounded border-gray-300 dark:border-slate-600 bg-gray-100 dark:bg-slate-800"
            />
            Update existing
          </label>
          <span className="text-gray-300 dark:text-slate-600 mx-1">|</span>
          <input
            type="date"
            value={customSinceDate}
            onChange={(e) => onCustomSinceDateChange(e.target.value)}
            className="px-2 py-1 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded text-sm"
          />
          <button
            disabled={!customSinceDate}
            onClick={() => {
              const since = new Date(customSinceDate + "T00:00:00").toISOString();
              onSync(i.id, since);
            }}
            className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded text-sm font-medium text-white"
          >
            Sync
          </button>
        </div>
      )}
      {isSyncing && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-sm text-gray-500 dark:text-slate-400 mb-1.5">
            <span>{phaseLabel}</span>
            <span className="flex items-center gap-3">
              {showDeterminate ? (
                <span>
                  {i.sync_progress_current ?? 0} / {i.sync_progress_total} traces
                </span>
              ) : i.sync_progress_current != null && i.sync_progress_current > 0 ? (
                <span>{i.sync_progress_current} fetched</span>
              ) : null}
              {i.sync_started_at && (
                <span className="tabular-nums text-gray-400 dark:text-slate-500">
                  {formatElapsed(i.sync_started_at, now)}
                </span>
              )}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
            {showDeterminate ? (
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-300 animate-pulse"
                style={{
                  width: `${Math.round(((i.sync_progress_current ?? 0) / (i.sync_progress_total ?? 1)) * 100)}%`,
                }}
              />
            ) : (
              <div className="h-full w-1/3 rounded-full bg-blue-500 animate-[indeterminate_1.5s_ease-in-out_infinite]" />
            )}
          </div>
          {i.sync_message && (
            <p className="mt-2 text-xs text-gray-500 dark:text-slate-400 truncate">
              {i.sync_message}
            </p>
          )}
          {sinceLabel && (
            <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">
              Scanning since {sinceLabel}
            </p>
          )}
          <p className="mt-2 text-xs text-gray-400 dark:text-slate-500">
            Sync runs in the background — you can safely navigate away.
          </p>
        </div>
      )}
      {i.sync_status === "error" && i.last_sync_error && (
        <div className="mt-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          <p>Sync error: {i.last_sync_error}</p>
          {i.sync_phase && (
            <p className="mt-1 text-red-400/70">
              Failed during {PHASE_LABELS[i.sync_phase].toLowerCase()}
              {i.sync_progress_current != null && i.sync_progress_total != null && (
                <> ({i.sync_progress_current} of {i.sync_progress_total} processed)</>
              )}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
