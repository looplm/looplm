/**
 * Build a shareable Markdown report of the index field schema + AI field docs.
 * Rendered client-side from data already loaded by the Fields tab, so the report
 * can be copied with one click without another round trip.
 */

import type {
  IndexFieldDocs,
  IndexFieldSchemaItem,
} from "@/lib/api-types/index-explorer";

/** Compact, human-friendly rendering of an Edm type (Collection(Edm.String) -> String[]). */
export function shortType(type: string): string {
  const collection = type.match(/^Collection\((.+)\)$/);
  const inner = (collection ? collection[1] : type).replace(/^Edm\./, "");
  return collection ? `${inner}[]` : inner;
}

/** The capability flags of a field, as plain labels in display order. */
export function fieldAttributes(f: IndexFieldSchemaItem): string[] {
  const attrs: string[] = [];
  if (f.is_key) attrs.push("key");
  if (f.searchable) attrs.push("searchable");
  if (f.filterable) attrs.push("filterable");
  if (f.facetable) attrs.push("facetable");
  if (f.sortable) attrs.push("sortable");
  if (f.is_vector) attrs.push("vector");
  if (!f.retrievable) attrs.push("not retrievable");
  return attrs;
}

/** Escape a value for a Markdown table cell (pipes break the table; flatten newlines). */
function cell(s: string): string {
  return s.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
}

export function buildFieldsMarkdown(opts: {
  fields: IndexFieldSchemaItem[];
  docs: IndexFieldDocs | null;
  generatedAt: string | null;
  model: string | null;
  sampleSize: number;
  providerName?: string;
}): string {
  const { fields, docs, generatedAt, model, sampleSize, providerName } = opts;

  const purposeByName = new Map<string, string>();
  for (const d of docs?.fields ?? []) purposeByName.set(d.name, d.purpose);

  const lines: string[] = [];
  lines.push(`# Index fields${providerName ? `: ${providerName}` : ""}`);
  lines.push("");

  if (docs?.summary) {
    lines.push(docs.summary);
    lines.push("");
  }

  if (docs && docs.groups.length > 0) {
    lines.push("## Related fields, and how they differ");
    lines.push("");
    for (const g of docs.groups) {
      lines.push(`### ${g.title}`);
      lines.push(`Fields: ${g.field_names.map((n) => `\`${n}\``).join(", ")}`);
      lines.push("");
      lines.push(g.distinction);
      lines.push("");
    }
  }

  lines.push("## Fields");
  lines.push("");
  lines.push("| Field | Type | Attributes | Fill | Examples | Purpose |");
  lines.push("| --- | --- | --- | --- | --- | --- |");
  for (const f of fields) {
    const attrs = fieldAttributes(f).join(", ") || "retrievable only";
    const examples = f.example_values.map((v) => `\`${v}\``).join(" ");
    const pct = `${Math.round(f.fill_rate * 100)}%`;
    const purpose = purposeByName.get(f.name) ?? "";
    lines.push(
      `| \`${f.name}\` | ${shortType(f.type)} | ${attrs} | ${pct} | ${cell(examples)} | ${cell(purpose)} |`,
    );
  }
  lines.push("");

  if (docs && generatedAt) {
    lines.push(
      `_Field explanations written by AI${model ? ` (${model})` : ""} on ${new Date(
        generatedAt,
      ).toLocaleString()}. Inferred from field names and sampled values, so verify anything surprising._`,
    );
  }
  if (sampleSize > 0) {
    lines.push(`_Example values and fill rates from a sample of ${sampleSize} documents._`);
  }

  return lines.join("\n");
}
