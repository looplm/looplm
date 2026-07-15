"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import {
  getChunkPassages,
  savePassageSelections,
  type ChunkPassagesResponse,
  type PassageForLabeling,
} from "@/lib/api";

// A passage is "helps" (checked) unless the labeler has explicitly unchecked it. Unlabeled (null)
// reads as still-helpful — the panel's job is to let them *uncheck* passages that don't help.
const isChecked = (relevant: number | null | undefined) => relevant !== 0;

// Collapsible passage-selection panel under a pooled chunk — the additive refinement of chunk
// labeling. The chunk grade stays the primary judgment; here the labeler unchecks the passages
// within the chunk that don't actually help answer the question. Passages are fetched lazily on
// first expand (sentence-level, grouped by their section heading) and each toggle persists on its
// own, keyed by (test_id, chunk_id, passage_id).
export function PassagePanel({
  testId,
  chunkId,
  canEdit,
  indexConnected,
}: {
  testId: string;
  chunkId: string;
  canEdit: boolean;
  indexConnected: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [data, setData] = useState<ChunkPassagesResponse | null>(null);
  // passage_id -> optimistic relevant (1 | 0), overlaying the fetched value.
  const [overrides, setOverrides] = useState<Record<string, number>>({});

  const load = useCallback(() => {
    if (state === "loading" || state === "loaded") return;
    setState("loading");
    getChunkPassages(testId, chunkId)
      .then((r) => {
        setData(r);
        setState("loaded");
      })
      .catch(() => setState("error"));
  }, [testId, chunkId, state]);

  const toggle = (p: PassageForLabeling, next: boolean) => {
    const relevant = next ? 1 : 0;
    const prev = overrides[p.passage_id];
    setOverrides((m) => ({ ...m, [p.passage_id]: relevant }));
    savePassageSelections(testId, chunkId, [
      {
        passage_id: p.passage_id,
        relevant,
        passage_source: p.passage_source,
        section_path: p.section_path,
        text_preview: p.text,
        char_start: p.char_start,
        char_end: p.char_end,
      },
    ]).catch(() => {
      toast.error("Failed to save passage selection");
      setOverrides((m) => {
        const copy = { ...m };
        if (prev === undefined) delete copy[p.passage_id];
        else copy[p.passage_id] = prev;
        return copy;
      });
    });
  };

  if (!indexConnected) return null;

  const passages = data?.passages ?? [];
  // Group passages by their section heading, preserving reading order of both sections and passages.
  const sections: { heading: string | null; items: PassageForLabeling[] }[] = [];
  for (const p of passages) {
    const heading = p.section_path ?? null;
    const last = sections[sections.length - 1];
    if (last && last.heading === heading) last.items.push(p);
    else sections.push({ heading, items: [p] });
  }
  const uncheckedCount = passages.filter(
    (p) => !isChecked(p.passage_id in overrides ? overrides[p.passage_id] : p.relevant),
  ).length;

  return (
    <div className="mt-1.5">
      <button
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) load();
        }}
        className="flex items-center gap-1.5 text-[11px] font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
      >
        <span>{open ? "▾" : "▸"}</span>
        Select helpful passages
        {state === "loaded" && passages.length > 0 && (
          <span className="font-normal text-gray-400 dark:text-slate-500">
            · {passages.length - uncheckedCount}/{passages.length} kept
          </span>
        )}
      </button>

      {open && (
        <div className="mt-1.5 rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50/60 dark:bg-slate-900/40 px-3 py-2">
          {state === "loading" && (
            <p className="text-[12px] italic text-gray-400 dark:text-slate-500">
              Loading passages from index…
            </p>
          )}
          {state === "error" && (
            <p className="text-[12px] italic text-gray-400 dark:text-slate-500">
              Could not load passages.
            </p>
          )}
          {state === "loaded" && passages.length === 0 && (
            <p className="text-[12px] italic text-gray-400 dark:text-slate-500">
              {data?.provider_connected
                ? "No passages to select for this chunk."
                : "Connect an index provider to select passages."}
            </p>
          )}

          {state === "loaded" && passages.length > 0 && (
            <>
              <p className="text-[11px] text-gray-400 dark:text-slate-500 mb-1.5">
                Uncheck the passages that don&apos;t help answer this question.
              </p>
              <div className="space-y-2">
                {sections.map((section, si) => (
                  <div key={si}>
                    {section.heading && (
                      <p className="text-[10px] uppercase tracking-wide font-semibold text-gray-400 dark:text-slate-500 mb-1">
                        {section.heading}
                      </p>
                    )}
                    <div className="space-y-1">
                      {section.items.map((p) => {
                        const checked = isChecked(
                          p.passage_id in overrides ? overrides[p.passage_id] : p.relevant,
                        );
                        return (
                          <label
                            key={p.passage_id}
                            className={`flex items-start gap-2 text-[13px] leading-snug cursor-pointer ${
                              checked
                                ? "text-gray-700 dark:text-slate-200"
                                : "text-gray-400 dark:text-slate-500 line-through"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={!canEdit}
                              onChange={(e) => toggle(p, e.target.checked)}
                              className="mt-0.5 shrink-0 accent-indigo-600"
                            />
                            <span className="whitespace-pre-wrap">{p.text}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
