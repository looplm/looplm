"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { Root, Element, ElementContent } from "hast";

// Chunks come out of the index as whatever the ingester produced: plain prose, Markdown, or raw
// HTML fragments (tables from scraped pages and Confluence exports are the common case). Reading
// `<td>` soup line by line is what a human reviewer has to do otherwise, so this renders the
// markup instead — Markdown + GFM tables, with raw HTML passed through a sanitizer.

// Chunk text is untrusted (it is whatever got indexed), so raw HTML goes through rehype-sanitize's
// GitHub schema: script tags, event handlers and javascript: URLs are dropped, while table
// structure (including colspan/rowspan) survives.

// Block-level HTML, or Markdown structure worth rendering (table pipes, headings, list bullets,
// bold). Plain prose fails this test and stays plain text — rendering it would only add noise.
const HTML_BLOCK = /<\/?(table|caption|thead|tbody|tr|t[dh]|figure|figcaption|ul|ol|li|p|div|h[1-6]|pre|code|br|strong|em|b|i|a|span|img)\b[^>]*>/i;
const MD_TABLE = /^\s*\|.*\|\s*$/m;
const MD_STRUCTURE = /^\s{0,3}#{1,6}\s|^\s{0,3}[-*+]\s|^\s{0,3}\d+\.\s|\*\*[^*\n]+\*\*|^\s{0,3}>\s/m;

/** Whether rendering this text as HTML/Markdown would show the reviewer anything extra. */
export function isRenderable(text: string | null | undefined): boolean {
  if (!text) return false;
  return HTML_BLOCK.test(text) || MD_TABLE.test(text) || MD_STRUCTURE.test(text);
}

// The GitHub schema drops the structural tags Azure Document Intelligence emits around tables and
// images (`<caption>`, `<figure>`, `<figcaption>`, `<colgroup>`). Dropping an element keeps its
// children, so a stripped `<caption>` leaves bare text sitting directly inside `<table>`, invalid
// nesting that React reports as a hydration error. These five carry no behaviour, so allowing them
// both fixes the nesting and renders the caption as a caption.
const SCHEMA = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "caption",
    "figure",
    "figcaption",
    "colgroup",
    "col",
  ],
  attributes: {
    ...defaultSchema.attributes,
    colgroup: ["span"],
    col: ["span"],
  },
};

// What each table-structural element is allowed to contain, and the wrapper to put anything else
// in. A chunk is an arbitrary slice of a document, so it can still hand us a half-open table or
// markup the sanitizer unwrapped into the wrong place; without this, React logs an invalid-nesting
// error and the browser hoists the stray content out of the table on hydration.
const TABLE_SLOTS: Record<string, { allow: string[]; wrap: string[] }> = {
  table: { allow: ["caption", "colgroup", "thead", "tbody", "tfoot", "tr"], wrap: ["caption"] },
  thead: { allow: ["tr"], wrap: ["tr", "td"] },
  tbody: { allow: ["tr"], wrap: ["tr", "td"] },
  tfoot: { allow: ["tr"], wrap: ["tr", "td"] },
  tr: { allow: ["td", "th"], wrap: ["td"] },
};

/** Nest ``children`` inside ``tags`` outermost-first, e.g. ``["tr","td"]`` -> ``<tr><td>…``. */
function nest(tags: string[], children: ElementContent[]): Element {
  const [tag, ...rest] = tags;
  return {
    type: "element",
    tagName: tag,
    properties: {},
    children: rest.length ? [nest(rest, children)] : children,
  };
}

function repair(node: Root | Element) {
  for (const child of node.children) {
    if (child.type === "element") repair(child);
  }
  if (node.type !== "element") return;
  const slot = TABLE_SLOTS[node.tagName];
  if (!slot) return;
  const out: ElementContent[] = [];
  // Consecutive strays share one wrapper, so a caption split across text and inline markup stays a
  // single caption. Whitespace-only text is left alone: React ignores it inside a table.
  let stray: ElementContent[] = [];
  const flush = () => {
    if (stray.length) out.push(nest(slot.wrap, stray));
    stray = [];
  };
  for (const child of node.children) {
    const ok =
      (child.type === "element" && slot.allow.includes(child.tagName)) ||
      (child.type === "text" && !child.value.trim()) ||
      child.type === "comment";
    if (ok) {
      flush();
      out.push(child);
    } else {
      stray.push(child);
    }
  }
  flush();
  node.children = out;
}

/** Rehype plugin: make table markup valid so React never sees invalid nesting. */
const rehypeRepairTables = () => repair;

// Typography classes tuned for chunk-sized content: tight vertical rhythm, bordered table cells
// (prose leaves table borders very faint), and horizontal scroll so a wide table can't stretch
// the row it sits in.
const PROSE =
  "prose prose-sm dark:prose-invert max-w-none " +
  "prose-p:my-1.5 prose-headings:my-2 prose-headings:text-[13px] prose-ul:my-1.5 prose-ol:my-1.5 " +
  "prose-li:my-0.5 prose-pre:my-1.5 prose-pre:text-[12px] prose-code:text-indigo-600 dark:prose-code:text-indigo-300 " +
  "prose-table:my-1.5 prose-table:text-[12px] prose-thead:border-gray-200 dark:prose-thead:border-slate-700 " +
  "prose-th:px-2 prose-th:py-1 prose-th:align-top prose-th:border prose-th:border-gray-200 dark:prose-th:border-slate-700 " +
  "prose-th:bg-gray-50 dark:prose-th:bg-slate-800/60 " +
  "prose-td:px-2 prose-td:py-1 prose-td:align-top prose-td:border prose-td:border-gray-200 dark:prose-td:border-slate-700 " +
  "prose-a:text-indigo-600 dark:prose-a:text-indigo-400 prose-img:my-1.5 " +
  // Captions read as metadata, not as a table row.
  "[&_caption]:text-left [&_caption]:text-[11px] [&_caption]:pb-1 [&_caption]:text-gray-500 " +
  "dark:[&_caption]:text-slate-400 prose-figcaption:text-[11px] prose-figcaption:mt-1";

/**
 * Render chunk text for a human reviewer. ``rendered`` off (or content with no markup) falls back
 * to the plain pre-wrapped text, which stays the honest view of what the index actually stores.
 */
export function ChunkText({
  text,
  rendered,
  clamp,
  className = "",
}: {
  text: string;
  rendered: boolean;
  // Collapsed preview: cap the height instead of clamping lines (line-clamp doesn't apply to the
  // block children a rendered table produces).
  clamp?: boolean;
  className?: string;
}) {
  if (!rendered || !isRenderable(text)) {
    return (
      <p
        className={`text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap ${
          clamp ? "line-clamp-3" : ""
        } ${className}`}
      >
        {text}
      </p>
    );
  }

  return (
    <div
      className={`${PROSE} text-gray-700 dark:text-slate-300 overflow-x-auto ${
        clamp ? "max-h-24 overflow-y-hidden" : ""
      } ${className}`}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, SCHEMA], rehypeRepairTables]}
      >
        {text}
      </Markdown>
    </div>
  );
}
