"use client";

import { useEffect, useRef, useState } from "react";
import { TagInput } from "@/components/tag-input";

type ViewMode = "simple" | "json";

/** Pretty-print a key like "team_filter" → "Team Filter" */
function prettyLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Parse JSON string into entries. Returns null if invalid. */
function parseJson(json: string): Record<string, unknown> | null {
  if (!json.trim()) return {};
  try {
    const parsed = JSON.parse(json);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) return parsed;
    return null;
  } catch {
    return null;
  }
}

/** Serialize entries back to pretty JSON (or empty string if no keys). */
function toJson(obj: Record<string, unknown>): string {
  const filtered: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    // Skip empty arrays, null, undefined, empty strings, empty objects
    if (v === null || v === undefined) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    if (typeof v === "string" && v === "") continue;
    if (typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0) continue;
    filtered[k] = v;
  }
  return Object.keys(filtered).length > 0 ? JSON.stringify(filtered, null, 2) : "";
}

export function ConfigEditor({
  configJson,
  onChange,
  onValidChange,
}: {
  configJson: string;
  onChange: (json: string) => void;
  onValidChange?: (valid: boolean) => void;
}) {
  const [viewMode, setViewMode] = useState<ViewMode>("simple");
  const [jsonError, setJsonError] = useState<string | null>(null);
  // Parsed entries for simple view — kept in sync with configJson
  const [entries, setEntries] = useState<Record<string, unknown>>({});
  // Track whether we're the source of the change to avoid re-parsing our own updates
  const selfUpdate = useRef(false);

  // Sync from parent configJson on external changes (mount, editingCase switch)
  useEffect(() => {
    if (selfUpdate.current) {
      selfUpdate.current = false;
      return;
    }
    const parsed = parseJson(configJson);
    if (parsed !== null) {
      setEntries(parsed);
      setJsonError(null);
      onValidChange?.(true);
    }
  }, [configJson]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Update a single key in the entries and push to parent as JSON. */
  function updateEntry(key: string, value: unknown) {
    const next = { ...entries, [key]: value };
    setEntries(next);
    selfUpdate.current = true;
    onChange(toJson(next));
  }

  /** Remove a key entirely. */
  function removeEntry(key: string) {
    const next = { ...entries };
    delete next[key];
    setEntries(next);
    selfUpdate.current = true;
    onChange(toJson(next));
  }

  // --- JSON view handlers ---

  function handleJsonTextChange(value: string) {
    selfUpdate.current = false; // let the useEffect re-parse
    onChange(value);
    if (!value.trim()) {
      setJsonError(null);
      onValidChange?.(true);
      return;
    }
    try {
      JSON.parse(value);
      setJsonError(null);
      onValidChange?.(true);
    } catch (e) {
      setJsonError((e as Error).message);
      onValidChange?.(false);
    }
  }

  function handleFormat() {
    if (!configJson.trim()) return;
    try {
      const parsed = JSON.parse(configJson);
      selfUpdate.current = false;
      onChange(JSON.stringify(parsed, null, 2));
      setJsonError(null);
      onValidChange?.(true);
    } catch {
      // leave as-is
    }
  }

  function switchMode(mode: ViewMode) {
    if (mode === viewMode) return;
    if (mode === "simple") {
      const parsed = parseJson(configJson);
      if (parsed !== null) {
        setEntries(parsed);
        setJsonError(null);
        onValidChange?.(true);
      }
    }
    setViewMode(mode);
  }

  // --- Render a single entry based on value type ---

  function renderField(key: string, value: unknown) {
    // string[] → TagInput
    if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
      return (
        <TagInput
          value={value as string[]}
          onChange={(v) => updateEntry(key, v)}
          placeholder="Type and press Enter to add"
        />
      );
    }

    // boolean → toggle
    if (typeof value === "boolean") {
      return (
        <button
          type="button"
          onClick={() => updateEntry(key, !value)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            value ? "bg-indigo-600" : "bg-gray-300 dark:bg-slate-600"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              value ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      );
    }

    // number → number input
    if (typeof value === "number") {
      return (
        <input
          type="number"
          value={value}
          onChange={(e) => {
            const num = e.target.value === "" ? 0 : Number(e.target.value);
            updateEntry(key, num);
          }}
          className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
        />
      );
    }

    // string → text input
    if (typeof value === "string") {
      return (
        <input
          type="text"
          value={value}
          onChange={(e) => updateEntry(key, e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm"
        />
      );
    }

    // object / complex → read-only JSON snippet
    return (
      <pre className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs font-mono overflow-x-auto">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  const entryKeys = Object.keys(entries);

  return (
    <div>
      {/* Mode toggle */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
          <button
            type="button"
            onClick={() => switchMode("simple")}
            className={`px-3 py-1 text-xs font-medium transition-colors ${
              viewMode === "simple"
                ? "bg-indigo-600 text-white"
                : "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-700"
            }`}
          >
            Simple
          </button>
          <button
            type="button"
            onClick={() => switchMode("json")}
            className={`px-3 py-1 text-xs font-medium transition-colors ${
              viewMode === "json"
                ? "bg-indigo-600 text-white"
                : "bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-700"
            }`}
          >
            JSON
          </button>
        </div>
        {viewMode === "json" && (
          <button
            type="button"
            onClick={handleFormat}
            className="text-xs text-gray-400 hover:text-indigo-500 dark:hover:text-indigo-400 transition-colors"
          >
            Format
          </button>
        )}
      </div>

      {viewMode === "simple" ? (
        <div className="space-y-3">
          {entryKeys.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-slate-500 py-2">
              No configuration. Switch to JSON to add properties.
            </p>
          ) : (
            entryKeys.map((key) => (
              <div key={key}>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium">{prettyLabel(key)}</label>
                  <button
                    type="button"
                    onClick={() => removeEntry(key)}
                    className="text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                  >
                    Remove
                  </button>
                </div>
                {renderField(key, entries[key])}
              </div>
            ))
          )}
        </div>
      ) : (
        <div>
          <p className="text-xs text-gray-400 dark:text-slate-500 mb-2">
            Pre-conditions, filters, expected values, and custom metadata. Leave empty for no configuration.
          </p>
          <textarea
            value={configJson}
            onChange={(e) => handleJsonTextChange(e.target.value)}
            rows={10}
            spellCheck={false}
            className={`w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800 border text-sm font-mono ${
              jsonError
                ? "border-red-400 dark:border-red-500"
                : "border-gray-200 dark:border-slate-700"
            }`}
            placeholder={`{\n  "team_filter": ["Vertragsmanagement"],\n  "deep_thinking": true\n}`}
          />
          {jsonError && (
            <p className="text-xs text-red-500 mt-1">{jsonError}</p>
          )}
        </div>
      )}
    </div>
  );
}
