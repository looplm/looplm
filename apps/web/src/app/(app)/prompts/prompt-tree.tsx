"use client";

import { ReactNode } from "react";
import type { PromptItem } from "@/lib/api";

interface TreeNode {
  name: string;
  path: string[];
  children: Map<string, TreeNode>;
  prompts: PromptItem[];
}

function makeNode(name: string, path: string[]): TreeNode {
  return { name, path, children: new Map(), prompts: [] };
}

function buildTree(prompts: PromptItem[]): TreeNode {
  const root = makeNode("", []);
  for (const p of prompts) {
    const path = (p.cluster_path ?? []).filter(Boolean);
    let node = root;
    for (const level of path) {
      let child = node.children.get(level);
      if (!child) {
        child = makeNode(level, [...node.path, level]);
        node.children.set(level, child);
      }
      node = child;
    }
    node.prompts.push(p);
  }
  return root;
}

function countDeep(node: TreeNode): number {
  let n = node.prompts.length;
  for (const c of node.children.values()) n += countDeep(c);
  return n;
}

function Branch({
  node,
  renderPrompt,
  depth,
}: {
  node: TreeNode;
  renderPrompt: (p: PromptItem) => ReactNode;
  depth: number;
}) {
  const children = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <details open className="group">
      <summary className="cursor-pointer select-none list-none flex items-center gap-1.5 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300">
        <span className="transition-transform group-open:rotate-90">▸</span>
        <span className="truncate">{node.name}</span>
        <span className="text-gray-300 dark:text-slate-600 normal-case font-normal">
          {countDeep(node)}
        </span>
      </summary>
      <div className="ml-3 border-l border-gray-100 dark:border-slate-800 pl-2 space-y-2 py-1">
        {children.map((c) => (
          <Branch key={c.path.join("/")} node={c} renderPrompt={renderPrompt} depth={depth + 1} />
        ))}
        {node.prompts.map((p) => renderPrompt(p))}
      </div>
    </details>
  );
}

export function PromptTree({
  prompts,
  renderPrompt,
}: {
  prompts: PromptItem[];
  renderPrompt: (p: PromptItem) => ReactNode;
}) {
  const root = buildTree(prompts);
  const topLevel = [...root.children.values()].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div className="space-y-2">
      {topLevel.map((c) => (
        <Branch key={c.path.join("/")} node={c} renderPrompt={renderPrompt} depth={0} />
      ))}
      {/* Ungrouped prompts (no cluster_path) render flat at the bottom. */}
      {root.prompts.length > 0 && (
        <div className="space-y-2">
          {topLevel.length > 0 && (
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-slate-500">
              Ungrouped
            </div>
          )}
          {root.prompts.map((p) => renderPrompt(p))}
        </div>
      )}
    </div>
  );
}
