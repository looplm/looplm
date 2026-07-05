"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  computeIndexFieldDocs,
  getIndexFieldDocs,
  getIndexFieldSchema,
} from "@/lib/api";
import type {
  IndexFieldDocs,
  IndexFieldGroup,
  IndexFieldSchemaItem,
} from "@/lib/api-types/index-explorer";
import { ErrorNotice } from "@/components/error-notice";
import {
  buildFieldsMarkdown,
  shortType,
} from "@/components/data-sources/field-schema-markdown";

// The capability flags we surface as chips, in display order, with a tone.
const ATTR_CHIPS: {
  test: (f: IndexFieldSchemaItem) => boolean;
  label: string;
  cls: string;
  title: string;
}[] = [
  {
    test: (f) => f.is_key,
    label: "key",
    cls: "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400",
    title: "The document key that uniquely identifies each chunk",
  },
  {
    test: (f) => f.searchable,
    label: "searchable",
    cls: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
    title: "Full-text searchable (matched by keyword queries)",
  },
  {
    test: (f) => f.filterable,
    label: "filterable",
    cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    title: "Usable in filters (exact-value constraints)",
  },
  {
    test: (f) => f.facetable,
    label: "facetable",
    cls: "bg-violet-500/15 text-violet-600 dark:text-violet-400",
    title: "Can be grouped/counted by value (a browsing dimension)",
  },
  {
    test: (f) => f.sortable,
    label: "sortable",
    cls: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    title: "Results can be ordered by this field",
  },
  {
    test: (f) => f.is_vector,
    label: "vector",
    cls: "bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-400",
    title: "An embedding vector used for dense/semantic search",
  },
  {
    test: (f) => !f.retrievable,
    label: "not retrievable",
    cls: "bg-gray-400/15 text-gray-500 dark:text-slate-400",
    title: "Not returned in results (used for search/filtering only)",
  },
];

