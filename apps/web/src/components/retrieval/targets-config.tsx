"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { getRetrievalTargets, saveRetrievalTargets, type RetrievalTargets } from "@/lib/api";
import { METRICS } from "@/components/retrieval/constants";
import { Info } from "@/components/retrieval/metric-card";

// Representative k used only for the metric labels here; the actual @k is decided per run and
// shown on the Evaluations results view. Targets are single thresholds applied at the run's top k.
const DISPLAY_K = 10;

// Configure the retrieval-quality targets (the pass thresholds for recall@k, nDCG@k, MRR, etc.).
// Configuration only — the computed values live on the Evaluations page. Persists to the same
// per-project targets the results view reads.
export function RetrievalTargetsConfig({ canEdit }: { canEdit: boolean }) {
  const [saved, setSaved] = useState<RetrievalTargets | null>(null);
  const [draft, setDraft] = useState<RetrievalTargets | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRetrievalTargets()
      .then((t) => {
        setSaved(t);
        setDraft(t);
      })
      .catch(() => {
        setSaved(null);
        setDraft(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const setVal = (key: keyof RetrievalTargets, v: number) =>
    setDraft((d) => (d ? { ...d, [key]: Math.max(0, Math.min(1, v)) } : d));

  const dirty = draft && saved && JSON.stringify(draft) !== JSON.stringify(saved);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const next = await saveRetrievalTargets(draft);
      setSaved(next);
      setDraft(next);
      toast.success("Targets saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save targets");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
        Loading targets…
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
        Couldn&apos;t load retrieval targets.
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 divide-y divide-gray-100 dark:divide-slate-800">
      {METRICS.map((m) => {
        const isPct = m.kind === "pct";
        const v = draft[m.key];
        return (
          <div key={m.key} className="flex items-center justify-between gap-4 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {m.label(DISPLAY_K)}
                </span>
                <Info text={m.info} />
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 max-w-2xl">{m.info}</p>
            </div>
            <label className="shrink-0 flex items-center gap-1">
              <span className="text-[11px] text-gray-400 dark:text-slate-500 mr-1">target</span>
              {isPct ? (
                <>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    disabled={!canEdit}
                    value={Math.round(v * 100)}
                    onChange={(e) => setVal(m.key, Number(e.target.value) / 100)}
                    className="w-20 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm tabular-nums disabled:opacity-50"
                  />
                  <span className="text-xs text-gray-400">%</span>
                </>
              ) : (
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  disabled={!canEdit}
                  value={Number(v.toFixed(2))}
                  onChange={(e) => setVal(m.key, Number(e.target.value))}
                  className="w-20 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm tabular-nums disabled:opacity-50"
                />
              )}
            </label>
          </div>
        );
      })}
      <div className="flex items-center justify-end gap-2 px-4 py-3">
        <button
          onClick={save}
          disabled={!canEdit || !dirty || saving}
          className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save targets"}
        </button>
      </div>
    </div>
  );
}
