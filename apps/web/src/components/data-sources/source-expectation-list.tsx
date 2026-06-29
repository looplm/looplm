"use client";

import { Fragment } from "react";

import type {
  GapRowResult,
  GapRunDetail,
  SourceExpectation,
} from "@/lib/api-types/source-registry";

import {
  ALL_BUCKETS,
  BUCKET_CHIP,
  BUCKET_LABEL,
  type FilterBucket,
  type Group,
  STATUS_CHIP,
  shortUrl,
} from "./source-registry-shared";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-3.5 h-3.5 flex-shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

function ExpectationRow({
  e,
  verdict,
  canEdit,
  onAck,
  onUnack,
  onDelete,
}: {
  e: SourceExpectation;
  verdict: GapRowResult | undefined;
  canEdit: boolean;
  onAck: (e: SourceExpectation) => void;
  onUnack: (e: SourceExpectation) => void;
  onDelete: (e: SourceExpectation) => void;
}) {
  const status = e.ack_note ? "acked" : verdict?.status;
  const chip = status ? STATUS_CHIP[status] : null;
  const detail = e.ack_note ? `Acknowledged: ${e.ack_note}` : verdict?.detail;
  return (
    <tr className="border-b border-gray-50 dark:border-slate-800/50 align-top">
      <td className="py-2 pr-3 max-w-[24rem]">
        <span className="font-medium">{e.name}</span>
        {e.adapter_tag && (
          <div className="mt-0.5">
            <code className="text-[11px] bg-gray-100 dark:bg-slate-800 rounded px-1.5 py-0.5">
              {e.adapter_tag}
            </code>
          </div>
        )}
        <div className="mt-1 space-y-0.5 text-xs">
          {([
            ["HTML", e.html_url],
            ["PDF", e.pdf_url],
          ] as const).map(([label, url]) =>
            url ? (
              <div key={label} className="flex items-baseline gap-1.5">
                <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500 w-8 flex-shrink-0">
                  {label}
                </span>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  title={url}
                  className="text-indigo-600 dark:text-indigo-400 hover:underline truncate"
                >
                  ↗ {shortUrl(url)}
                </a>
              </div>
            ) : null,
          )}
        </div>
      </td>
      <td className="py-2 pr-3 text-xs max-w-[20rem]">
        {/* Only a real match counts; `missing` rows still carry a sub-threshold
            near-miss in matched_url/title, which would contradict the status. */}
        {(status === "covered_url" || status === "covered_title" || status === "review") &&
        (verdict?.matched_url || verdict?.matched_title) ? (
          <a
            href={verdict.matched_url ?? undefined}
            target="_blank"
            rel="noreferrer"
            title={verdict.matched_url ?? undefined}
            className="block truncate text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            ↗ {verdict.matched_title ?? shortUrl(verdict.matched_url!)}
          </a>
        ) : (
          <span className="text-gray-400 dark:text-slate-500">—</span>
        )}
      </td>
      <td className="py-2 pr-3 max-w-[16rem]">
        {chip ? (
          <span className={`inline-block px-2 py-1 rounded-full text-xs ${chip.cls}`}>
            {chip.label}
          </span>
        ) : (
          <span className="text-xs text-gray-400 dark:text-slate-500">not analyzed</span>
        )}
        {detail && (
          <span className="block mt-1 text-xs text-gray-500 dark:text-slate-400">
            {detail}
          </span>
        )}
      </td>
      {canEdit && (
        <td className="py-2 whitespace-nowrap text-xs">
          {e.ack_note ? (
            <button
              onClick={() => onUnack(e)}
              className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
            >
              Un-ack
            </button>
          ) : (
            <button
              onClick={() => onAck(e)}
              title="Mark this gap as intentional"
              className="text-gray-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 px-1.5 py-1"
            >
              Ack
            </button>
          )}
          <button
            onClick={() => onDelete(e)}
            className="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 px-1.5 py-1"
          >
            ×
          </button>
        </td>
      )}
    </tr>
  );
}

