"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import type { EvalRunListItem, EvaluatorItem } from "@/lib/api-types/evals";
import { getEvaluators } from "@/lib/api";
import {
  DeltaBadge,
  MiniBar,
  PassFailBadge,
  RelevanceBadge,
  SourceBadge,
  formatPercent,
  formatScoreValue,
  formatScoreLabel,
} from "./compare-runs-badges";

interface CompareRunsModalProps {
  runs: EvalRunListItem[];
  onClose: () => void;
}

export function CompareRunsModal({ runs, onClose }: CompareRunsModalProps) {
  const [evaluatorMap, setEvaluatorMap] = useState<Record<string, EvaluatorItem>>({});

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Fetch evaluators for display names and metadata
  useEffect(() => {
    getEvaluators()
      .then((resp) => {
        const map: Record<string, EvaluatorItem> = {};
        for (const ev of resp.data) {
          map[ev.name] = ev;
        }
        setEvaluatorMap(map);
      })
      .catch(() => {});
  }, []);

  const sorted = useMemo(
    () => [...runs].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    [runs]
  );

  const isTwoRun = sorted.length === 2;

  // Detect if runs come from the same session (experiment comparison)
  const isExperimentComparison = useMemo(() => {
    if (sorted.length < 2) return false;
    const sessionIds = sorted.map((r) => (r.metadata as Record<string, unknown>)?.session_id).filter(Boolean);
    return sessionIds.length === sorted.length && new Set(sessionIds).size === 1;
  }, [sorted]);

  // Get experiment name for a run from its metadata
  function getRunLabel(run: EvalRunListItem, index: number): string {
    const meta = run.metadata as Record<string, unknown>;
    if (isExperimentComparison && meta?.experiment_name) {
      return String(meta.experiment_name);
    }
    if (isTwoRun) return index === 0 ? "Baseline" : "Latest";
    return run.name;
  }

  // Collect experiment variable diffs for display
  const experimentVariableDiffs = useMemo(() => {
    if (!isExperimentComparison) return null;
    const allKeys = new Set<string>();
    const varsByRun: Record<string, string>[] = [];
    for (const run of sorted) {
      const vars = ((run.metadata as Record<string, unknown>)?.experiment_variables as Record<string, string>) || {};
      varsByRun.push(vars);
      Object.keys(vars).forEach((k) => allKeys.add(k));
    }
    if (allKeys.size === 0) return null;
    return { keys: Array.from(allKeys).sort(), varsByRun };
  }, [sorted, isExperimentComparison]);

  // Collect all grader keys and sort by source, then relevance, then name
  const allGraderKeys = useMemo(() => {
    const keys = new Set<string>();
    sorted.forEach((r) => Object.keys(r.grader_summary).forEach((k) => keys.add(k)));
    const sourceOrder: Record<string, number> = { custom: 0, ragas: 1, langfuse: 2 };
    const relevanceOrder: Record<string, number> = { core: 0, important: 1, minor: 2 };
    return Array.from(keys).sort((a, b) => {
      const metaA = evaluatorMap[a];
      const metaB = evaluatorMap[b];
      const srcA = sourceOrder[metaA?.source ?? ""] ?? 3;
      const srcB = sourceOrder[metaB?.source ?? ""] ?? 3;
      if (srcA !== srcB) return srcA - srcB;
      const relA = relevanceOrder[metaA?.relevance ?? "minor"] ?? 2;
      const relB = relevanceOrder[metaB?.relevance ?? "minor"] ?? 2;
      if (relA !== relB) return relA - relB;
      return a.localeCompare(b);
    });
  }, [sorted, evaluatorMap]);

  const allScoreKeys = useMemo(() => {
    const keys = new Set<string>();
    sorted.forEach((r) => Object.keys(r.score_summary).forEach((k) => keys.add(k)));
    return Array.from(keys).sort((a, b) => {
      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      const deltaA = Math.abs((last.score_summary[a]?.avg ?? 0) - (first.score_summary[a]?.avg ?? 0));
      const deltaB = Math.abs((last.score_summary[b]?.avg ?? 0) - (first.score_summary[b]?.avg ?? 0));
      return deltaB - deltaA;
    });
  }, [sorted]);

  function graderDirection(key: string): "up" | "down" | "same" {
    const first = sorted[0].grader_summary[key]?.pass_rate;
    const last = sorted[sorted.length - 1].grader_summary[key]?.pass_rate;
    if (first == null || last == null) return "same";
    const delta = last - first;
    if (delta > 0.0005) return "up";
    if (delta < -0.0005) return "down";
    return "same";
  }

  function getDisplayName(key: string): string {
    return evaluatorMap[key]?.display_name || key;
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 backdrop-blur-md z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 shadow-2xl w-full max-w-5xl max-h-[85vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700 shrink-0">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              Compare Runs
            </h2>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-auto">
            {/* Hero: Overall Pass Rate Cards */}
            <div className="px-6 pt-5 pb-4">
              <div className="flex items-center gap-3 justify-center flex-wrap">
                {sorted.map((run, i) => (
                  <Fragment key={run.id}>
                    <div className="flex-1 min-w-[160px] max-w-[220px] rounded-xl border border-gray-200 dark:border-slate-700 p-4 text-center bg-gray-50 dark:bg-slate-800/40">
                      {(isTwoRun || isExperimentComparison) && (
                        <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-400 dark:text-slate-500 mb-1">
                          {getRunLabel(run, i)}
                        </div>
                      )}
                      <div className="text-xs text-gray-500 dark:text-slate-400 truncate" title={run.name}>
                        {run.name}
                      </div>
                      <div className="text-xs text-gray-400 dark:text-slate-500 mb-2">
                        {new Date(run.created_at).toLocaleString("de-DE", {
                          day: "2-digit", month: "2-digit", year: "2-digit",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </div>
                      <div className="text-2xl font-bold text-gray-900 dark:text-white">
                        {formatPercent(run.pass_rate)}
                      </div>
                      <MiniBar rate={run.pass_rate} />
                      <div className="mt-2 text-xs text-gray-500 dark:text-slate-400">
                        <span className="text-green-600 dark:text-green-400 font-medium">{run.passed}</span>
                        {" / "}
                        <span className="text-red-600 dark:text-red-400 font-medium">{run.failed}</span>
                        {" / "}
                        {run.total}
                      </div>
                    </div>
                    {i < sorted.length - 1 && (
                      <div className="flex flex-col items-center gap-1 px-1">
                        <svg className="w-4 h-4 text-gray-300 dark:text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                          <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <DeltaBadge
                          current={sorted[i + 1].pass_rate}
                          previous={run.pass_rate}
                          isPercent
                        />
                      </div>
                    )}
                  </Fragment>
                ))}
              </div>
            </div>

            {/* Experiment Variable Diffs */}
            {experimentVariableDiffs && (
              <div className="px-6 pb-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
                  Experiment Variables
                </div>
                <div className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
                  <table className="w-full text-sm border-collapse">
                    <thead>
                      <tr className="bg-gray-50 dark:bg-slate-800/50 border-b border-gray-200 dark:border-slate-700">
                        <th className="px-4 py-2 text-left font-medium text-gray-500 dark:text-slate-400 min-w-[160px]">
                          Variable
                        </th>
                        {sorted.map((run, i) => (
                          <th key={run.id} className="px-3 py-2 text-center font-medium text-gray-600 dark:text-slate-300 min-w-[110px]">
                            <div className="truncate max-w-[180px] mx-auto text-xs">
                              {getRunLabel(run, i)}
                            </div>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {experimentVariableDiffs.keys.map((key, rowIdx) => (
                        <tr
                          key={key}
                          className={`border-b border-gray-100 dark:border-slate-800/50 ${
                            rowIdx % 2 === 0 ? "bg-white dark:bg-slate-900" : "bg-gray-50/50 dark:bg-slate-800/20"
                          }`}
                        >
                          <td className="px-4 py-2 font-mono text-xs text-gray-700 dark:text-slate-300">{key}</td>
                          {experimentVariableDiffs.varsByRun.map((vars, i) => (
                            <td key={i} className="px-3 py-2 text-center font-mono text-xs text-gray-600 dark:text-slate-400">
                              {vars[key] ?? <span className="text-gray-300 dark:text-slate-600">--</span>}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Grader Pass Rates Table */}
            {allGraderKeys.length > 0 && (
              <div className="px-6 pb-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
                  Grader Pass Rates
                </div>
                <div className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
                  <table className="w-full text-sm border-collapse">
                    <thead>
                      <tr className="bg-gray-50 dark:bg-slate-800/50 border-b border-gray-200 dark:border-slate-700">
                        <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-slate-400 sticky left-0 bg-gray-50 dark:bg-slate-800/50 z-10 min-w-[240px]">
                          Grader
                        </th>
                        {sorted.map((run, i) => (
                          <Fragment key={run.id}>
                            <th className="px-3 py-2.5 text-center font-medium text-gray-600 dark:text-slate-300 min-w-[110px]">
                              <div className="truncate max-w-[180px] mx-auto text-xs" title={run.name}>
                                {getRunLabel(run, i)}
                              </div>
                            </th>
                            {i < sorted.length - 1 && (
                              <th className="px-2 py-2.5 text-center text-xs font-normal text-gray-400 dark:text-slate-500 min-w-[80px]">
                                Change
                              </th>
                            )}
                          </Fragment>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {allGraderKeys.map((key, rowIdx) => {
                        const dir = graderDirection(key);
                        const meta = evaluatorMap[key];
                        const borderColor = dir === "up"
                          ? "border-l-[3px] border-l-green-400 dark:border-l-green-500"
                          : dir === "down"
                          ? "border-l-[3px] border-l-red-400 dark:border-l-red-500"
                          : "border-l-[3px] border-l-transparent";
                        return (
                          <tr
                            key={key}
                            className={`border-b border-gray-100 dark:border-slate-800/50 ${borderColor} ${
                              rowIdx % 2 === 0 ? "bg-white dark:bg-slate-900" : "bg-gray-50/50 dark:bg-slate-800/20"
                            }`}
                          >
                            <td
                              className={`px-4 py-2.5 sticky left-0 z-10 ${
                                rowIdx % 2 === 0 ? "bg-white dark:bg-slate-900" : "bg-gray-50/50 dark:bg-slate-800/20"
                              }`}
                            >
                              <div className="flex flex-col gap-1">
                                <span className="font-medium text-gray-900 dark:text-white truncate block max-w-[220px]" title={getDisplayName(key)}>
                                  {getDisplayName(key)}
                                </span>
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  {meta && <SourceBadge source={meta.source ?? null} />}
                                  {meta && <RelevanceBadge relevance={meta.relevance} />}
                                  {meta && <PassFailBadge affectsPass={meta.affects_pass} />}
                                  {meta?.display_name && (
                                    <span className="text-[10px] text-gray-400 dark:text-slate-500">{key}</span>
                                  )}
                                </div>
                              </div>
                            </td>
                            {sorted.map((run, i) => {
                              const grader = run.grader_summary[key];
                              return (
                                <Fragment key={run.id}>
                                  <td className="px-3 py-2.5 text-center">
                                    {grader ? (
                                      <div>
                                        <span className="font-medium text-gray-900 dark:text-white">
                                          {formatPercent(grader.pass_rate)}
                                        </span>
                                        <MiniBar rate={grader.pass_rate} />
                                      </div>
                                    ) : (
                                      <span className="text-gray-300 dark:text-slate-600">--</span>
                                    )}
                                  </td>
                                  {i < sorted.length - 1 && (
                                    <td className="px-2 py-2.5 text-center">
                                      <DeltaBadge
                                        current={sorted[i + 1].grader_summary[key]?.pass_rate}
                                        previous={grader?.pass_rate}
                                        isPercent
                                      />
                                    </td>
                                  )}
                                </Fragment>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Score Averages Table */}
            {allScoreKeys.length > 0 && (
              <div className="px-6 pt-3 pb-5">
                <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2">
                  Score Averages
                </div>
                <div className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
                  <table className="w-full text-sm border-collapse">
                    <thead>
                      <tr className="bg-gray-50 dark:bg-slate-800/50 border-b border-gray-200 dark:border-slate-700">
                        <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-slate-400 sticky left-0 bg-gray-50 dark:bg-slate-800/50 z-10 min-w-[240px]">
                          Score
                        </th>
                        {sorted.map((run, i) => (
                          <Fragment key={run.id}>
                            <th className="px-3 py-2.5 text-center font-medium text-gray-600 dark:text-slate-300 min-w-[110px]">
                              <div className="truncate max-w-[180px] mx-auto text-xs" title={run.name}>
                                {getRunLabel(run, i)}
                              </div>
                            </th>
                            {i < sorted.length - 1 && (
                              <th className="px-2 py-2.5 text-center text-xs font-normal text-gray-400 dark:text-slate-500 min-w-[80px]">
                                Change
                              </th>
                            )}
                          </Fragment>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {allScoreKeys.map((key, rowIdx) => (
                        <tr
                          key={key}
                          className={`border-b border-gray-100 dark:border-slate-800/50 ${
                            rowIdx % 2 === 0 ? "bg-white dark:bg-slate-900" : "bg-gray-50/50 dark:bg-slate-800/20"
                          }`}
                        >
                          <td
                            className={`px-4 py-2.5 sticky left-0 z-10 ${
                              rowIdx % 2 === 0 ? "bg-white dark:bg-slate-900" : "bg-gray-50/50 dark:bg-slate-800/20"
                            }`}
                          >
                            <span className="font-medium text-gray-900 dark:text-white truncate block max-w-[220px]" title={key}>
                              {formatScoreLabel(key)}
                            </span>
                          </td>
                          {sorted.map((run, i) => {
                            const score = run.score_summary[key];
                            return (
                              <Fragment key={run.id}>
                                <td className="px-3 py-2.5 text-center">
                                  {score ? (
                                    <div>
                                      <span className="font-medium text-gray-900 dark:text-white">
                                        {formatScoreValue(key, score.avg)}
                                      </span>
                                      <div className="text-[10px] text-gray-400 dark:text-slate-500">
                                        {formatScoreValue(key, score.min)}–{formatScoreValue(key, score.max)}
                                      </div>
                                    </div>
                                  ) : (
                                    <span className="text-gray-300 dark:text-slate-600">--</span>
                                  )}
                                </td>
                                {i < sorted.length - 1 && (
                                  <td className="px-2 py-2.5 text-center">
                                    <DeltaBadge
                                      current={sorted[i + 1].score_summary[key]?.avg}
                                      previous={score?.avg}
                                    />
                                  </td>
                                )}
                              </Fragment>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Bottom padding if no scores */}
            {allScoreKeys.length === 0 && <div className="pb-5" />}
          </div>
        </div>
      </div>
    </>
  );
}
