"use client";

import { useState } from "react";
import type { Integration } from "@/lib/api";
import StatusBadge from "@/components/status-badge";

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
}: IntegrationCardProps) {
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
      {i.sync_status === "syncing" && (
        <div className="mt-3">
          {i.sync_progress_total != null ? (
            <>
              <div className="flex items-center justify-between text-sm text-gray-500 dark:text-slate-400 mb-1.5">
                <span>Syncing traces...</span>
                <span>{i.sync_progress_current ?? 0} / {i.sync_progress_total}</span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-300 animate-pulse"
                  style={{
                    width: i.sync_progress_total > 0
                      ? `${Math.round(((i.sync_progress_current ?? 0) / i.sync_progress_total) * 100)}%`
                      : "100%",
                  }}
                />
              </div>
            </>
          ) : (
            <div className="space-y-1.5">
              <p className="text-sm text-gray-500 dark:text-slate-400">Starting sync...</p>
              <div className="h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                <div className="h-full w-1/3 rounded-full bg-blue-500 animate-[indeterminate_1.5s_ease-in-out_infinite]" />
              </div>
            </div>
          )}
          <p className="mt-2 text-xs text-gray-400 dark:text-slate-500">
            Sync runs in the background — you can safely navigate away.
          </p>
        </div>
      )}
      {i.sync_status === "error" && i.last_sync_error && (
        <div className="mt-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          <p>Sync error: {i.last_sync_error}</p>
          {i.sync_progress_current != null && i.sync_progress_total != null && (
            <p className="mt-1 text-red-400/70">
              Failed after processing {i.sync_progress_current} of {i.sync_progress_total} traces
            </p>
          )}
        </div>
      )}
    </div>
  );
}