export function SourceExpectationList({
  run,
  summary,
  visibleStatuses,
  toggleStatus,
  resetStatuses,
  isDefaultFilter,
  resolvedGroupBy,
  availableDims,
  setGroupBy,
  groups,
  collapsedGroups,
  toggleGroup,
  verdicts,
  expectationsCount,
  shownCount,
  canEdit,
  onAck,
  onUnack,
  onDelete,
}: {
  run: GapRunDetail | null;
  summary: NonNullable<GapRunDetail["results"]>["summary"] | undefined;
  visibleStatuses: Set<FilterBucket>;
  toggleStatus: (b: FilterBucket) => void;
  resetStatuses: () => void;
  isDefaultFilter: boolean;
  resolvedGroupBy: string;
  availableDims: { key: keyof SourceExpectation; label: string }[];
  setGroupBy: (v: string) => void;
  groups: Group[];
  collapsedGroups: Set<string>;
  toggleGroup: (key: string) => void;
  verdicts: Record<string, GapRowResult>;
  expectationsCount: number;
  shownCount: number;
  canEdit: boolean;
  onAck: (e: SourceExpectation) => void;
  onUnack: (e: SourceExpectation) => void;
  onDelete: (e: SourceExpectation) => void;
}) {
  const colCount = canEdit ? 4 : 3;

  return (
    <>
      {summary && run?.status === "completed" && (
        <div className="flex flex-wrap items-center gap-2 my-3 text-xs">
          {ALL_BUCKETS.map((b) => {
            const active = visibleStatuses.has(b);
            const count =
              b === "covered"
                ? summary.covered
                : b === "review"
                  ? summary.review
                  : b === "missing"
                    ? summary.missing
                    : summary.acked;
            return (
              <button
                key={b}
                onClick={() => toggleStatus(b)}
                aria-pressed={active}
                title={active ? `Hide ${BUCKET_LABEL[b]}` : `Show ${BUCKET_LABEL[b]}`}
                className={`px-2 py-1 rounded-full transition ${BUCKET_CHIP[b]} ${
                  active ? "ring-1 ring-current/40" : "opacity-40 hover:opacity-70"
                }`}
              >
                {count} {BUCKET_LABEL[b]}
              </button>
            );
          })}
          <button
            onClick={resetStatuses}
            className="px-2 py-1 text-gray-500 dark:text-slate-400 hover:underline"
          >
            {isDefaultFilter ? "Show all" : "Only gaps"}
          </button>
          {run.completed_at && (
            <span className="px-2 py-1 text-gray-400 dark:text-slate-500">
              analyzed {new Date(run.completed_at).toLocaleString()}
            </span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 mt-3 mb-1 text-xs">
        <label className="flex items-center gap-1.5 text-gray-500 dark:text-slate-400">
          <span>Cluster by</span>
          <select
            value={resolvedGroupBy}
            onChange={(ev) => setGroupBy(ev.target.value)}
            className="bg-transparent border border-gray-200 dark:border-slate-700 rounded px-1.5 py-1"
          >
            {availableDims.map((d) => (
              <option key={d.key} value={d.key}>
                {d.label}
              </option>
            ))}
            <option value="none">None (flat list)</option>
          </select>
        </label>
        <span className="text-gray-400 dark:text-slate-500">
          Showing {shownCount} of {expectationsCount} sources
        </span>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-slate-500 py-4">
          No sources match the current filters.
        </p>
      ) : (
        <div className="overflow-x-auto mt-1">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 dark:text-slate-400 border-b border-gray-100 dark:border-slate-800">
                <th className="py-2 pr-3 font-medium">Wanted source (CSV)</th>
                <th className="py-2 pr-3 font-medium">In index</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                {canEdit && <th className="py-2 font-medium" />}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const flat = g.key === "__all__";
                const collapsed = collapsedGroups.has(g.key);
                return (
                  <Fragment key={g.key}>
                    {!flat && (
                      <tr className="bg-gray-50/70 dark:bg-slate-800/40 border-b border-gray-100 dark:border-slate-800">
                        <td colSpan={colCount} className="px-1 py-1.5">
                          <button
                            onClick={() => toggleGroup(g.key)}
                            aria-expanded={!collapsed}
                            className="w-full flex items-center gap-2 text-left"
                          >
                            <Chevron open={!collapsed} />
                            <span className="font-medium text-sm">{g.label}</span>
                            <span className="text-xs text-gray-400 dark:text-slate-500">
                              ({g.items.length})
                            </span>
                            <span className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
                              {g.counts.missing > 0 && (
                                <span
                                  className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.missing.cls}`}
                                >
                                  {g.counts.missing} missing
                                </span>
                              )}
                              {g.counts.review > 0 && (
                                <span
                                  className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.review.cls}`}
                                >
                                  {g.counts.review} review
                                </span>
                              )}
                              {g.counts.covered > 0 && (
                                <span
                                  className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.covered_url.cls}`}
                                >
                                  {g.counts.covered} covered
                                </span>
                              )}
                              {g.counts.acked > 0 && (
                                <span
                                  className={`px-1.5 py-0.5 rounded-full ${STATUS_CHIP.acked.cls}`}
                                >
                                  {g.counts.acked} ack
                                </span>
                              )}
                            </span>
                          </button>
                        </td>
                      </tr>
                    )}
                    {(flat || !collapsed) &&
                      g.items.map((e) => (
                        <ExpectationRow
                          key={e.id}
                          e={e}
                          verdict={verdicts[e.id]}
                          canEdit={canEdit}
                          onAck={onAck}
                          onUnack={onUnack}
                          onDelete={onDelete}
                        />
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
