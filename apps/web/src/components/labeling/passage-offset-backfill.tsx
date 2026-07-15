"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  ApiError,
  getPassageOffsetBackfillLatest,
  startPassageOffsetBackfill,
  type PassageOffsetBackfillRun,
} from "@/lib/api";

const isRunning = (r: PassageOffsetBackfillRun | null) =>
  r != null && (r.status === "pending" || r.status === "running");

// A small maintenance trigger in the labeling controls bar: backfill document-anchored char offsets
// onto passage selections whose chunk has since gained chunk_char_start (e.g. after enabling the
// offset-carrying chunker). Self-contained — loads the latest run on mount, launches on click, and
// polls until the run finishes, then shows the per-outcome tallies. Only rendered when the labeler
// can edit and an index is connected (the caller gates that).
export function PassageOffsetBackfill({ canEdit }: { canEdit: boolean }) {
  const [run, setRun] = useState<PassageOffsetBackfillRun | null>(null);
  const [starting, setStarting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await getPassageOffsetBackfillLatest();
      setRun(r.run);
    } catch {
      /* transient — the next poll or action retries */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while a run is in flight so the progress + final tallies land without a manual reload.
  useEffect(() => {
    if (!isRunning(run)) return;
    const t = setInterval(() => void refresh(), 1500);
    return () => clearInterval(t);
  }, [run, refresh]);

  const start = useCallback(() => {
    setStarting(true);
    startPassageOffsetBackfill()
      .then(setRun)
      .catch(async (e) => {
        // 409 = a run is already in progress; just surface it rather than erroring.
        await refresh();
        if (!(e instanceof ApiError && e.status === 409)) {
          toast.error("Could not start passage offset backfill");
        }
      })
      .finally(() => setStarting(false));
  }, [refresh]);

  const busy = starting || isRunning(run);

  let status: React.ReactNode = null;
  if (isRunning(run) && run) {
    const { processed_chunks: done, total_chunks: total } = run;
    status = (
      <span className="text-gray-400 dark:text-slate-500">
        Anchoring… {total ? `${done}/${total}` : ""}
      </span>
    );
  } else if (run?.status === "completed") {
    const skipped =
      run.no_offset + run.chunk_missing + run.no_split_match + run.drifted;
    status = (
      <span
        className="text-gray-400 dark:text-slate-500"
        title={
          `Anchored ${run.anchored} passage label(s).\n` +
          `Skipped ${skipped}: no offset yet ${run.no_offset}, chunk missing ${run.chunk_missing}, ` +
          `no split match ${run.no_split_match}, text drifted ${run.drifted}.`
        }
      >
        · anchored {run.anchored}
        {skipped > 0 ? `, skipped ${skipped}` : ""}
      </span>
    );
  } else if (run?.status === "failed") {
    status = (
      <span
        className="text-red-600 dark:text-red-400"
        title={run.error ?? "Backfill failed"}
      >
        · backfill failed
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1.5">
      <button
        onClick={start}
        disabled={!canEdit || busy}
        title="Fill document-anchored char offsets on passage selections whose chunk now carries chunk_char_start (e.g. after re-indexing with the offset-aware chunker). Only fills missing offsets; never overwrites. Run before a re-chunk."
        className="px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
      >
        Backfill passage offsets
      </button>
      {status}
    </span>
  );
}
