"use client";

import { Fragment, useEffect, useState } from "react";
import { getCostsOverview } from "@/lib/api";
import type { CostsOverviewResponse } from "@/lib/api-types/costs";
import { useGlobalFilters } from "@/components/global-filters-context";

function formatCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// Friendly labels for known platform function names; falls back to the raw name.
const FUNCTION_LABELS: Record<string, string> = {
  eval_root_cause: "Root-cause analysis",
  eval_pattern_classifier: "Failure-pattern classifier",
};

function functionLabel(name: string): string {
  return FUNCTION_LABELS[name] ?? name;
}

type CostView = "all" | "application" | "platform";

export default function CostsPage() {
  const [data, setData] = useState<CostsOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [costView, setCostView] = useState<CostView>("all");
  const { startDate, endDate, environment, userFilterMode, filteredUsers, traceNames } = useGlobalFilters();

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = {};
    if (startDate) params.start_date = new Date(startDate).toISOString();
    if (endDate) params.end_date = new Date(endDate).toISOString();
    if (!startDate) params.days = "30";
    if (environment && environment !== "all") params.environment = environment;
    if (filteredUsers.length > 0) {
      const key = userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
      params[key] = filteredUsers.join(",");
    }

    getCostsOverview(params)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [startDate, endDate, environment, userFilterMode, filteredUsers, traceNames]);

  const showApp = costView === "all" || costView === "application";
  const showPlatform = costView === "all" || costView === "platform";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Costs</h1>
        <div className="flex items-center rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-0.5">
          {(["all", "application", "platform"] as const).map((view) => (
            <button
              key={view}
              onClick={() => setCostView(view)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                costView === view
                  ? "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300"
                  : "text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300"
              }`}
            >
              {view === "all" ? "All" : view === "application" ? "Application" : "Platform"}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="text-sm text-gray-400 dark:text-slate-500 py-12 text-center">Loading cost data...</div>
      ) : data ? (
        <div className="space-y-6">
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Total Cost"
              value={formatCost(
                costView === "application" ? data.app_cost_usd
                  : costView === "platform" ? data.platform_cost_usd
                  : data.total_cost_usd
              )}
              highlight
            />
            {showApp && (
              <StatCard label="Application Cost" value={formatCost(data.app_cost_usd)} sub={`${data.total_app_requests.toLocaleString()} LLM calls`} />
            )}
            {showPlatform && (
              <StatCard label="Platform Cost" value={formatCost(data.platform_cost_usd)} sub={`${data.total_platform_requests.toLocaleString()} requests`} />
            )}
            <StatCard
              label="Total Tokens"
              value={formatTokens(
                (showApp ? data.total_app_tokens : 0) + (showPlatform ? data.total_platform_tokens : 0)
              )}
              sub={
                costView === "all"
                  ? `${formatTokens(data.total_app_tokens)} app + ${formatTokens(data.total_platform_tokens)} platform`
                  : undefined
              }
            />
          </div>

          {/* Trend chart */}
          {data.trend.length > 0 && <CostTrendChart data={data.trend} costView={costView} />}

          {/* Breakdown tables */}
          <div className={`grid grid-cols-1 ${showApp && showPlatform ? "lg:grid-cols-2" : ""} gap-6`}>
            {/* App costs by model */}
            {showApp && <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-5">
              <h3 className="text-sm font-semibold mb-3">Application Costs by Model</h3>
              {data.app_by_model.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 dark:text-slate-400 text-xs">
                        <th className="pb-2 font-medium">Model</th>
                        <th className="pb-2 font-medium text-right">Calls</th>
                        <th className="pb-2 font-medium text-right">Tokens</th>
                        <th className="pb-2 font-medium text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.app_by_model.map((m) => (
                        <tr key={m.model} className="border-t border-gray-50 dark:border-slate-800">
                          <td className="py-2 font-mono text-xs">{m.model}</td>
                          <td className="py-2 text-right">{m.request_count.toLocaleString()}</td>
                          <td className="py-2 text-right text-gray-500 dark:text-slate-400">
                            {formatTokens(m.input_tokens + m.output_tokens)}
                          </td>
                          <td className="py-2 text-right font-medium">{formatCost(m.cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-gray-400 dark:text-slate-500">No application LLM calls with token data found.</p>
              )}
            </div>}

            {/* Platform costs by service */}
            {showPlatform && <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-5">
              <h3 className="text-sm font-semibold mb-3">Platform Costs by Service</h3>
              {data.platform_by_service.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 dark:text-slate-400 text-xs">
                        <th className="pb-2 font-medium">Service</th>
                        <th className="pb-2 font-medium text-right">Requests</th>
                        <th className="pb-2 font-medium text-right">Tokens</th>
                        <th className="pb-2 font-medium text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.platform_by_service.map((s) => (
                        <Fragment key={s.service_name}>
                          <tr className="border-t border-gray-50 dark:border-slate-800">
                            <td className="py-2 font-mono text-xs font-medium">{s.service_name}</td>
                            <td className="py-2 text-right">{s.request_count.toLocaleString()}</td>
                            <td className="py-2 text-right text-gray-500 dark:text-slate-400">
                              {formatTokens(s.input_tokens + s.output_tokens)}
                            </td>
                            <td className="py-2 text-right font-medium">{formatCost(s.cost_usd)}</td>
                          </tr>
                          {s.by_detail && s.by_detail.length > 1 && (() => {
                            const hasMultipleFns = new Set(s.by_detail!.map((d) => d.function_name)).size > 1;
                            return s.by_detail!.map((d) => (
                              <tr key={`${s.service_name}-${d.function_name}-${d.model}`} className="border-t border-gray-50/50 dark:border-slate-800/50">
                                <td className="py-1.5 pl-4 font-mono text-xs text-gray-400 dark:text-slate-500">
                                  {hasMultipleFns ? `${functionLabel(d.function_name)} · ${d.model}` : d.model}
                                </td>
                                <td className="py-1.5 text-right text-xs text-gray-400 dark:text-slate-500">{d.request_count.toLocaleString()}</td>
                                <td className="py-1.5 text-right text-xs text-gray-400 dark:text-slate-500">
                                  {formatTokens(d.input_tokens + d.output_tokens)}
                                </td>
                                <td className="py-1.5 text-right text-xs text-gray-400 dark:text-slate-500">{formatCost(d.cost_usd)}</td>
                              </tr>
                            ));
                          })()}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-gray-400 dark:text-slate-500">No platform LLM usage recorded.</p>
              )}
            </div>}
          </div>

          {/* Empty state */}
          {data.total_app_requests === 0 && data.total_platform_requests === 0 && (
            <div className="text-center py-12 text-gray-400 dark:text-slate-500">
              <p className="text-sm">No LLM cost data found for the selected period.</p>
              <p className="text-xs mt-1">
                Application costs are calculated from synced trace spans. Platform costs are tracked automatically.
              </p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border px-5 py-4 ${
        highlight
          ? "bg-indigo-50 dark:bg-indigo-950/30 border-indigo-200 dark:border-indigo-800"
          : "bg-white dark:bg-slate-900 border-gray-100 dark:border-slate-800"
      }`}
    >
      <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">{label}</div>
      <div className="text-2xl font-bold">{value}</div>
      {sub && <div className="text-xs text-gray-400 dark:text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function CostTrendChart({
  data,
  costView,
}: {
  data: { date: string; app_cost_usd: number; platform_cost_usd: number; total_cost_usd: number; app_requests: number; platform_requests: number }[];
  costView: CostView;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  const showApp = costView === "all" || costView === "application";
  const showPlatform = costView === "all" || costView === "platform";

  const maxCost = Math.max(...data.map((d) =>
    (showApp ? d.app_cost_usd : 0) + (showPlatform ? d.platform_cost_usd : 0)
  ), 0.001);
  const niceMax = maxCost <= 0.01 ? 0.01 : Math.ceil(maxCost * 100) / 100;
  const yTicks = [0, niceMax / 4, niceMax / 2, (niceMax * 3) / 4, niceMax];
  const labelInterval = Math.max(1, Math.floor(data.length / 8));

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
      <h3 className="text-sm font-semibold mb-3">Daily Cost</h3>
      <div className="flex">
        {/* Y-axis */}
        <div className="flex flex-col justify-between h-44 pr-2 text-xs text-gray-400 dark:text-slate-500 w-14 shrink-0">
          {[...yTicks].reverse().map((tick, i) => (
            <span key={i} className="text-right leading-none">
              {formatCost(tick)}
            </span>
          ))}
        </div>
        {/* Stacked bars */}
        <div className="flex-1 relative">
          <div className="flex gap-[3px] h-44">
            {data.map((d, i) => {
              const appH = showApp && niceMax > 0 ? Math.round((d.app_cost_usd / niceMax) * 176) : 0;
              const platH = showPlatform && niceMax > 0 ? Math.round((d.platform_cost_usd / niceMax) * 176) : 0;
              return (
                <div
                  key={d.date}
                  className="flex-1 flex justify-center items-end relative"
                  style={{ minWidth: 8 }}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered(null)}
                >
                  {hovered === i && (
                    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                      <div className="font-medium mb-1">{d.date}</div>
                      <div>Total: {formatCost((showApp ? d.app_cost_usd : 0) + (showPlatform ? d.platform_cost_usd : 0))}</div>
                      {showApp && (
                        <div className="flex items-center gap-1 text-gray-300">
                          <span className="w-2 h-2 rounded-sm bg-indigo-500 inline-block" />
                          App: {formatCost(d.app_cost_usd)} ({d.app_requests} calls)
                        </div>
                      )}
                      {showPlatform && (
                        <div className="flex items-center gap-1 text-gray-300">
                          <span className="w-2 h-2 rounded-sm bg-emerald-500 inline-block" />
                          Platform: {formatCost(d.platform_cost_usd)} ({d.platform_requests} req)
                        </div>
                      )}
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900 dark:border-t-slate-700" />
                    </div>
                  )}
                  {/* Stacked bar: app on bottom, platform on top */}
                  <div className="w-[80%] flex flex-col-reverse">
                    {showApp && (
                      <div
                        className={`bg-indigo-500 transition-opacity ${!showPlatform || platH === 0 ? "rounded-t-sm" : ""} rounded-b-sm`}
                        style={{
                          height: appH,
                          minHeight: d.app_cost_usd > 0 ? 2 : 0,
                          opacity: hovered === null || hovered === i ? 1 : 0.4,
                        }}
                      />
                    )}
                    {showPlatform && (
                      <div
                        className={`bg-emerald-500 transition-opacity rounded-t-sm ${!showApp || appH === 0 ? "rounded-b-sm" : ""}`}
                        style={{
                          height: platH,
                          minHeight: d.platform_cost_usd > 0 ? 2 : 0,
                          opacity: hovered === null || hovered === i ? 1 : 0.4,
                        }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {/* X-axis labels */}
          <div className="flex mt-2">
            {data.map((d, i) => (
              <div key={d.date} className="flex-1 text-center" style={{ minWidth: 8 }}>
                {i % labelInterval === 0 || i === data.length - 1 ? (
                  <span className="text-[10px] text-gray-400 dark:text-slate-500">
                    {d.date.slice(5)}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
      {/* Legend */}
      <div className="flex gap-4 mt-3 text-xs text-gray-500 dark:text-slate-400 ml-14">
        {showApp && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded bg-indigo-500 inline-block" /> Application
          </span>
        )}
        {showPlatform && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded bg-emerald-500 inline-block" /> Platform
          </span>
        )}
      </div>
    </div>
  );
}
