"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";

// Chunks come out of the index as whatever the ingester produced: plain prose, Markdown, or raw
// HTML fragments (tables from scraped pages and Confluence exports are the common case). Reading
// `<td>` soup line by line is what a human reviewer has to do otherwise, so this renders the
// markup instead — Markdown + GFM tables, with raw HTML passed through a sanitizer.

// Chunk text is untrusted (it is whatever got indexed), so raw HTML goes through rehype-sanitize's
// default GitHub schema: script tags, event handlers and javascript: URLs are dropped, while table
// structure (including colspan/rowspan) survives.

// Block-level HTML, or Markdown structure worth rendering (table pipes, headings, list bullets,
// bold). Plain prose fails this test and stays plain text — rendering it would only add noise.
const HTML_BLOCK = /<\/?(table|thead|tbody|tr|t[dh]|ul|ol|li|p|div|h[1-6]|pre|code|br|strong|em|b|i|a|span|img)\b[^>]*>/i;
const MD_TABLE = /^\s*\|.*\|\s*$/m;
const MD_STRUCTURE = /^\s{0,3}#{1,6}\s|^\s{0,3}[-*+]\s|^\s{0,3}\d+\.\s|\*\*[^*\n]+\*\*|^\s{0,3}>\s/m;

/** Whether rendering this text as HTML/Markdown would show the reviewer anything extra. */
export function isRenderable(text: string | null | undefined): boolean {
  if (!text) return false;
  return HTML_BLOCK.test(text) || MD_TABLE.test(text) || MD_STRUCTURE.test(text);
}

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
  "prose-a:text-indigo-600 dark:prose-a:text-indigo-400 prose-img:my-1.5";

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
      <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeSanitize]}>
        {text}
      </Markdown>
    </div>
  );
}
