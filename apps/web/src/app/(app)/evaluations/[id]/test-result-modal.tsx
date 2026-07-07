"use client";

import { useEffect, useState } from "react";
import type { EvalResultItem, EvaluatorItem, ConversationTurn, RootCauseDetail, EvalGraderResult } from "@/lib/api";
import { sortGraderEntries, sortGraderDetails, formatScoreValue, formatScoreLabel, rootCauseStyle } from "./eval-utils";
import { ExpectedOutputDiff, Section, ExpandableBox, CopyButton } from "./eval-components";
import { GraderResultCard } from "./grader-result-card";
import { ExecutionResultBadge } from "@/components/eval/result-badge";
import { usePermissions } from "@/components/permissions-context";

interface TestResultModalProps {
  result: EvalResultItem;
  disabledGraders: Set<string>;
  evaluatorMap: Record<string, EvaluatorItem>;
  runMetadata?: Record<string, unknown>;
  onClose: () => void;
}

function ExternalLinkIcon({ className = "" }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`inline-block ${className}`}>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

export function TestResultModal({
  result,
  disabledGraders,
  evaluatorMap,
  runMetadata,
  onClose,
}: TestResultModalProps) {
  const [expanded, setExpanded] = useState(true);
  const [showPassed, setShowPassed] = useState(false);
  const { canWrite } = usePermissions();
  const conversationHistory: ConversationTurn[] = (result.metadata?.conversation_history as ConversationTurn[]) || [];

  // Target generation-LLM token usage + the full context block fed into its prompt
  // (see _enrich_result_metadata). The target does not return the literal system prompt.
  const targetUsage = result.metadata?.target_usage as
    | { prompt_tokens: number; completion_tokens: number; total_tokens: number }
    | undefined;
  const modelContext =
    typeof result.metadata?.model_context === "string" ? (result.metadata.model_context as string) : null;
  // The literal prompt, when the target returns it (rde-gpt): system + assembled turns.
  const modelPrompt = result.metadata?.model_prompt as
    | { system?: string; messages?: Array<{ role: string; content: string }> }
    | undefined;

  // Dataset the result's test case belongs to — needed to promote retrieved URLs
  // into the test case's expected URLs. Per-result (new triggered runs), falling
  // back to the run-level dataset_ids.
  const datasetId = typeof result.metadata?.dataset_id === "string"
    ? (result.metadata.dataset_id as string)
    : Array.isArray(runMetadata?.dataset_ids) && (runMetadata!.dataset_ids as string[]).length > 0
      ? (runMetadata!.dataset_ids as string[])[0]
      : undefined;
  const canEditExpectedUrls = canWrite("datasets");

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const graderEntries = Object.entries(result.graders || {}) as [string, EvalGraderResult][];
  const sortedDetailEntries = sortGraderDetails(graderEntries, evaluatorMap);
  const passedCount = sortedDetailEntries.filter(
    ([, g]) => !g.skipped && g.pass
  ).length;
  const visibleDetailEntries = sortedDetailEntries.filter(([, g]) => {
    if (showPassed) return true;
    return g.skipped || !g.pass;
  });

  const critical = visibleDetailEntries.filter(
    ([n, g]) => !g.pass && !g.skipped && evaluatorMap[n]?.affects_pass
  );
  const other = visibleDetailEntries.filter(
    ([n, g]) => !((!g.pass && !g.skipped && evaluatorMap[n]?.affects_pass))
  );

  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]" onClick={onClose} />
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
        <div className={`bg-white dark:bg-slate-900 rounded-xl border border-gray-200 dark:border-slate-700 shadow-xl w-full flex flex-col transition-all duration-200 ${
          expanded ? "max-w-[95vw] max-h-[95vh]" : "max-w-4xl max-h-[90vh]"
        }`}>
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800 shrink-0">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold">{result.test_id}</h2>
              <ExecutionResultBadge executionStatus={result.execution_status} pass={result.pass} />
              {result.turns_to_pass != null && result.turns_to_pass > 1 && (
                <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                  Turn {result.turns_to_pass}
                </span>
              )}
              {conversationHistory.length > 1 && !result.pass && (
                <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
                  {conversationHistory.length} turns
                </span>
              )}

              {/* Navigation links */}
              {(() => {
                const hasTrace = typeof result.metadata?.trace_id === "string";
                if (!hasTrace && !datasetId) return null;
                return (
                  <div className="flex items-center gap-3 ml-2">
                    <span className="text-gray-300 dark:text-slate-600">|</span>
                    {hasTrace && (
                      <a
                        href={`/traces/${result.metadata!.trace_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 flex items-center gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Trace <ExternalLinkIcon />
                      </a>
                    )}
                    {datasetId && (
                      <a
                        href={`/datasets/${datasetId}?highlight=${encodeURIComponent(result.test_id)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 flex items-center gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Test Case <ExternalLinkIcon />
                      </a>
                    )}
                  </div>
                );
              })()}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 p-1"
                title={expanded ? "Shrink" : "Expand"}
              >
                {expanded ? (
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="4 14 10 14 10 20" />
                    <polyline points="20 10 14 10 14 4" />
                    <line x1="14" y1="10" x2="21" y2="3" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                )}
              </button>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 text-xl">
                &times;
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="p-4 overflow-y-auto flex-1">
            <div className="flex flex-col gap-2 text-base">
              {/* Execution health — degraded/errored rows were not graded */}
              {result.execution_status !== "ok" && (() => {
                const exec = (result.metadata?.execution as { error?: string } | undefined) ?? undefined;
                const mode = result.metadata?.retrieval_mode as string | undefined;
                return (
                  <div className="rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-900/15 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
                    {result.execution_status === "degraded" ? (
                      <>
                        This case ran against <span className="font-medium">degraded retrieval</span>
                        {mode ? ` (${mode})` : ""}: the target fell back to keyword-only search after
                        its embeddings deployment throttled. It was not graded and is excluded from the
                        pass rate.
                      </>
                    ) : (
                      <>
                        This case <span className="font-medium">failed to run</span> after retries and
                        was not graded.{exec?.error ? ` Last error: ${exec.error}` : ""}
                      </>
                    )}
                  </div>
                );
              })()}
              {/* Filter Pre-conditions */}
              {(Array.isArray(result.metadata?.team_filter) || Array.isArray(result.metadata?.tag_filter) || result.metadata?.context_filters) ? (
                <Section title="Filter Pre-conditions" defaultOpen={false}>
                  <div className="flex flex-wrap gap-2">
                    {Array.isArray(result.metadata.team_filter) && (result.metadata.team_filter as string[]).length > 0 && (
                      <div className="px-2 py-1 rounded bg-blue-50 dark:bg-blue-900/20 text-sm text-blue-700 dark:text-blue-400">
                        Teams: {(result.metadata.team_filter as string[]).join(", ")}
                      </div>
                    )}
                    {Array.isArray(result.metadata.tag_filter) && (result.metadata.tag_filter as string[]).length > 0 && (
                      <div className="px-2 py-1 rounded bg-purple-50 dark:bg-purple-900/20 text-sm text-purple-700 dark:text-purple-400">
                        Tags: {(result.metadata.tag_filter as string[]).join(", ")}
                      </div>
                    )}
                    {result.metadata.context_filters != null && typeof result.metadata.context_filters === "object" && Object.keys(result.metadata.context_filters as object).length > 0 && (
                      <div className="px-2 py-1 rounded bg-gray-50 dark:bg-gray-800 text-sm text-gray-600 dark:text-gray-400">
                        Context filters: {JSON.stringify(result.metadata.context_filters)}
                      </div>
                    )}
                  </div>
                </Section>
              ) : null}

              {/* Multi-turn conversation timeline */}
              {conversationHistory.length > 1 ? (
                <Section title={`Conversation (${conversationHistory.length} turns)`}>
                  <div className="flex flex-col gap-3">
                    {conversationHistory.map((turn) => (
                      <div
                        key={turn.turn}
                        className={`rounded-lg border ${
                          turn.pass
                            ? "border-green-300 dark:border-green-700 bg-green-50/50 dark:bg-green-900/10"
                            : "border-gray-200 dark:border-slate-700"
                        }`}
                      >
                        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-slate-800">
                          <span className="text-sm font-medium text-gray-600 dark:text-slate-300">
                            Turn {turn.turn}
                          </span>
                          {turn.pass ? (
                            <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                              PASS
                            </span>
                          ) : turn.error ? (
                            <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
                              ERROR
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
                              FAIL
                            </span>
                          )}
                          {/* Per-turn grader summary */}
                          {Object.keys(turn.graders || {}).length > 0 && (
                            <span className="text-xs text-gray-400 dark:text-slate-500 ml-auto">
                              {Object.values(turn.graders).filter((g) => g.pass).length}/{Object.values(turn.graders).filter((g) => !g.skipped).length} graders passed
                            </span>
                          )}
                        </div>
                        <div className="p-3 space-y-2">
                          <div>
                            <p className="text-xs text-gray-400 dark:text-slate-500 mb-0.5">Prompt</p>
                            <div className="p-2 rounded bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 text-sm whitespace-pre-wrap max-h-32 overflow-y-auto">
                              {turn.prompt}
                            </div>
                          </div>
                          {turn.response && (
                            <div>
                              <p className="text-xs text-gray-400 dark:text-slate-500 mb-0.5">Response</p>
                              <ExpandableBox className="text-sm whitespace-pre-wrap">
                                {turn.response}
                              </ExpandableBox>
                            </div>
                          )}
                          {turn.error && (
                            <div className="p-2 rounded bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 text-sm text-red-600 dark:text-red-400">
                              {turn.error}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              ) : (
                <>
                  {/* Input */}
                  {result.input && (
                    <Section title="Input">
                      <div className="relative group/box">
                        <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 whitespace-pre-wrap max-h-40 overflow-y-auto">
                          {result.input}
                        </div>
                        <CopyButton
                          getText={() => result.input!}
                          className="absolute top-2 right-2 opacity-0 group-hover/box:opacity-100 p-1 rounded bg-gray-100 dark:bg-slate-800"
                        />
                      </div>
                    </Section>
                  )}
                </>
              )}

              {/* Expected Output + Output side by side */}
              <Section
                title="Expected Output / Actual Output"
                trailing={
                  !result.pass && result.output && result.expected_output ? (
                    <span className="text-sm text-red-500 dark:text-red-400 font-normal">
                      missing content highlighted
                    </span>
                  ) : undefined
                }
              >
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {result.expected_output && (
                    <div>
                      <p className="text-sm text-gray-400 dark:text-slate-500 mb-1">Expected</p>
                      <ExpandableBox className="text-base leading-relaxed">
                        {!result.pass && result.output ? (
                          <ExpectedOutputDiff
                            expected={result.expected_output}
                            actual={result.output}
                          />
                        ) : (
                          <p className="whitespace-pre-wrap">{result.expected_output}</p>
                        )}
                      </ExpandableBox>
                    </div>
                  )}
                  {result.output && (
                    <div>
                      <p className="text-sm text-gray-400 dark:text-slate-500 mb-1">Actual</p>
                      <ExpandableBox className="whitespace-pre-wrap">
                        {result.output}
                      </ExpandableBox>
                    </div>
                  )}
                </div>
              </Section>

              {/* Prompt + token usage for the generation call */}
              {(targetUsage || modelContext || modelPrompt) && (
                <Section
                  title="Model prompt & tokens"
                  defaultOpen={false}
                  trailing={
                    targetUsage ? (
                      <span className="text-sm font-normal text-gray-500 dark:text-slate-400">
                        {targetUsage.prompt_tokens.toLocaleString()} in / {targetUsage.completion_tokens.toLocaleString()} out tokens
                      </span>
                    ) : undefined
                  }
                >
                  {targetUsage && (
                    <div className="flex flex-wrap gap-2 mb-3 text-sm">
                      <span className="px-2 py-1 rounded bg-gray-100 dark:bg-slate-800">
                        Input: <span className="font-medium">{targetUsage.prompt_tokens.toLocaleString()}</span> tokens
                      </span>
                      <span className="px-2 py-1 rounded bg-gray-100 dark:bg-slate-800">
                        Output: <span className="font-medium">{targetUsage.completion_tokens.toLocaleString()}</span> tokens
                      </span>
                      <span className="px-2 py-1 rounded bg-gray-100 dark:bg-slate-800">
                        Total: <span className="font-medium">{targetUsage.total_tokens.toLocaleString()}</span> tokens
                      </span>
                    </div>
                  )}
                  {modelPrompt ? (
                    <div className="flex flex-col gap-3">
                      <p className="text-xs text-gray-400 dark:text-slate-500">
                        The literal prompt the model received (image parts elided). Retrieved
                        context is embedded in the last user turn.
                      </p>
                      {modelPrompt.system && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">System</p>
                          <ExpandableBox className="whitespace-pre-wrap text-sm font-mono">
                            {modelPrompt.system}
                          </ExpandableBox>
                        </div>
                      )}
                      {(modelPrompt.messages ?? []).map((m, i) => (
                        <div key={i}>
                          <p className="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1 capitalize">
                            {m.role || "message"}
                          </p>
                          <ExpandableBox className="whitespace-pre-wrap text-sm font-mono">
                            {m.content}
                          </ExpandableBox>
                        </div>
                      ))}
                    </div>
                  ) : modelContext ? (
                    <>
                      <p className="text-xs text-gray-400 dark:text-slate-500 mb-1">
                        Context block fed into the generation prompt (the bulk of the input tokens).
                        This target does not return its system prompt, so only the context is shown.
                      </p>
                      <ExpandableBox className="whitespace-pre-wrap text-sm font-mono">
                        {modelContext}
                      </ExpandableBox>
                    </>
                  ) : (
                    <p className="text-sm text-gray-400 dark:text-slate-500">
                      The target did not return the prompt for this call.
                    </p>
                  )}
                </Section>
              )}

              {/* Retrieval Context / Raw API Response */}
              {typeof result.metadata?.retrieval_context === "string" ? (
                <Section title="Retrieval Context" defaultOpen={false}>
                  <ExpandableBox className="whitespace-pre-wrap text-sm">
                    {result.metadata.retrieval_context}
                  </ExpandableBox>
                </Section>
              ) : typeof result.metadata?.raw_response === "string" && (
                <Section title="Context (raw API response)" defaultOpen={false}>
                  <ExpandableBox className="whitespace-pre-wrap text-sm font-mono">
                    {(() => {
                      try {
                        return JSON.stringify(JSON.parse(result.metadata.raw_response as string), null, 2);
                      } catch {
                        return result.metadata.raw_response as string;
                      }
                    })()}
                  </ExpandableBox>
                </Section>
              )}

              {result.reason && (
                <Section title="Full Reason" defaultOpen={false}>
                  <div className="relative group/box">
                    <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 whitespace-pre-wrap max-h-40 overflow-y-auto">
                      {result.reason}
                    </div>
                    <CopyButton
                      getText={() => result.reason!}
                      className="absolute top-2 right-2 opacity-0 group-hover/box:opacity-100 p-1 rounded bg-gray-100 dark:bg-slate-800"
                    />
                  </div>
                </Section>
              )}

              {/* Root Cause */}
              {(() => {
                const rc = result.metadata?.root_cause as RootCauseDetail | undefined;
                const style = rc ? rootCauseStyle(rc.category) : null;
                if (!rc || !style) return null;
                return (
                  <Section title="Root Cause">
                    <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 flex flex-col gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`inline-block px-2 py-0.5 rounded text-sm font-medium ${style.badge}`}>
                          {style.label}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-slate-500">
                          {rc.confidence} confidence · {rc.source === "llm" ? "LLM-judged" : "from graders"}
                        </span>
                      </div>
                      {rc.evidence && (
                        <p className="text-sm text-gray-700 dark:text-slate-300">{rc.evidence}</p>
                      )}
                      {rc.category === "indeterminate" &&
                        rc.evidence?.includes("No retrieval context captured") && (
                          <a
                            href="/settings?tab=project"
                            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
                          >
                            Detect retrieval field in Settings →
                          </a>
                        )}
                      {rc.missing_facts && rc.missing_facts.length > 0 && (
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-1">
                            Missing from retrieved context
                          </p>
                          <ul className="list-disc list-inside text-sm text-gray-700 dark:text-slate-300">
                            {rc.missing_facts.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </Section>
                );
              })()}

              {/* Grader Details */}
              {graderEntries.length > 0 && (
                <Section title="Grader Details">
                  <div className="flex flex-col gap-3">
                    {critical.length > 0 && (
                      <div>
                        <p className="text-sm font-medium uppercase tracking-wider text-red-500 dark:text-red-400 mb-1.5">
                          Critical — affects pass/fail
                        </p>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {critical.map(([name, g]) => (
                            <GraderResultCard
                              key={name}
                              name={name}
                              grader={g}
                              evaluatorMap={evaluatorMap}
                              disabledGraders={disabledGraders}
                              datasetId={datasetId}
                              testId={result.test_id}
                              canEdit={canEditExpectedUrls}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                    {other.length > 0 && (
                      <div>
                        {critical.length > 0 && (
                          <p className="text-sm font-medium uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-1.5">
                            Other graders
                          </p>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {other.map(([name, g]) => (
                            <GraderResultCard
                              key={name}
                              name={name}
                              grader={g}
                              evaluatorMap={evaluatorMap}
                              disabledGraders={disabledGraders}
                              datasetId={datasetId}
                              testId={result.test_id}
                              canEdit={canEditExpectedUrls}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                    {passedCount > 0 && (
                      <button
                        onClick={() => setShowPassed(prev => !prev)}
                        className="text-sm text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors text-left"
                      >
                        {showPassed
                          ? "Hide passed"
                          : `Show ${passedCount} passed`}
                      </button>
                    )}
                  </div>
                </Section>
              )}

              {/* Scores */}
              {Object.keys(result.scores || {}).length > 0 && (
                <Section title="Scores">
                  <div className="flex gap-3 flex-wrap">
                    {Object.entries(result.scores).map(([name, val]) => (
                      <div key={name} className="px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
                        <span className="text-gray-500 dark:text-slate-400" title={name}>{formatScoreLabel(name)}: </span>
                        <span className="font-medium">{formatScoreValue(name, val)}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
