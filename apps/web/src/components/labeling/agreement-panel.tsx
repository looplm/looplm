"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import {
  getAgreement,
  setGold,
  type AgreementReport,
  type Disagreement,
} from "@/lib/api";
import { gradeLabel } from "./types";
import { GradeSelector } from "./grade-selector";

// Cohen's kappa interpretation (Landis & Koch bands), for a plain-language verdict.
function kappaVerdict(k: number): { text: string; cls: string } {
  if (k < 0.2) return { text: "slight agreement", cls: "text-red-600 dark:text-red-400" };
  if (k < 0.4) return { text: "fair agreement", cls: "text-amber-600 dark:text-amber-400" };
  if (k < 0.6) return { text: "moderate agreement", cls: "text-amber-600 dark:text-amber-400" };
  if (k < 0.8) return { text: "substantial agreement", cls: "text-emerald-600 dark:text-emerald-400" };
  return { text: "almost perfect agreement", cls: "text-emerald-600 dark:text-emerald-400" };
}

// Inter-annotator agreement (Cohen's kappa) over double-judged chunks, plus an adjudication
// list to resolve disagreements into gold. Project-wide; loads on expand.
export function AgreementPanel({ canEdit }: { canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<AgreementReport | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [goldByKey, setGoldByKey] = useState<Record<string, number>>({});

  const load = useCallback(() => {
    setState("loading");
    getAgreement()
      .then((r) => {
        setReport(r);
        setState("loaded");
      })
      .catch(() => setState("error"));
  }, []);

  const onToggle = () => {
    const next = !open;
    setOpen(next);
    if (next && state === "idle") load();
  };

  const adjudicate = (d: Disagreement, grade: number) => {
    const key = `${d.test_id}|${d.chunk_id}`;
    const prev = goldByKey[key];
    setGoldByKey((m) => ({ ...m, [key]: grade }));
    setGold(d.test_id, d.chunk_id, grade).catch(() => {
      toast.error("Failed to adjudicate");
      setGoldByKey((m) => {
        const next = { ...m };
        if (prev == null) delete next[key];
        else next[key] = prev;
        return next;
      });
    });
  };

  const k = report?.average_kappa;
  const verdict = k != null ? kappaVerdict(k) : null;

  return (
    <div className="mb-4 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-[12px] font-medium text-gray-600 dark:text-slate-300 hover:bg-gray-50/60 dark:hover:bg-slate-800/30"
      >
        <span className="text-gray-400">{open ? "▾" : "▸"}</span>
        Annotator agreement
        {report?.available && verdict && (
          <span className={`ml-1 ${verdict.cls}`}>
            κ {k!.toFixed(2)} · {verdict.text}
          </span>
        )}
        {report && !report.available && (
          <span className="ml-1 font-normal text-gray-400 dark:text-slate-500">
            optional · single annotator
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-gray-100 dark:border-slate-800">
          {state === "loading" ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-3">Computing agreement…</p>
          ) : state === "error" ? (
            <p className="text-[12px] text-red-500 py-3">Failed to load agreement.</p>
          ) : !report || !report.available ? (
            <p className="text-[12px] text-gray-400 dark:text-slate-500 py-3">
              Agreement is optional. A single annotator is enough to label, and those labels are
              the ground truth on their own. To check consistency, run the AI judge on a case (or
              have a second reviewer judge a 10–15% overlap sample) and Cohen&apos;s κ plus any
              disagreements show up here.
            </p>
          ) : (
            <div className="pt-3 space-y-4">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[12px] text-gray-500 dark:text-slate-400">
                <span>
                  <span className="font-semibold tabular-nums">{report.overlap_count}</span>{" "}
                  double-judged chunks ({Math.round(report.double_judged_pct * 100)}% of{" "}
                  {report.judged_items})
                </span>
                <span>{report.annotators.map((a) => `${a.name} (${a.judged_count})`).join(", ")}</span>
              </div>

              {report.pairwise.length > 1 && (
                <div className="text-[11px] text-gray-500 dark:text-slate-400 space-y-0.5">
                  {report.pairwise.map((p) => (
                    <div key={`${p.a}-${p.b}`}>
                      {p.a} ↔ {p.b}: κ {p.kappa.toFixed(2)} <span className="text-gray-400">(n={p.n})</span>
                    </div>
                  ))}
                </div>
              )}

              {report.disagreements.length > 0 ? (
                <div>
                  <div className="text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-2">
                    Disagreements to adjudicate ({report.disagreements.length})
                  </div>
                  <div className="rounded-lg border border-gray-100 dark:border-slate-800 divide-y divide-gray-50 dark:divide-slate-800/50">
                    {report.disagreements.map((d) => {
                      const key = `${d.test_id}|${d.chunk_id}`;
                      const gold = goldByKey[key] ?? d.gold ?? null;
                      return (
                        <div key={key} className="flex items-start gap-3 px-3 py-2.5">
                          <div className="min-w-0 flex-1">
                            <p className="text-[12px] text-gray-700 dark:text-slate-300 truncate">
                              {d.title || d.chunk_id}
                            </p>
                            <p className="text-[11px] text-gray-400 dark:text-slate-500">
                              {d.votes
                                .map((v) => `${v.labeler}: ${v.relevance} (${gradeLabel(v.relevance)})`)
                                .join(" · ")}
                              {gold != null && (
                                <span className="ml-2 text-gray-500 dark:text-slate-400">
                                  → gold: {gold} ({gradeLabel(gold)})
                                </span>
                              )}
                            </p>
                          </div>
                          <GradeSelector
                            value={gold}
                            disabled={!canEdit}
                            onSelect={(grade) => adjudicate(d, grade)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <p className="text-[12px] text-gray-400 dark:text-slate-500">
                  No disagreements among the double-judged chunks.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
