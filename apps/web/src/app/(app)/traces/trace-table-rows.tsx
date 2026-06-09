"use client";

import { useState } from "react";
import Link from "next/link";
import {
  getTraceChildren,
  type TraceListItem,
  type ThreadSummary,
  type TraceTreeNode,
} from "@/lib/api";
import StatusBadge from "@/components/status-badge";
import Tooltip from "@/components/tooltip";
import { formatDuration } from "@/lib/format";

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

export function formatInputPreview(input: any): string {
  if (!input) return "\u2014";
  try {
    if (typeof input === "string") {
      try {
        input = JSON.parse(input);
      } catch {
        return input;
      }
    }

    if (typeof input !== "object") return String(input);

    if (Array.isArray(input.main_messages) && input.main_messages.length > 0) {
      const msg = input.main_messages[0];
      if (msg.content) return typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content);
    }

    if (input.input) return typeof input.input === "string" ? input.input : JSON.stringify(input.input);

    if (Array.isArray(input.messages) && input.messages.length > 0) {
      const first = input.messages[0];
      if (first.content) return typeof first.content === "string" ? first.content : JSON.stringify(first.content);
    }

    return JSON.stringify(input);
  } catch (e) {
    return JSON.stringify(input);
  }
}

export function TraceRow({ t, widths }: { t: TraceListItem; widths: any }) {
  return (
    <tr className="border-b border-gray-100 dark:border-slate-800 hover:bg-gray-100/50 dark:hover:bg-slate-800/50">
      <td className="py-3 px-4 truncate" style={{ width: widths.name }}>
        <Link href={`/traces/${t.id}`} className="text-indigo-600 dark:text-indigo-400 hover:underline">
          {t.name || t.external_id}
        </Link>
      </td>
      <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.thread }}>
        <Tooltip content={t.thread_id || ""}>
          <span>{t.thread_id || "\u2014"}</span>
        </Tooltip>
      </td>
      <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.user }}>
        <Tooltip content={t.user_id || ""}>
          <span>{t.user_id || "\u2014"}</span>
        </Tooltip>
      </td>
      <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.input }}>
        <Tooltip content={formatInputPreview(t.input)}>
          <div className="truncate cursor-default px-1 rounded hover:bg-gray-100/50 dark:hover:bg-slate-800/50">
            {formatInputPreview(t.input).slice(0, 80) + (formatInputPreview(t.input).length > 80 ? "..." : "")}
          </div>
        </Tooltip>
      </td>
      <td className="py-3 px-4" style={{ width: widths.status }}><StatusBadge status={t.status || undefined} /></td>
      <td className="text-right py-3 px-4 text-gray-500 dark:text-slate-400" style={{ width: widths.duration }}>{t.duration_ms ? formatDuration(t.duration_ms) : "\u2014"}</td>
      <td className="py-3 px-4 text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.time }}>{new Date(t.start_time).toLocaleString()}</td>
      <td className="py-3 px-4 text-red-400 text-xs truncate" style={{ width: widths.error }}>
        <Tooltip content={t.error_message || ""}>
          <span>{t.error_message || ""}</span>
        </Tooltip>
      </td>
    </tr>
  );
}

