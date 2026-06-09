"use client";

import { useEffect, useState, lazy, Suspense } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { getTrace, getTraceAnalysis, triggerAnalysis, applyFix, getTraceChildren, getTraceFeedback, type TraceDetail, type TraceAnalysis, type SpanNode, type TraceTreeNode, type TraceFeedbackScore } from "@/lib/api";
import StatusBadge from "@/components/status-badge";
import { formatDuration } from "@/lib/format";

import SmartViewer from "@/components/smart-viewer";
import ThreadConversation from "@/components/thread-conversation";

const TraceGraph = lazy(() => import("@/components/trace-graph"));

type ChildViewMode = "tree" | "graph";

const RUN_TYPE_COLORS: Record<string, string> = {
  llm: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  tool: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  retriever: "bg-green-500/20 text-green-300 border-green-500/30",
  chain: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  agent: "bg-orange-500/20 text-orange-300 border-orange-500/30",
};

function RunTypeBadge({ runType }: { runType?: string }) {
  if (!runType) return null;
  const colors = RUN_TYPE_COLORS[runType] || "bg-slate-500/20 text-slate-300 border-slate-500/30";
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${colors}`}>
      {runType}
    </span>
  );
}

function ErrorBlock({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div className="mb-8 p-4 bg-red-500/10 border border-red-500/20 rounded-xl">
      <p className="text-sm font-medium text-red-400 mb-1">Error</p>
      <p className="text-sm text-red-300">{message}</p>
    </div>
  );
}

function ChildRunTree({ nodes, depth = 0 }: { nodes: TraceTreeNode[]; depth?: number }) {
  return (
    <div className={depth > 0 ? "ml-6 border-l border-gray-200 dark:border-slate-700 pl-4" : ""}>
      {nodes.map((node) => (
        <div key={node.id} className="mb-3">
          <div className="flex items-center gap-3 py-1">
            <RunTypeBadge runType={node.run_type ?? undefined} />
            <Link href={`/traces/${node.id}`} className="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline">
              {node.name || "unnamed"}
            </Link>
            <StatusBadge status={node.status || undefined} />
            {node.duration_ms != null && <span className="text-xs text-gray-500 dark:text-slate-400">{formatDuration(node.duration_ms)}</span>}
          </div>
          {(node.children?.length ?? 0) > 0 && <ChildRunTree nodes={node.children ?? []} depth={(depth || 0) + 1} />}
        </div>
      ))}
    </div>
  );
}

function SpanRow({ span }: { span: SpanNode }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = !!(span.input || span.output);

  return (
    <div className="mb-3">
      <div
        className={`flex items-center gap-3 py-1 ${hasDetail ? "cursor-pointer hover:bg-gray-100/50 dark:hover:bg-slate-800/50 rounded px-1 -mx-1" : ""}`}
        onClick={() => hasDetail && setExpanded(!expanded)}
      >
        {hasDetail && (
          <span className="text-xs text-gray-400 dark:text-slate-500 w-4 text-center">{expanded ? "▼" : "▶"}</span>
        )}
        <span className="text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-slate-800 rounded font-mono">{span.type || "span"}</span>
        <span className="text-sm font-medium">{span.name || "unnamed"}</span>
        <StatusBadge status={span.status || undefined} />
        {span.duration_ms && <span className="text-xs text-gray-500 dark:text-slate-400">{formatDuration(span.duration_ms)}</span>}
        {span.model && <span className="text-xs text-gray-400 dark:text-slate-500">{span.model}</span>}
        {(span.tokens_in || span.tokens_out) && (
          <span className="text-xs text-gray-400 dark:text-slate-500">
            {span.tokens_in || 0}→{span.tokens_out || 0} tokens
          </span>
        )}
      </div>
      {span.error_message && (
        <p className="text-xs text-red-400 ml-8 mt-1">{span.error_message}</p>
      )}
      {expanded && (
        <div className="mt-2 ml-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {!!span.input && <SmartViewer data={span.input as any} title="Input" />}
          {!!span.output && <SmartViewer data={span.output as any} title="Output" />}
        </div>
      )}
    </div>
  );
}

function SpanTree({ spans, depth = 0 }: { spans: SpanNode[]; depth?: number }) {
  return (
    <div className={depth > 0 ? "ml-6 border-l border-gray-200 dark:border-slate-700 pl-4" : ""}>
      {spans.map((span) => (
        <div key={span.id}>
          <SpanRow span={span} />
          {(span.children?.length ?? 0) > 0 && <SpanTree spans={span.children ?? []} depth={depth + 1} />}
        </div>
      ))}
    </div>
  );
}

export default function TraceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [analysis, setAnalysis] = useState<TraceAnalysis | null>(null);
  const [childNodes, setChildNodes] = useState<TraceTreeNode[] | null>(null);
  const [childViewMode, setChildViewMode] = useState<ChildViewMode>("tree");
  const [feedback, setFeedback] = useState<TraceFeedbackScore[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTrace(id).then((t) => {
      setTrace(t);
      if (t.child_run_count > 0) {
        getTraceChildren(id).then((r) => setChildNodes(r.children ?? [])).catch(() => {});
      }
    }).catch((e) => setError(e.message));
    getTraceAnalysis(id).then(setAnalysis).catch(() => { });
    getTraceFeedback(id).then(setFeedback).catch(() => {});
  }, [id]);

  const handleAnalyze = async () => {
    try {
      await triggerAnalysis(id);
      // Reload analysis after a brief delay
      setTimeout(() => getTraceAnalysis(id).then(setAnalysis).catch(() => { }), 1000);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleApplyFix = async (fixId: string) => {
    try {
      await applyFix(fixId);
      getTraceAnalysis(id).then(setAnalysis).catch(() => { });
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (error && !trace) {
    return <div className="text-red-400">Error: {error}</div>;
  }
  if (!trace) return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <button onClick={() => router.back()} className="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white">&larr; Back</button>
        {trace.root_trace_id && (
          <>
            <span className="text-gray-300 dark:text-slate-600">|</span>
            <Link href={`/traces/${trace.root_trace_id}`} className="text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300">
              &larr; Back to root run
            </Link>
          </>
        )}
      </div>

      <div className="flex items-center gap-4 mb-8">
        <h1 className="text-2xl font-bold">{trace.name || trace.external_id}</h1>
        <RunTypeBadge runType={trace.run_type ?? undefined} />
        <StatusBadge status={trace.status || undefined} />
        {trace.duration_ms && <span className="text-gray-500 dark:text-slate-400">{formatDuration(trace.duration_ms)}</span>}
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">External ID</p>
          <p className="text-sm font-mono">{trace.external_id}</p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">User ID</p>
          <p className="text-sm font-mono">{trace.user_id || "—"}</p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">Start Time</p>
          <p className="text-sm">{new Date(trace.start_time).toLocaleString()}</p>
        </div>
        <div className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
          <p className="text-xs text-gray-500 dark:text-slate-400 mb-1">End Time</p>
          <p className="text-sm">
            {trace.end_time
              ? new Date(trace.end_time).toLocaleString()
              : trace.duration_ms
                ? new Date(new Date(trace.start_time).getTime() + trace.duration_ms).toLocaleString()
                : "—"}
          </p>
        </div>
      </div>

      {/* Trace Metadata */}
      {trace.metadata && Object.keys(trace.metadata).length > 0 && (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
          <h2 className="text-lg font-semibold mb-4">Metadata</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {Object.entries(trace.metadata).map(([key, value]) => {
              const display = typeof value === "object" ? JSON.stringify(value) : String(value);
              return (
                <div key={key} className="min-w-0">
                  <p className="text-xs text-gray-500 dark:text-slate-400 mb-1 truncate">{key}</p>
                  <p className="text-sm font-mono overflow-x-auto whitespace-nowrap" title={display}>
                    {typeof value === "boolean" ? (
                      <span className={value ? "text-green-400" : "text-red-400"}>{display}</span>
                    ) : (
                      display
                    )}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {trace.thread_id && (
        <ThreadConversation
          threadId={trace.thread_id}
          currentTraceId={trace.id}
          currentTraceStartTime={trace.start_time}
        />
      )}

      <ErrorBlock message={trace.error_message} />

      {/* Input/Output */}
      {(!!trace.input || !!trace.output) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {!!trace.input && (
            <SmartViewer data={trace.input as any} title="Input" />
          )}
          {!!trace.output && (
            <SmartViewer data={trace.output as any} title="Output" />
          )}
        </div>
      )}

      {/* Span Tree */}
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">Span Tree</h2>
        {(trace.spans?.length ?? 0) === 0 ? (
          <p className="text-gray-500 dark:text-slate-400 text-sm">No spans recorded.</p>
        ) : (
          <SpanTree spans={trace.spans ?? []} />
        )}
      </div>

      {/* Feedback */}
      {feedback.length > 0 && (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
          <h2 className="text-lg font-semibold mb-4">Feedback ({feedback.length})</h2>
          <div className="space-y-3">
            {feedback.map((fb) => (
              <div key={fb.id} className="flex items-start gap-4 py-2 border-b border-gray-100/50 dark:border-slate-800/50 last:border-0">
                <span className="text-lg">
                  {fb.score_name === "user-feedback" ? (
                    fb.value === 1 ? "👍" : "👎"
                  ) : (
                    <span className={fb.value === 1 ? "text-green-400" : "text-red-400"}>
                      {fb.value === 1 ? "✓" : "✗"}
                    </span>
                  )}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-slate-800 rounded text-gray-600 dark:text-slate-300">
                      {fb.score_name}
                    </span>
                    {fb.scored_at && (
                      <span className="text-xs text-gray-400 dark:text-slate-500">
                        {new Date(fb.scored_at).toLocaleString("de-DE", {
                          day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                        })}
                      </span>
                    )}
                  </div>
                  {fb.comment && <p className="text-sm text-gray-500 dark:text-slate-400">{fb.comment}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Child Runs */}
      {trace.child_run_count > 0 && (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Child Runs ({trace.child_run_count})</h2>
            <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
              <button
                onClick={() => setChildViewMode("tree")}
                className={`px-3 py-1 text-xs ${childViewMode === "tree" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
              >
                Tree
              </button>
              <button
                onClick={() => setChildViewMode("graph")}
                className={`px-3 py-1 text-xs ${childViewMode === "graph" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
              >
                Graph
              </button>
            </div>
          </div>
          {childNodes === null ? (
            <p className="text-gray-500 dark:text-slate-400 text-sm">Loading child runs...</p>
          ) : childNodes.length === 0 ? (
            <p className="text-gray-500 dark:text-slate-400 text-sm">No child runs found.</p>
          ) : childViewMode === "tree" ? (
            <ChildRunTree nodes={childNodes} />
          ) : (
            <Suspense fallback={<p className="text-slate-400 text-sm">Loading graph...</p>}>
              <TraceGraph trace={trace} childNodes={childNodes} />
            </Suspense>
          )}
        </div>
      )}

      {/* Analysis */}
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Analysis & Fix Suggestions</h2>
          {!analysis && (
            <button onClick={handleAnalyze} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white">
              Analyze Trace
            </button>
          )}
        </div>

        {analysis ? (
          <div>
            <div className="mb-6 p-4 bg-gray-100/50 dark:bg-slate-800/50 rounded-lg">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-sm font-medium">Failure Type:</span>
                <StatusBadge status={analysis.analysis.failure_type || "unknown"} />
                {analysis.analysis.confidence && (
                  <span className="text-xs text-gray-500 dark:text-slate-400">Confidence: {(analysis.analysis.confidence * 100).toFixed(0)}%</span>
                )}
              </div>
              {analysis.analysis.root_cause && (
                <p className="text-sm text-gray-600 dark:text-slate-300 mt-2">{analysis.analysis.root_cause}</p>
              )}
            </div>

            {analysis.fix_suggestions.length > 0 && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-gray-500 dark:text-slate-400">Fix Suggestions</h3>
                {analysis.fix_suggestions.map((fix) => (
                  <div key={fix.id} className="p-4 bg-gray-100/50 dark:bg-slate-800/50 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-xs px-1.5 py-0.5 bg-gray-200 dark:bg-slate-700 rounded">{fix.type}</span>
                        <span className="text-sm font-medium">{fix.title}</span>
                        <StatusBadge status={fix.status} />
                      </div>
                      {fix.status === "pending" && (
                        <button onClick={() => handleApplyFix(fix.id)} className="px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-xs font-medium">
                          Apply
                        </button>
                      )}
                    </div>
                    {fix.description && <p className="text-sm text-gray-500 dark:text-slate-400">{fix.description}</p>}
                    {fix.diff != null && (
                      <pre className="mt-2 text-xs bg-gray-50 dark:bg-slate-900 p-2 rounded overflow-auto">{JSON.stringify(fix.diff, null, 2)}</pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-gray-500 dark:text-slate-400 text-sm">No analysis available. Click &quot;Analyze Trace&quot; to generate one.</p>
        )}
      </div>
    </div>
  );
}
