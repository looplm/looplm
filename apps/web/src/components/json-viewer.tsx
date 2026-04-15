"use client";

import { useState, useRef, useEffect } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import Markdown from "react-markdown";

interface JsonViewerProps {
    data: any;
    title?: string;
    initialExpanded?: boolean;
}

type ViewMode = "raw" | "formatted";

const URL_REGEX = /^https?:\/\/.+/;

function isPlainValue(v: any): boolean {
    return v === null || v === undefined || typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

/** Render a single value nicely. */
function FormattedValue({ value, depth }: { value: any; depth: number }) {
    if (value === null || value === undefined) {
        return <span className="text-gray-400 dark:text-slate-500 italic">—</span>;
    }
    if (typeof value === "boolean") {
        return <span className={value ? "text-green-400" : "text-red-400"}>{value ? "true" : "false"}</span>;
    }
    if (typeof value === "number") {
        return <span className="text-amber-300">{value}</span>;
    }
    if (typeof value === "string") {
        if (URL_REGEX.test(value)) {
            const decoded = decodeURIComponent(value);
            const label = decoded.length > 80 ? decoded.slice(0, 77) + "…" : decoded;
            return (
                <a href={value} target="_blank" rel="noopener noreferrer" className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300 underline break-all text-xs">
                    {label}
                </a>
            );
        }
        // If string looks like it has markdown (newlines, headers, lists, bold)
        if (/[\n]|^#{1,6}\s|^\s*[-*]\s|\*\*.+\*\*/.test(value)) {
            return (
                <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-1 prose-code:text-indigo-600 dark:prose-code:text-indigo-300">
                    <Markdown>{value}</Markdown>
                </div>
            );
        }
        return <span className="text-gray-700 dark:text-slate-200 break-words">{value}</span>;
    }
    if (Array.isArray(value)) {
        return <FormattedArray items={value} depth={depth} />;
    }
    if (typeof value === "object") {
        return <FormattedObject data={value} depth={depth} />;
    }
    return <span className="text-gray-600 dark:text-slate-300">{String(value)}</span>;
}

/** Render an object as labeled fields. */
function FormattedObject({ data, depth }: { data: Record<string, any>; depth: number }) {
    const entries = Object.entries(data);
    if (entries.length === 0) return <span className="text-gray-400 dark:text-slate-500 italic">{"{ }"}</span>;

    return (
        <div className={`space-y-2 ${depth > 0 ? "pl-3 border-l border-gray-200/50 dark:border-slate-700/50" : ""}`}>
            {entries.map(([key, value]) => (
                <div key={key}>
                    <span className="text-[11px] font-medium text-gray-500 dark:text-slate-400">{key}</span>
                    <div className={isPlainValue(value) ? "mt-0.5" : "mt-1"}>
                        <FormattedValue value={value} depth={depth + 1} />
                    </div>
                </div>
            ))}
        </div>
    );
}

/** Render an array as a list of cards (objects) or values. */
function FormattedArray({ items, depth }: { items: any[]; depth: number }) {
    if (items.length === 0) return <span className="text-gray-400 dark:text-slate-500 italic">[ ]</span>;

    // Array of objects → render as cards
    const allObjects = items.every((item) => item && typeof item === "object" && !Array.isArray(item));
    if (allObjects) {
        return (
            <div className="space-y-2">
                {items.map((item, i) => (
                    <div key={i} className="rounded-lg bg-gray-100/40 dark:bg-slate-800/40 border border-gray-200/40 dark:border-slate-700/40 p-3">
                        <FormattedObject data={item} depth={depth + 1} />
                    </div>
                ))}
            </div>
        );
    }

    // Array of primitives → simple list
    return (
        <div className="space-y-1">
            {items.map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">{i + 1}.</span>
                    <FormattedValue value={item} depth={depth + 1} />
                </div>
            ))}
        </div>
    );
}

/** Check if data can be rendered in formatted view. */
function canFormat(data: any): boolean {
    if (data === null || data === undefined) return false;
    if (typeof data === "string") return true;
    if (typeof data === "object") return true;
    return false;
}

export default function JsonViewer({ data, title, initialExpanded = false }: JsonViewerProps) {
    const hasFormattedView = canFormat(data);

    const [expanded, setExpanded] = useState(initialExpanded);
    const [copied, setCopied] = useState(false);
    const [viewMode, setViewMode] = useState<ViewMode>(hasFormattedView ? "formatted" : "raw");
    const [overflows, setOverflows] = useState(false);
    const contentRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const el = contentRef.current;
        if (el) {
            setOverflows(el.scrollHeight > el.clientHeight);
        }
    }, [data, expanded, viewMode]);

    const handleCopy = () => {
        navigator.clipboard.writeText(JSON.stringify(data, null, 2));
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-gray-100/50 dark:bg-slate-800/50 border-b border-gray-100 dark:border-slate-800">
                <div className="flex items-center gap-2.5">
                    <span className="text-xs font-semibold text-gray-600 dark:text-slate-300">{title || "JSON"}</span>
                    {hasFormattedView && (<>
                        <span className="text-gray-300 dark:text-slate-600">·</span>
                        <div className="flex bg-gray-100 dark:bg-slate-800 rounded p-0.5">
                            <button
                                onClick={() => setViewMode("formatted")}
                                className={`cursor-pointer px-2 py-0.5 text-[10px] rounded transition-colors ${viewMode === "formatted" ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
                                title="Show formatted view"
                            >
                                Formatted
                            </button>
                            <button
                                onClick={() => setViewMode("raw")}
                                className={`cursor-pointer px-2 py-0.5 text-[10px] rounded transition-colors ${viewMode === "raw" ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"}`}
                                title="Show raw JSON"
                            >
                                Raw
                            </button>
                        </div>
                    </>)}
                </div>
                <div className="flex items-center gap-1">
                    <button
                        onClick={handleCopy}
                        className="cursor-pointer p-1 text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-colors"
                        title={copied ? "Copied!" : "Copy to clipboard"}
                    >
                        {copied ? (
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                        ) : (
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" /></svg>
                        )}
                    </button>
                    {(expanded || overflows) && (
                        <button
                            onClick={() => setExpanded(!expanded)}
                            className="cursor-pointer p-1 text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white transition-colors"
                            title={expanded ? "Collapse to preview" : "Expand to full size"}
                        >
                            {expanded ? (
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 14h6m0 0v6m0-6L3 21M20 10h-6m0 0V4m0 6l7-7" /></svg>
                            ) : (
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M14 4h6m0 0v6m0-6L13 11M10 20H4m0 0v-6m0 6l7-7" /></svg>
                            )}
                        </button>
                    )}
                </div>
            </div>
            <div ref={contentRef} className={`overflow-y-auto overflow-x-hidden ${expanded ? "max-h-[32rem]" : "max-h-48"}`}>
                {viewMode === "formatted" ? (
                    <div className="p-4 text-sm">
                        <FormattedValue value={data} depth={0} />
                    </div>
                ) : (
                    <SyntaxHighlighter
                        language="json"
                        style={vscDarkPlus}
                        wrapLongLines
                        customStyle={{ margin: 0, padding: "1rem", fontSize: "0.75rem", backgroundColor: "transparent", whiteSpace: "pre-wrap", wordBreak: "break-all", overflowWrap: "break-word", overflow: "visible" }}
                        codeTagProps={{ style: { whiteSpace: "pre-wrap", wordBreak: "break-all", overflowWrap: "break-word" } }}
                    >
                        {JSON.stringify(data, null, 2)}
                    </SyntaxHighlighter>
                )}
            </div>
        </div>
    );
}
