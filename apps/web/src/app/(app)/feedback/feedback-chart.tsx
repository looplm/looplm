interface TrendBarChartProps {
  title: string;
  data: { date: string; positive: number; negative: number; total: number }[];
  positiveLabel: string;
  negativeLabel: string;
  hoveredBar: number | null;
  hoverOffset: number;
  onHover: (index: number | null) => void;
}

export function TrendBarChart({
  title,
  data,
  positiveLabel,
  negativeLabel,
  hoveredBar,
  hoverOffset,
  onHover,
}: TrendBarChartProps) {
  if (data.length === 0) return null;

  const maxTotal = Math.max(...data.map((d) => d.total), 1);
  const niceMax = maxTotal <= 5 ? 5 : Math.ceil(maxTotal / 5) * 5;
  const yTicks = [0, Math.round(niceMax / 4), Math.round(niceMax / 2), Math.round((niceMax * 3) / 4), niceMax];
  const labelInterval = Math.max(1, Math.floor(data.length / 6));

  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold mb-3">{title}</h2>
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
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
                const barPx = Math.round((t.total / niceMax) * 192);
                const posPx = t.total > 0 ? Math.round((t.positive / t.total) * barPx) : 0;
                const negPx = barPx - posPx;
                const hoverIdx = i + hoverOffset;
                return (
                  <div
                    key={t.date}
                    className="flex-1 flex flex-col justify-end relative"
                    style={{ minWidth: 6 }}
                    onMouseEnter={() => onHover(hoverIdx)}
                    onMouseLeave={() => onHover(null)}
                  >
                    {hoveredBar === hoverIdx && (
                      <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                        <div className="font-medium mb-1">{t.date}</div>
                        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-green-500 inline-block" /> {t.positive} {positiveLabel.toLowerCase()}</div>
                        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500 inline-block" /> {t.negative} {negativeLabel.toLowerCase()}</div>
                        <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900 dark:border-t-slate-700" />
                      </div>
                    )}
                    {t.total > 0 ? (
                      <div
                        className="w-full rounded-t-sm overflow-hidden transition-opacity flex flex-col"
                        style={{
                          height: barPx,
                          minHeight: 4,
                          opacity: hoveredBar === null || hoveredBar === hoverIdx ? 1 : 0.4,
                        }}
                      >
                        <div className="w-full bg-red-500" style={{ height: negPx }} />
                        <div className="w-full bg-green-500 flex-1" />
                      </div>
                    ) : (
                      <div className="w-full" style={{ height: 0 }} />
                    )}
                  </div>
                );
              })}
            </div>
            {/* X-axis labels */}
            <div className="flex mt-2">
              {data.map((t, i) => (
                <div key={t.date} className="flex-1 text-center" style={{ minWidth: 6 }}>
                  {i % labelInterval === 0 || i === data.length - 1 ? (
                    <span className="text-[10px] text-gray-400 dark:text-slate-500">
                      {t.date.slice(5)}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flex gap-4 mt-3 text-xs text-gray-500 dark:text-slate-400 ml-8">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded bg-green-500 inline-block" /> {positiveLabel}
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded bg-red-500 inline-block" /> {negativeLabel}
          </span>
        </div>
      </div>
    </div>
  );
}
