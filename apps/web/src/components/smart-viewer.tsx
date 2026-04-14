"use client";

import { useState } from "react";
import JsonViewer from "./json-viewer";

interface Message {
    id?: string;
    type: string;
    content: string;
    name?: string;
    tool_calls?: any[];
    usage_metadata?: any;
    response_metadata?: any;
}

interface SmartViewerProps {
    data: any;
    title?: string;
}

function ChatBubble({ message }: { message: Message }) {
    const isUser = message.type === "human" || message.type === "user";
    const isSystem = message.type === "system";
    const isAi = message.type === "ai" || message.type === "assistant";

    let bgClass = "bg-gray-100 dark:bg-slate-800";
    let alignClass = "items-start";
    let label = message.type;

    if (isUser) {
        bgClass = "bg-indigo-900/30 border border-indigo-800/50";
        alignClass = "items-end";
        label = "User";
    } else if (isSystem) {
        bgClass = "bg-gray-100/50 dark:bg-slate-800/50 border border-gray-200/50 dark:border-slate-700/50 dashed border-2";
        alignClass = "items-center";
        label = "System";
    } else if (isAi) {
        bgClass = "bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700";
        alignClass = "items-start";
        label = "AI";
    }

    return (
        <div className={`flex flex-col ${alignClass} mb-4 max-w-full`}>
            <span className="text-xs text-gray-400 dark:text-slate-500 mb-1 capitalize">{label}</span>
            <div className={`rounded-lg p-3 max-w-[90%] ${bgClass} overflow-x-auto`}>
                <p className="text-sm text-gray-700 dark:text-slate-200 whitespace-pre-wrap">{message.content}</p>

                {/* Metadata section (e.g. usage) */}
                {message.usage_metadata && (
                    <div className="mt-2 pt-2 border-t border-gray-200/50 dark:border-slate-700/50 text-[10px] text-gray-400 dark:text-slate-500 flex gap-3">
                        <span>In: {message.usage_metadata.input_tokens}</span>
                        <span>Out: {message.usage_metadata.output_tokens}</span>
                        <span>Total: {message.usage_metadata.total_tokens}</span>
                    </div>
                )}
            </div>
        </div>
    );
}

export default function SmartViewer({ data, title }: SmartViewerProps) {
    // Simple heuristic to detect chat structure
    const isChat =
        data &&
        typeof data === "object" &&
        Array.isArray(data.main_messages) &&
        data.main_messages.length > 0 &&
        data.main_messages.every((m: any) => typeof m.content === "string" && typeof m.type === "string");

    const [viewMode, setViewMode] = useState<"preview" | "json">(isChat ? "preview" : "json");

    // If it's not detected as chat, force JSON view and hide toggle
    if (!isChat) {
        return <JsonViewer data={data} title={title} />;
    }

    return (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-gray-100/50 dark:bg-slate-800/50 border-b border-gray-100 dark:border-slate-800">
                <div className="flex items-center gap-3">
                    <span className="text-xs font-medium text-gray-500 dark:text-slate-400">{title || "Output"}</span>
                    <div className="flex bg-gray-100 dark:bg-slate-800 rounded p-0.5">
                        <button
                            onClick={() => setViewMode("preview")}
                            className={`px-2 py-0.5 text-[10px] rounded ${viewMode === "preview" ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
                        >
                            Preview
                        </button>
                        <button
                            onClick={() => setViewMode("json")}
                            className={`px-2 py-0.5 text-[10px] rounded ${viewMode === "json" ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
                        >
                            JSON
                        </button>
                    </div>
                </div>
            </div>

            {viewMode === "json" ? (
                // Render JsonViewer WITHOUT its header (we implemented our own header above)
                // However, JsonViewer has its own internal header.
                // Ideally we refactor JsonViewer, but for now we can arguably just render it "inside".
                // Actually, JsonViewer renders a full card.
                // Let's just use the JsonViewer directly but maybe pass a prop to hide header?
                // Or better: Just switch entirely.
                <div className="-mt-px">
                    {/* Hack: Negative margin to overlap borders if we were adjacent, but we are inside. */}
                    {/* To reuse JsonViewer logic without double header, we might want to strip JsonViewer's container. */}
                    {/* For this iteration, let's just render JsonViewer as is, it will have a second header. acceptable for MVP or we refactor. */}
                    {/* Wait, if I return JsonViewer, it has the standard header. */}
                    {/* If I use SmartViewer header, I should probably pass 'data' to syntax highlighter directly here or refactor JsonViewer. */}
                    {/* Let's refactor JsonViewer to accept a 'hideHeader' prop? Or just render it. A nested header is okay-ish for "Raw JSON". */}
                    <JsonViewer data={data} title="Raw JSON" initialExpanded={true} />
                </div>
            ) : (
                <div className="p-4 bg-white/50 dark:bg-slate-900/50 max-h-[500px] overflow-y-auto space-y-2">
                    {data.main_messages.map((msg: Message, idx: number) => (
                        <ChatBubble key={msg.id || idx} message={msg} />
                    ))}
                </div>
            )}
        </div>
    );
}
