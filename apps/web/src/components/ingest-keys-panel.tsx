"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  getIngestKeys,
  createIngestKey,
  revokeIngestKey,
  type Integration,
  type IngestKey,
  type IngestKeyCreated,
} from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" ? window.location.origin : "http://localhost:8000");

function snippet(apiKey: string): string {
  return `pip install looplm

from looplm import LoopLM

client = LoopLM(
    api_key="${apiKey}",
    base_url="${API_BASE}",
)

with client.trace("chat", input={"q": "hi"}, user_id="u-1") as t:
    with t.span("llm", name="answer", model="gpt-4o") as s:
        s.set_tokens(input=120, output=80)
        s.set_output({"answer": "hello"})`;
}

interface Props {
  integration: Integration;
  onEdit: (i: Integration) => void;
  onDelete: (i: Integration) => void;
}

export function LooplmTracingCard({ integration: i, onEdit, onDelete }: Props) {
  const [keys, setKeys] = useState<IngestKey[]>([]);
  const [newName, setNewName] = useState("default");
  const [created, setCreated] = useState<IngestKeyCreated | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => getIngestKeys(i.id).then((r) => setKeys(r.data)).catch(() => {});
  useEffect(() => { load(); }, [i.id]);

  const handleCreate = async () => {
    setLoading(true);
    try {
      const key = await createIngestKey(i.id, newName.trim() || "default");
      setCreated(key);
      setNewName("default");
      load();
    } catch (err: any) {
      toast.error("Failed to create key", { description: err.message });
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    if (!confirm("Revoke this key? Apps using it will stop being able to send traces.")) return;
    try {
      await revokeIngestKey(i.id, keyId);
      if (created && created.id === keyId) setCreated(null);
      load();
    } catch (err: any) {
      toast.error("Failed to revoke key", { description: err.message });
    }
  };

  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success("Copied to clipboard"),
      () => toast.error("Copy failed"),
    );
  };

  const activeKeys = keys.filter((k) => !k.revoked_at);

  return (
    <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h3 className="font-semibold">{i.name}</h3>
            <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
              LoopLM SDK
            </span>
          </div>
          <div className="text-sm text-gray-500 dark:text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
            <span>{activeKeys.length} active key{activeKeys.length === 1 ? "" : "s"}</span>
            <span>
              Last received:{" "}
              {i.last_received_at ? new Date(i.last_received_at).toLocaleString() : "Never"}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onEdit(i)}
            className="px-3 py-1.5 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 rounded-lg text-sm"
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(i)}
            className="px-3 py-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded-lg text-sm"
          >
            Delete
          </button>
        </div>
      </div>

      {/* One-time plaintext key banner */}
      {created && (
        <div className="mt-4 p-4 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30">
          <p className="text-sm font-medium text-amber-800 dark:text-amber-300 mb-2">
            Copy your key now — it won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 rounded bg-white dark:bg-slate-950 border border-amber-200 dark:border-amber-500/30 text-sm font-mono break-all">
              {created.key}
            </code>
            <button
              onClick={() => copy(created.key)}
              className="px-3 py-2 bg-amber-500 hover:bg-amber-400 text-white rounded-lg text-sm font-medium shrink-0"
            >
              Copy
            </button>
          </div>
        </div>
      )}

      {/* Key management */}
      <div className="mt-5">
        <div className="flex items-end gap-2 mb-3">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 dark:text-slate-400 mb-1">New key name</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
              placeholder="default"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={loading}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white disabled:opacity-50"
          >
            + Create key
          </button>
        </div>

        {keys.length > 0 && (
          <div className="rounded-lg border border-gray-100 dark:border-slate-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-slate-800/50 text-gray-500 dark:text-slate-400">
                <tr>
                  <th className="text-left font-medium px-3 py-2">Name</th>
                  <th className="text-left font-medium px-3 py-2">Key</th>
                  <th className="text-left font-medium px-3 py-2">Last used</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id} className="border-t border-gray-100 dark:border-slate-800">
                    <td className="px-3 py-2">{k.name}</td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-500 dark:text-slate-400">
                      {k.key_prefix}…
                    </td>
                    <td className="px-3 py-2 text-gray-500 dark:text-slate-400">
                      {k.revoked_at ? (
                        <span className="text-red-400">Revoked</span>
                      ) : k.last_used_at ? (
                        new Date(k.last_used_at).toLocaleString()
                      ) : (
                        "Never"
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {!k.revoked_at && (
                        <button
                          onClick={() => handleRevoke(k.id)}
                          className="text-red-400 hover:text-red-300 text-xs"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Install snippet */}
      <div className="mt-5">
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs text-gray-500 dark:text-slate-400">Quickstart (Python)</label>
          <button
            onClick={() => copy(snippet(created?.key ?? "llm_sk_…"))}
            className="text-xs text-indigo-500 hover:text-indigo-400"
          >
            Copy snippet
          </button>
        </div>
        <pre className="p-4 rounded-lg bg-gray-50 dark:bg-slate-950 border border-gray-100 dark:border-slate-800 text-xs font-mono overflow-x-auto whitespace-pre">
          {snippet(created?.key ?? "llm_sk_…")}
        </pre>
      </div>
    </div>
  );
}
