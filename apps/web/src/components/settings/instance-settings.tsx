"use client";

import { useEffect, useState } from "react";
import {
  getMigrations,
  runMigrations,
  type MigrationsStatus,
  type MigrationUpgradeResult,
} from "@/lib/api";

export default function InstanceSettings() {
  const [status, setStatus] = useState<MigrationsStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<MigrationUpgradeResult | null>(null);

  function refresh() {
    setLoadError(null);
    getMigrations()
      .then(setStatus)
      .catch(() => setLoadError("Could not load migration status"));
  }

  useEffect(() => {
    refresh();
  }, []);

  async function apply() {
    setRunning(true);
    setResult(null);
    try {
      const res = await runMigrations();
      setResult(res);
      refresh();
    } catch (e) {
      setResult({
        success: false,
        before_rev: status?.current_rev ?? null,
        after_rev: status?.current_rev ?? null,
        output: String((e as Error)?.message ?? e),
      });
    } finally {
      setRunning(false);
      setConfirming(false);
    }
  }

  const upToDate =
    status && status.head_rev !== null && status.current_rev === status.head_rev;

  return (
    <div className="space-y-6">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-1">Database Migrations</h2>
        <p className="text-sm text-gray-500 dark:text-slate-400 mb-4">
          Apply pending Alembic revisions to bring the database schema up to the
          version the running API expects. Avoid running while traffic is heavy —
          for large or locking migrations, prefer{" "}
          <code className="font-mono text-xs">alembic upgrade head</code> from a
          shell.
        </p>

        {loadError && <div className="text-sm text-red-500 mb-4">{loadError}</div>}

        {status && (
          <>
            <dl className="grid grid-cols-1 sm:grid-cols-[160px_1fr] gap-x-6 gap-y-2 text-sm mb-4">
              <dt className="text-gray-500 dark:text-slate-400">Current revision</dt>
              <dd className="font-mono">{status.current_rev ?? "(none)"}</dd>
              <dt className="text-gray-500 dark:text-slate-400">Head revision</dt>
              <dd className="font-mono">{status.head_rev ?? "(none)"}</dd>
              <dt className="text-gray-500 dark:text-slate-400">Pending</dt>
              <dd>{status.pending.length}</dd>
            </dl>

            {upToDate ? (
              <div className="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-sm text-emerald-700 dark:text-emerald-300">
                ✓ Database is up to date.
              </div>
            ) : (
              <>
                {status.pending.length > 0 && (
                  <ul className="mb-4 text-sm border border-gray-200 dark:border-slate-800 rounded-lg divide-y divide-gray-200 dark:divide-slate-800">
                    {status.pending.map((rev) => (
                      <li key={rev.revision} className="px-3 py-2 flex gap-3">
                        <span className="font-mono text-xs text-gray-500 dark:text-slate-400 shrink-0">
                          {rev.revision}
                        </span>
                        <span className="text-gray-800 dark:text-slate-200">
                          {rev.message || "(no message)"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {!confirming ? (
                  <button
                    onClick={() => setConfirming(true)}
                    disabled={running}
                    className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500 disabled:opacity-50"
                  >
                    Apply migrations
                  </button>
                ) : (
                  <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50">
                    <p className="text-sm text-amber-900 dark:text-amber-200 mb-3">
                      This will run <code className="font-mono">alembic upgrade head</code>{" "}
                      against the live database. Continue?
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={apply}
                        disabled={running}
                        className="px-4 py-2 bg-amber-600 text-white rounded-lg text-sm hover:bg-amber-500 disabled:opacity-50"
                      >
                        {running ? "Running…" : "Yes, apply"}
                      </button>
                      <button
                        onClick={() => setConfirming(false)}
                        disabled={running}
                        className="px-4 py-2 bg-gray-200 dark:bg-slate-800 text-gray-700 dark:text-slate-200 rounded-lg text-sm hover:bg-gray-300 dark:hover:bg-slate-700 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {result && (
          <div className="mt-6">
            <div
              className={`p-3 rounded-lg text-sm mb-3 ${
                result.success
                  ? "bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-emerald-700 dark:text-emerald-300"
                  : "bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300"
              }`}
            >
              {result.success ? "✓" : "✗"} {result.before_rev ?? "(none)"} →{" "}
              {result.after_rev ?? "(none)"}
            </div>
            <pre className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-96">
              {result.output || "(no output)"}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
