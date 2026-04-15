import { useState } from "react";

interface TrendData {
  date: string;
  total: number;
  unique_users: number;
}

interface UsageTrendChartProps {
  data: TrendData[];
}

export function UsageTrendChart({ data }: UsageTrendChartProps) {
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);

  if (data.length === 0) return null;

  const maxVal = Math.max(...data.map((d) => d.total), ...data.map((d) => d.unique_users), 1);
  const niceMax = maxVal <= 5 ? 5 : Math.ceil(maxVal / 5) * 5;
  const yTicks = [0, Math.round(niceMax / 4), Math.round(niceMax / 2), Math.round((niceMax * 3) / 4), niceMax];
  const labelInterval = Math.max(1, Math.floor(data.length / 6));

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
      <h2 className="text-lg font-semibold mb-3">Usage Trends</h2>
      <div className="flex">
        {/* Y-axis */}
        <div className="flex flex-col justify-between h-48 pr-2 text-xs text-gray-400 dark:text-slate-500 w-8 shrink-0">
          {[...yTicks].reverse().map((tick) => (
            <span key={tick} className="text-right leading-none">{tick}</span>
          ))}
        </div>
        {/* Bars */}
        <div className="flex-1 relative">
          <div className="flex gap-[3px] h-48">
            {data.map((t, i) => {
              const tracesPx = Math.round((t.total / niceMax) * 192);
              const usersPx = Math.round((t.unique_users / niceMax) * 192);
              return (
                <div
                  key={t.date}
                  className="flex-1 flex justify-center gap-[2px] items-end relative"
                  style={{ minWidth: 12 }}
                  onMouseEnter={() => setHoveredBar(i)}
                  onMouseLeave={() => setHoveredBar(null)}
                >
                  {hoveredBar === i && (
                    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                      <div className="font-medium mb-1">{t.date} ({new Date(t.date + "T00:00:00").toLocaleDateString("en-US", { weekday: "short" })})</div>
                      <div className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-sm bg-indigo-500 inline-block" /> {t.total} traces
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-sm bg-violet-400 inline-block" /> {t.unique_users} users
                      </div>
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900 dark:border-t-slate-700" />
                    </div>
                  )}
                  <div
                    className="w-[45%] bg-indigo-500 rounded-t-sm transition-opacity"
                    style={{
                      height: tracesPx,
                      minHeight: t.total > 0 ? 4 : 0,
                      opacity: hoveredBar === null || hoveredBar === i ? 1 : 0.4,
                    }}
                  />
                  <div
                    className="w-[45%] bg-violet-400 rounded-t-sm transition-opacity"
                    style={{
                      height: usersPx,
                      minHeight: t.unique_users > 0 ? 4 : 0,
                      opacity: hoveredBar === null || hoveredBar === i ? 1 : 0.4,
                    }}
                  />
                </div>
              );
            })}
          </div>
          {/* X-axis labels */}
          <div className="flex mt-2">
            {data.map((t, i) => (
              <div key={t.date} className="flex-1 text-center" style={{ minWidth: 12 }}>
                {i % labelInterval === 0 || i === data.length - 1 ? (
                  <div className="flex flex-col items-center">
                    <span className="text-[11px] text-gray-400 dark:text-slate-500">
                      {t.date.slice(5)}
                    </span>
                    <span className="text-[11px] text-gray-400 dark:text-slate-500">
                      {new Date(t.date + "T00:00:00").toLocaleDateString("en-US", { weekday: "short" })}
                    </span>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex gap-4 mt-3 text-xs text-gray-500 dark:text-slate-400 ml-8">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-indigo-500 inline-block" /> Traces
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-violet-400 inline-block" /> Users
        </span>
      </div>
    </div>
  );
}