export function ThreadGroup({ thread, widths }: { thread: ThreadSummary; widths: any }) {
  const [expanded, setExpanded] = useState(false);
  const rootTrace = thread.traces?.[0];
  const childTraces = thread.traces?.slice(1) ?? [];

  if (!rootTrace) return null;

  return (
    <>
      <tr
        className="border-b border-gray-100 dark:border-slate-800 hover:bg-gray-100/50 dark:hover:bg-slate-800/50 cursor-pointer group"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="py-3 px-4 truncate" style={{ width: widths.name }}>
          <div className="flex items-center">
            <button
              className={`w-4 h-4 mr-2 flex items-center justify-center text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-transform ${childTraces.length === 0 ? "invisible" : ""} ${expanded ? "rotate-90" : ""}`}
            >
              &#9654;
            </button>
            <Link href={`/traces/${rootTrace.id}`} className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline truncate max-w-[200px]" onClick={(e) => e.stopPropagation()}>
              {rootTrace.name || rootTrace.external_id || thread.thread_id}
            </Link>
            {childTraces.length > 0 && (
              <span className="ml-2 px-1.5 py-0.5 text-[10px] rounded-full bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 border border-gray-200 dark:border-slate-700">
                {childTraces.length}
              </span>
            )}
          </div>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.thread }}>
          <Tooltip content={thread.thread_id}>
            <span>{thread.thread_id}</span>
          </Tooltip>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.user }}>
          <Tooltip content={rootTrace.user_id || ""}>
            <span>{rootTrace.user_id || "\u2014"}</span>
          </Tooltip>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.input }}>
          <Tooltip content={formatInputPreview(rootTrace.input)}>
            <div className="truncate cursor-default px-1 rounded hover:bg-gray-100/50 dark:hover:bg-slate-800/50">
              {formatInputPreview(rootTrace.input).slice(0, 80) + (formatInputPreview(rootTrace.input).length > 80 ? "..." : "")}
            </div>
          </Tooltip>
        </td>
        <td className="py-3 px-4" style={{ width: widths.status }}>
          <StatusBadge status={rootTrace.status || undefined} />
        </td>
        <td className="text-right py-3 px-4 text-gray-500 dark:text-slate-400" style={{ width: widths.duration }}>
          {rootTrace.duration_ms ? formatDuration(rootTrace.duration_ms) : "\u2014"}
        </td>
        <td className="py-3 px-4 text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.time }}>{new Date(rootTrace.start_time).toLocaleString()}</td>
        <td className="py-3 px-4 text-red-400 text-xs truncate" style={{ width: widths.error }}>
          <Tooltip content={rootTrace.error_message || ""}>
            <span>{rootTrace.error_message || ""}</span>
          </Tooltip>
        </td>
      </tr>
      {expanded && childTraces.map((t, idx) => (
        <tr key={t.id} className="border-b border-gray-100 dark:border-slate-800 bg-white/50 dark:bg-slate-900/30 hover:bg-gray-100/50 dark:hover:bg-slate-800/20">
          <td className="py-2 px-4 pl-12 relative truncate" style={{ width: widths.name }}>
            <div className="absolute left-7 top-0 bottom-0 border-l border-gray-100/50 dark:border-slate-800/50 w-px" />
            <div className="absolute left-7 top-1/2 w-3 border-t border-gray-100/50 dark:border-slate-800/50 h-px" />

            <Link href={`/traces/${t.id}`} className="text-indigo-600 dark:text-indigo-400 hover:underline text-sm ml-2">
              {t.name || t.external_id}
            </Link>
          </td>
          <td className="py-2 px-4 text-xs font-mono text-gray-400 dark:text-slate-500 truncate" style={{ width: widths.thread }}>
            <Tooltip content={t.thread_id || thread.thread_id}>
              <span className="opacity-50">&quot;</span>
            </Tooltip>
          </td>
          <td className="py-2 px-4 text-xs font-mono text-gray-400 dark:text-slate-500 truncate" style={{ width: widths.user }}>
            <Tooltip content={t.user_id || ""}>
              <span>{t.user_id || "\u2014"}</span>
            </Tooltip>
          </td>
          <td className="py-2 px-4 text-xs font-mono text-gray-400 dark:text-slate-500 truncate" style={{ width: widths.input }}>
            <Tooltip content={formatInputPreview(t.input)}>
              <div className="truncate cursor-default px-1 rounded hover:bg-gray-100/50 dark:hover:bg-slate-800/50">
                {formatInputPreview(t.input).slice(0, 80) + (formatInputPreview(t.input).length > 80 ? "..." : "")}
              </div>
            </Tooltip>
          </td>
          <td className="py-2 px-4" style={{ width: widths.status }}><StatusBadge status={t.status || undefined} /></td>
          <td className="text-right py-2 px-4 text-gray-500 dark:text-slate-400 text-sm" style={{ width: widths.duration }}>{t.duration_ms ? formatDuration(t.duration_ms) : "\u2014"}</td>
          <td className="py-2 px-4 text-gray-500 dark:text-slate-400 text-sm truncate" style={{ width: widths.time }}>{new Date(t.start_time).toLocaleString()}</td>
          <td className="py-2 px-4 text-red-400 text-xs truncate" style={{ width: widths.error }}>
            <Tooltip content={t.error_message || ""}>
              <span>{t.error_message || ""}</span>
            </Tooltip>
          </td>
        </tr>
      ))}
    </>
  );
}

function RunTreeNodes({ nodes, depth = 0 }: { nodes: TraceTreeNode[]; depth?: number }) {
  return (
    <>
      {nodes.map((node) => (
        <RunTreeNodeRow key={node.id} node={node} depth={depth} />
      ))}
    </>
  );
}

