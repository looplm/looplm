"use client";

import { useEffect, useState } from "react";
import {
  updateRetrievalRunMeta,
  type RetrievalRunRecord,
  type RetrievalRunSummary,
} from "@/lib/api";

// Inline editor for a run's metadata — used both right after an auto-save and from the history
// list. The user annotates the snapshot (name, RAG pipeline version, index name/version, notes);
// index name is pre-filled from the connected provider captured at save time. Takes a summary so
// either a freshly-created record or a list row can be edited.
export function RunMetadataEditor({
  run,
  canEdit,
  onSaved,
}: {
  run: RetrievalRunSummary;
  canEdit: boolean;
  onSaved?: (updated: RetrievalRunRecord) => void;
}) {
  const [name, setName] = useState(run.name ?? "");
  const [pipelineVersion, setPipelineVersion] = useState(run.pipeline_version ?? "");
  const [indexName, setIndexName] = useState(run.index_name ?? "");
  const [indexVersion, setIndexVersion] = useState(run.index_version ?? "");
  const [notes, setNotes] = useState(run.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Reset the form when a new run is snapshotted (Compute/Recompute produces a new id).
  useEffect(() => {
    setName(run.name ?? "");
    setPipelineVersion(run.pipeline_version ?? "");
    setIndexName(run.index_name ?? "");
    setIndexVersion(run.index_version ?? "");
    setNotes(run.notes ?? "");
    setSaved(false);
  }, [run.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    name !== (run.name ?? "") ||
    pipelineVersion !== (run.pipeline_version ?? "") ||
    indexName !== (run.index_name ?? "") ||
    indexVersion !== (run.index_version ?? "") ||
    notes !== (run.notes ?? "");

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await updateRetrievalRunMeta(run.id, {
        name: name || null,
        pipeline_version: pipelineVersion || null,
        index_name: indexName || null,
        index_version: indexVersion || null,
        notes: notes || null,
      });
      onSaved?.(updated);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  const field = "text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 disabled:opacity-60";

  return (
    <div className="mb-4 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
          Saved as run · annotate it
        </span>
        <div className="flex items-center gap-2">
          {saved && !dirty && <span className="text-xs text-emerald-600 dark:text-emerald-400">Saved ✓</span>}
          {canEdit && (
            <button
              onClick={save}
              disabled={saving || !dirty}
              className="text-xs font-medium rounded-lg px-3 py-1.5 bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save metadata"}
            </button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <input className={field} placeholder="Run name" value={name} disabled={!canEdit} onChange={(e) => setName(e.target.value)} />
        <input className={field} placeholder="RAG pipeline version" value={pipelineVersion} disabled={!canEdit} onChange={(e) => setPipelineVersion(e.target.value)} />
        <input className={field} placeholder="Index name" value={indexName} disabled={!canEdit} onChange={(e) => setIndexName(e.target.value)} />
        <input className={field} placeholder="Index version" value={indexVersion} disabled={!canEdit} onChange={(e) => setIndexVersion(e.target.value)} />
      </div>
      <textarea
        className={`${field} w-full mt-2 resize-y`}
        placeholder="Notes (what changed in this run?)"
        rows={2}
        value={notes}
        disabled={!canEdit}
        onChange={(e) => setNotes(e.target.value)}
      />
    </div>
  );
}