function AttrChips({ field }: { field: IndexFieldSchemaItem }) {
  const chips = ATTR_CHIPS.filter((c) => c.test(field));
  if (chips.length === 0) {
    return (
      <span className="text-[10px] text-gray-400 dark:text-slate-500">retrievable only</span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1">
      {chips.map((c) => (
        <span
          key={c.label}
          title={c.title}
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${c.cls}`}
        >
          {c.label}
        </span>
      ))}
    </div>
  );
}

/** A slim bar showing what fraction of sampled docs carry a value. */
function FillBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  return (
    <div className="flex items-center gap-1.5" title={`${pct}% of sampled documents have a value`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-gray-200 dark:bg-slate-700">
        <div
          className="h-full rounded-full bg-indigo-500/70"
          style={{ width: `${Math.max(pct === 0 ? 0 : 4, pct)}%` }}
        />
      </div>
      <span className="w-8 text-right text-[10px] tabular-nums text-gray-400 dark:text-slate-500">
        {pct}%
      </span>
    </div>
  );
}

function ExampleValues({ values }: { values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      <span className="text-[10px] text-gray-400 dark:text-slate-500">e.g.</span>
      {values.map((v, i) => (
        <code
          key={i}
          className="max-w-full truncate rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600 dark:bg-slate-800 dark:text-slate-300"
          title={v}
        >
          {v}
        </code>
      ))}
    </div>
  );
}

function FieldRow({
  field,
  purpose,
}: {
  field: IndexFieldSchemaItem;
  purpose: string | undefined;
}) {
  return (
    <div className="border-t border-gray-100 py-3 first:border-t-0 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <code className="font-mono text-sm font-medium text-gray-800 dark:text-slate-100">
          {field.name}
        </code>
        <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-500 dark:bg-slate-800 dark:text-slate-400">
          {shortType(field.type)}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <FillBar rate={field.fill_rate} />
        </div>
      </div>

      <div className="mt-1.5">
        <AttrChips field={field} />
      </div>

      {purpose ? (
        <p className="mt-2 text-xs leading-relaxed text-gray-600 dark:text-slate-300">
          <span className="mr-1 text-indigo-400" title="Explanation written by AI">
            ✨
          </span>
          {purpose}
        </p>
      ) : null}

      <ExampleValues values={field.example_values} />
    </div>
  );
}

function RelatedGroupCard({ group }: { group: IndexFieldGroup }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs font-medium text-gray-700 dark:text-slate-200">{group.title}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {group.field_names.map((n) => (
          <code
            key={n}
            className="rounded bg-indigo-500/10 px-1.5 py-0.5 font-mono text-[11px] text-indigo-600 dark:text-indigo-300"
          >
            {n}
          </code>
        ))}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-gray-600 dark:text-slate-300">
        {group.distinction}
      </p>
    </div>
  );
}

export function FieldSchemaTab({
  providerId,
  providerName,
  canEdit,
}: {
  providerId: string;
  providerName?: string;
  canEdit: boolean;
}) {
  const [fields, setFields] = useState<IndexFieldSchemaItem[] | null>(null);
  const [sampleSize, setSampleSize] = useState(0);
  const [docs, setDocs] = useState<IndexFieldDocs | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [schema, fieldDocs] = await Promise.all([
        getIndexFieldSchema(providerId),
        getIndexFieldDocs(providerId),
      ]);
      setFields(schema.fields);
      setSampleSize(schema.sample_size);
      setDocs(fieldDocs.docs);
      setGeneratedAt(fieldDocs.generated_at);
      setModel(fieldDocs.model);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  useEffect(() => {
    load();
  }, [load]);

  const onExplain = useCallback(async () => {
    setExplaining(true);
    setExplainError(null);
    try {
      const res = await computeIndexFieldDocs(providerId);
      setDocs(res.docs);
      setGeneratedAt(res.generated_at);
      setModel(res.model);
    } catch (e) {
      setExplainError(e);
    } finally {
      setExplaining(false);
    }
  }, [providerId]);

  const purposeByName = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of docs?.fields ?? []) map.set(d.name, d.purpose);
    return map;
  }, [docs]);

  const onCopyMarkdown = useCallback(async () => {
    if (!fields) return;
    const markdown = buildFieldsMarkdown({
      fields,
      docs,
      generatedAt,
      model,
      sampleSize,
      providerName,
    });
    try {
      await navigator.clipboard.writeText(markdown);
      toast.success("Markdown report copied to clipboard");
    } catch {
      toast.error("Could not copy to clipboard");
    }
  }, [fields, docs, generatedAt, model, sampleSize, providerName]);

  if (loading) {
    return <p className="py-8 text-sm text-gray-400 dark:text-slate-500">Loading fields…</p>;
  }
  if (error != null) return <ErrorNotice error={error} />;
  if (!fields || fields.length === 0) {
    return (
      <p className="py-8 text-sm text-gray-500 dark:text-slate-400">
        This index exposes no fields.
      </p>
    );
  }

  const generatedLabel = generatedAt
    ? new Date(generatedAt).toLocaleString()
    : null;

  return (
    <div>
      {/* Explain controls */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-gray-500 dark:text-slate-400">
          Every metadata field in your connected index, with its type, what it can do, how often it
          is populated, and example values. Use AI to describe each field and clarify how similar
          fields differ from one another.
        </p>
        <div className="flex flex-shrink-0 items-center gap-2">
          <button
            onClick={onCopyMarkdown}
            className="rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-700 hover:bg-gray-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            title="Copy a Markdown report of these fields to the clipboard"
          >
            Copy Markdown
          </button>
          {canEdit && (
            <button
              onClick={onExplain}
              disabled={explaining}
              className="rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {explaining ? "Explaining…" : docs ? "Re-explain fields" : "✨ Explain fields"}
            </button>
          )}
        </div>
      </div>

      {explainError != null && (
        <div className="mb-4">
          <ErrorNotice error={explainError} />
        </div>
      )}

      {/* AI summary + provenance */}
      {docs && (docs.summary || generatedLabel) && (
        <div className="mb-4 rounded-xl border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-900/40 dark:bg-indigo-900/10">
          {docs.summary && (
            <p className="text-sm text-gray-700 dark:text-slate-200">
              <span className="mr-1">✨</span>
              {docs.summary}
            </p>
          )}
          {generatedLabel && (
            <p className="mt-1 text-[11px] text-gray-400 dark:text-slate-500">
              Explanations written by AI{model ? ` (${model})` : ""}, {generatedLabel}. They are
              inferred from field names and sampled values, so double-check anything surprising.
            </p>
          )}
        </div>
      )}

      {/* Related / confusable fields */}
      {docs && docs.groups.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-slate-200">
            Related fields, and how they differ
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {docs.groups.map((g, i) => (
              <RelatedGroupCard key={i} group={g} />
            ))}
          </div>
        </div>
      )}

      {/* Field list */}
      <div className="rounded-xl border border-gray-200 p-4 dark:border-slate-700">
        <div className="mb-1 flex items-center justify-between">
          <h3 className="text-sm font-medium text-gray-700 dark:text-slate-200">
            Fields <span className="text-gray-400 dark:text-slate-500">({fields.length})</span>
          </h3>
          {sampleSize > 0 && (
            <span className="text-[11px] text-gray-400 dark:text-slate-500">
              examples + fill rates from a sample of {sampleSize} documents
            </span>
          )}
        </div>
        {!docs && canEdit && (
          <p className="mb-1 text-xs text-gray-400 dark:text-slate-500">
            Run &quot;Explain fields&quot; above to add an AI description to each field.
          </p>
        )}
        {fields.map((f) => (
          <FieldRow key={f.name} field={f} purpose={purposeByName.get(f.name)} />
        ))}
      </div>
    </div>
  );
}