function RunTreeNodeRow({ node, depth }: { node: TraceTreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const paddingLeft = 20 + depth * 24;

  return (
    <>
      <tr className="border-b border-gray-100/50 dark:border-slate-800/50 bg-white/50 dark:bg-slate-900/30 hover:bg-gray-100/50 dark:hover:bg-slate-800/20">
        <td colSpan={8} className="py-2 px-4">
          <div className="flex items-center gap-2" style={{ paddingLeft }}>
            {depth > 0 && (
              <div className="absolute" style={{ left: paddingLeft - 12 }}>
                <div className="border-l border-gray-200/50 dark:border-slate-700/50 h-full absolute -top-2" />
                <div className="border-t border-gray-200/50 dark:border-slate-700/50 w-3 absolute top-1/2" />
              </div>
            )}
            {hasChildren ? (
              <button
                onClick={() => setExpanded(!expanded)}
                className={`w-4 h-4 flex items-center justify-center text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-transform text-xs ${expanded ? "rotate-90" : ""}`}
              >
                &#9654;
              </button>
            ) : (
              <span className="w-4 h-4 flex items-center justify-center text-gray-300 dark:text-slate-600 text-xs">&#9679;</span>
            )}
            <RunTypeBadge runType={node.run_type ?? undefined} />
            <Link href={`/traces/${node.id}`} className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline truncate max-w-[300px]">
              {node.name || "unnamed"}
            </Link>
            <StatusBadge status={node.status || undefined} />
            {node.duration_ms != null && (
              <span className="text-xs text-gray-400 dark:text-slate-500">{formatDuration(node.duration_ms)}</span>
            )}
            {hasChildren && (
              <span className="text-[10px] text-gray-400 dark:text-slate-500 px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700">
                {node.children?.length ?? 0}
              </span>
            )}
          </div>
        </td>
      </tr>
      {expanded && hasChildren && (
        <RunTreeNodes nodes={node.children ?? []} depth={depth + 1} />
      )}
    </>
  );
}

export function RunTreeGroup({ trace, widths }: { trace: TraceListItem; widths: any }) {
  const [expanded, setExpanded] = useState(false);
  const [childTree, setChildTree] = useState<TraceTreeNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const hasChildren = trace.child_run_count > 0;

  const handleExpand = () => {
    if (!hasChildren) return;
    if (!expanded && !childTree) {
      setLoading(true);
      getTraceChildren(trace.id)
        .then((r) => {
          setChildTree(r.children ?? []);
          setExpanded(true);
        })
        .catch(() => setChildTree([]))
        .finally(() => setLoading(false));
    } else {
      setExpanded(!expanded);
    }
  };

  return (
    <>
      <tr
        className={`border-b border-gray-100 dark:border-slate-800 hover:bg-gray-100/50 dark:hover:bg-slate-800/50 ${hasChildren ? "cursor-pointer" : ""} group`}
        onClick={handleExpand}
      >
        <td className="py-3 px-4 truncate" style={{ width: widths.name }}>
          <div className="flex items-center">
            {hasChildren ? (
              <button
                className={`w-4 h-4 mr-2 flex items-center justify-center text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-transform text-xs ${expanded ? "rotate-90" : ""}`}
              >
                {loading ? (
                  <span className="animate-spin">&#9696;</span>
                ) : (
                  <>&#9654;</>
                )}
              </button>
            ) : (
              <span className="w-4 h-4 mr-2" />
            )}
            <RunTypeBadge runType={trace.run_type ?? undefined} />
            <Link href={`/traces/${trace.id}`} className="ml-1 font-medium text-indigo-600 dark:text-indigo-400 hover:underline truncate max-w-[200px]" onClick={(e) => e.stopPropagation()}>
              {trace.name || trace.external_id}
            </Link>
          </div>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.thread }}>
          <Tooltip content={trace.thread_id || ""}>
            <span>{trace.thread_id || "\u2014"}</span>
          </Tooltip>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.user }}>
          <Tooltip content={trace.user_id || ""}>
            <span>{trace.user_id || "\u2014"}</span>
          </Tooltip>
        </td>
        <td className="py-3 px-4 text-xs font-mono text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.input }}>
          <Tooltip content={formatInputPreview(trace.input)}>
            <div className="truncate cursor-default px-1 rounded hover:bg-gray-100/50 dark:hover:bg-slate-800/50">
              {formatInputPreview(trace.input).slice(0, 80) + (formatInputPreview(trace.input).length > 80 ? "..." : "")}
            </div>
          </Tooltip>
        </td>
        <td className="py-3 px-4" style={{ width: widths.status }}>
          <StatusBadge status={trace.status || undefined} />
        </td>
        <td className="text-right py-3 px-4 text-gray-500 dark:text-slate-400" style={{ width: widths.duration }}>
          {trace.duration_ms ? formatDuration(trace.duration_ms) : "\u2014"}
        </td>
        <td className="py-3 px-4 text-gray-500 dark:text-slate-400 truncate" style={{ width: widths.time }}>{new Date(trace.start_time).toLocaleString()}</td>
        <td className="py-3 px-4 text-red-400 text-xs truncate" style={{ width: widths.error }}>
          <Tooltip content={trace.error_message || ""}>
            <span>{trace.error_message || ""}</span>
          </Tooltip>
        </td>
      </tr>
      {expanded && childTree && childTree.length > 0 && (
        <RunTreeNodes nodes={childTree} depth={0} />
      )}
    </>
  );
}
