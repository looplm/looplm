import Link from "next/link";
import type { ReactNode } from "react";
import { ErrorNotice } from "@/components/error-notice";
import Tooltip from "@/components/tooltip";
import InfoIcon from "@/components/info-icon";
import { PLOT_H } from "@/components/charts/chart-scale";

export interface SectionShellProps {
  title: string;
  subtitle?: string;
  tooltip?: string;
  action?: ReactNode;
  loading: boolean;
  error: unknown;
  /** The request succeeded but there is nothing to draw. */
  empty: boolean;
  emptyTitle: string;
  emptyHint?: string;
  emptyHref?: string;
  emptyCta?: string;
  /** Dim the last good content while a refetch is in flight. */
  refreshing?: boolean;
  children: ReactNode;
}

/**
 * Card chrome plus the four states every section needs, in one place so they cannot drift.
 *
 * Errors are scoped to the card. The dashboard blanks the whole page when any one of its
 * queries fails; here a broken section leaves the other three readable.
 */
export function SectionShell({
  title,
  subtitle,
  tooltip,
  action,
  loading,
  error,
  empty,
  emptyTitle,
  emptyHint,
  emptyHref,
  emptyCta,
  refreshing,
  children,
}: SectionShellProps) {
  return (
    <section className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-slate-100">
            {title}
            {tooltip ? (
              <Tooltip content={tooltip}>
                <span>
                  <InfoIcon />
                </span>
              </Tooltip>
            ) : null}
          </h2>
          {subtitle ? (
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {refreshing ? (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
              Updating
            </span>
          ) : null}
          {action}
        </div>
      </div>

      {error ? (
        <ErrorNotice error={error} />
      ) : loading ? (
        <div className={`${PLOT_H} rounded-lg bg-gray-100 dark:bg-slate-800 animate-pulse`} />
      ) : empty ? (
        <div className="rounded-lg border border-dashed border-gray-200 dark:border-slate-700 p-6 text-center">
          <p className="text-sm font-medium text-gray-700 dark:text-slate-200">{emptyTitle}</p>
          {emptyHint ? (
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">{emptyHint}</p>
          ) : null}
          {emptyHref && emptyCta ? (
            <Link
              href={emptyHref}
              className="inline-block mt-3 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {emptyCta}
            </Link>
          ) : null}
        </div>
      ) : (
        <div className={refreshing ? "opacity-60 transition-opacity" : "transition-opacity"}>
          {children}
        </div>
      )}
    </section>
  );
}
