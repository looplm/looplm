"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  getDuplicates,
  deleteTestCase,
  mergeDuplicates,
  dismissDuplicates,
  type DuplicatesResponse,
  type DuplicateGroup,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { ConfirmModal } from "@/components/confirm-modal";
import { usePermissions } from "@/components/permissions-context";
import { DuplicateGroupCard } from "./duplicate-group-card";

/** Stable key for a group so the "keep" selection survives refetches. */
function groupKey(group: DuplicateGroup): string {
  return group.members.map((m) => m.case_id).sort().join("|");
}

type PendingAction =
  | { kind: "delete"; group: DuplicateGroup; keepId: string }
  | { kind: "merge"; group: DuplicateGroup; keepId: string };

export default function DuplicatesPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("datasets");

  const [threshold, setThreshold] = useState(0.8);
  const [scope, setScope] = useState<"all" | "within_dataset">("all");
  const [resp, setResp] = useState<DuplicatesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [keepById, setKeepById] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const reqIdRef = useRef(0);

  const load = useCallback(async () => {
    const reqId = ++reqIdRef.current;
    setLoading(true);
    try {
      const data = await getDuplicates({ threshold, scope });
      if (reqId !== reqIdRef.current) return; // a newer request superseded this one
      setResp(data);
    } catch {
      if (reqId === reqIdRef.current) setResp(null);
    } finally {
      if (reqId === reqIdRef.current) setLoading(false);
    }
  }, [threshold, scope]);

  // Debounce refetch so dragging the slider doesn't spam the API.
  useEffect(() => {
    const t = setTimeout(load, 350);
    return () => clearTimeout(t);
  }, [load]);

  const groups = resp?.groups ?? [];

  function keepFor(group: DuplicateGroup): string {
    return keepById[groupKey(group)] ?? group.members[0].case_id;
  }

  function selectKeep(group: DuplicateGroup, caseId: string) {
    setKeepById((prev) => ({ ...prev, [groupKey(group)]: caseId }));
  }

  async function runAction(fn: () => Promise<unknown>, key: string) {
    setBusyKey(key);
    try {
      await fn();
      await load();
    } catch {
      // ignore — surfaced by the API error handler
    } finally {
      setBusyKey(null);
    }
  }

  function confirmDelete(group: DuplicateGroup) {
    setPending({ kind: "delete", group, keepId: keepFor(group) });
  }

  function confirmMerge(group: DuplicateGroup) {
    setPending({ kind: "merge", group, keepId: keepFor(group) });
  }

  async function handleConfirm() {
    if (!pending) return;
    const { group, keepId } = pending;
    const others = group.members.filter((m) => m.case_id !== keepId);
    const key = groupKey(group);
    setPending(null);
    if (pending.kind === "delete") {
      await runAction(
        () => Promise.all(others.map((m) => deleteTestCase(m.dataset_id, m.case_id))),
        key,
      );
    } else {
      await runAction(
        () => mergeDuplicates(keepId, others.map((m) => m.case_id)),
        key,
      );
    }
  }

  async function handleDismiss(group: DuplicateGroup) {
    await runAction(
      () => dismissDuplicates(group.members.map((m) => m.case_id)),
      groupKey(group),
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/datasets"
          className="text-sm text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 mb-2 inline-block"
        >
          &larr; Datasets
        </Link>
        <h1 className="text-2xl font-bold">Duplicate Questions</h1>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
          Prompts that appear more than once across all datasets in this project. Pick one case to
          keep, then merge or delete the rest — or dismiss a group that only looks similar.
        </p>
      </div>

      {/* Controls + stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Duplicate Groups" value={groups.length} />
        <StatCard
          label="Affected Cases"
          value={resp?.duplicate_cases ?? 0}
          sub={resp ? `of ${resp.total_cases} total` : undefined}
        />
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4 flex flex-col justify-center gap-2">
          <div className="flex items-center justify-between text-sm">
            <label htmlFor="threshold" className="text-gray-500 dark:text-slate-400">
              Similarity
            </label>
            <span className="font-mono text-gray-700 dark:text-slate-200">
              {Math.round(threshold * 100)}%
            </span>
          </div>
          <input
            id="threshold"
            type="range"
            min={0.5}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-indigo-600"
          />
          <div className="flex gap-1 mt-1">
            {(["all", "within_dataset"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={`flex-1 px-2 py-1 rounded-md text-xs transition-colors ${
                  scope === s
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700"
                }`}
              >
                {s === "all" ? "All datasets" : "Within dataset"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Groups */}
      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Scanning...</p>
      ) : groups.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No duplicate questions found at this similarity threshold. Lower it to catch looser
          matches.
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((group, i) => {
            const key = groupKey(group);
            return (
              <DuplicateGroupCard
                key={key}
                group={group}
                index={i}
                keepId={keepFor(group)}
                canEdit={canEdit}
                busy={busyKey === key}
                onSelectKeep={(caseId) => selectKeep(group, caseId)}
                onDeleteOthers={() => confirmDelete(group)}
                onMerge={() => confirmMerge(group)}
                onDismiss={() => handleDismiss(group)}
              />
            );
          })}
        </div>
      )}

      {/* Confirm modal */}
      {pending && (
        <ConfirmModal
          title={pending.kind === "delete" ? "Delete Duplicate Cases" : "Merge Duplicate Cases"}
          message={
            pending.kind === "delete"
              ? `Delete ${pending.group.members.length - 1} case(s) and keep only the selected one? This cannot be undone.`
              : `Merge ${pending.group.members.length - 1} case(s) into the selected one (unioning their sources, tags, and answers) and delete the rest? This cannot be undone.`
          }
          confirmLabel={pending.kind === "delete" ? "Delete" : "Merge"}
          confirmVariant="danger"
          onConfirm={handleConfirm}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
