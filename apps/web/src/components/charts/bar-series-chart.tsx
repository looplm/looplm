"use client";

import { useState, type ReactNode } from "react";
import { ChartFrame } from "./chart-frame";
import { PLOT_PX, barLayout, formatCount, labelIndices, niceMax, yTickValues } from "./chart-scale";

export interface BarSeries<T> {
  key: string;
  label: string;
  /** Tailwind bg-* class. Must be legible in both light and dark. */
  className: string;
  value: (d: T) => number;
}

export interface BarSeriesChartProps<T> {
  data: T[];
  /** React key and tooltip heading. */
  rowKey: (d: T) => string;
  tooltipTitle: (d: T) => string;
  xLabel: (d: T, i: number) => string;
  series: BarSeries<T>[];
  mode: "stacked" | "grouped";
  yFormat?: (v: number) => string;
  /** Lifted hover, so sibling charts can share one crosshair index. */
  hovered?: number | null;
  onHover?: (i: number | null) => void;
  /** Offset added to the reported index when several charts share one hover space. */
  hoverOffset?: number;
  tooltipExtra?: (d: T) => ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
}

/**
 * N-series bar chart, stacked or grouped.
 *
 * Hover is lifted when `hovered`/`onHover` are supplied and falls back to internal state
 * otherwise, so a single chart works standalone and a row of them can share a crosshair.
 */
export function BarSeriesChart<T>({
  data,
  rowKey,
  tooltipTitle,
  xLabel,
  series,
  mode,
  yFormat = formatCount,
  hovered,
  onHover,
  hoverOffset = 0,
  tooltipExtra,
  action,
  footer,
}: BarSeriesChartProps<T>) {
  const [ownHover, setOwnHover] = useState<number | null>(null);
  const lifted = hovered !== undefined && onHover !== undefined;
  const activeHover = lifted ? hovered : ownHover;
  const setHover = lifted ? onHover : setOwnHover;

  if (data.length === 0) return null;

  const columnTotal = (d: T) =>
    mode === "stacked"
      ? series.reduce((sum, s) => sum + Math.max(s.value(d), 0), 0)
      : Math.max(...series.map((s) => Math.max(s.value(d), 0)), 0);

  const top = niceMax(Math.max(...data.map(columnTotal), 1));
  const ticks = yTickValues(top);
  const labelled = labelIndices(data.length);
  const { gapPx, minBarPx } = barLayout(data.length);

  return (
    <ChartFrame
      yTicks={ticks.map(yFormat)}
      xLabels={data.map((d, i) => (labelled.has(i) ? xLabel(d, i) : null))}
      legend={series.map((s) => ({ label: s.label, className: s.className }))}
      action={action}
      footer={footer}
    >
      <div className="flex h-48" style={{ gap: gapPx }}>
        {data.map((d, i) => {
          const hoverIdx = i + hoverOffset;
          const isHovered = activeHover === hoverIdx;
          const dimmed = activeHover !== null && !isHovered;
          const total = columnTotal(d);
          return (
            <div
              key={rowKey(d)}
              className="flex-1 flex flex-col justify-end relative"
              style={{ minWidth: minBarPx }}
              onMouseEnter={() => setHover(hoverIdx)}
              onMouseLeave={() => setHover(null)}
            >
              {isHovered ? (
                <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                  <div className="font-medium mb-1">{tooltipTitle(d)}</div>
                  {series.map((s) => (
                    <div key={s.key} className="flex items-center gap-1">
                      <span className={`w-2 h-2 rounded-sm inline-block ${s.className}`} />
                      {yFormat(s.value(d))} {s.label.toLowerCase()}
                    </div>
                  ))}
                  {tooltipExtra ? <div className="mt-1">{tooltipExtra(d)}</div> : null}
                  <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900 dark:border-t-slate-700" />
                </div>
              ) : null}
              {total > 0 ? (
                mode === "stacked" ? (
                  <div
                    className="w-full rounded-t-sm overflow-hidden transition-opacity flex flex-col"
                    style={{
                      height: Math.round((total / top) * PLOT_PX),
                      minHeight: 4,
                      opacity: dimmed ? 0.4 : 1,
                    }}
                  >
                    {/* Rendered top-down, so the series list reads bottom-up in the stack. */}
                    {[...series].reverse().map((s, idx) => {
                      const v = Math.max(s.value(d), 0);
                      const isLast = idx === series.length - 1;
                      return (
                        <div
                          key={s.key}
                          className={`w-full ${s.className} ${isLast ? "flex-1" : ""}`}
                          style={
                            isLast
                              ? undefined
                              : { height: Math.round((v / total) * ((total / top) * PLOT_PX)) }
                          }
                        />
                      );
                    })}
                  </div>
                ) : (
                  <div
                    className="w-full flex items-end gap-[2px] transition-opacity"
                    style={{ opacity: dimmed ? 0.4 : 1 }}
                  >
                    {series.map((s) => (
                      <div
                        key={s.key}
                        className={`flex-1 rounded-t-sm ${s.className}`}
                        style={{
                          height: Math.round((Math.max(s.value(d), 0) / top) * PLOT_PX),
                          minHeight: s.value(d) > 0 ? 2 : 0,
                        }}
                      />
                    ))}
                  </div>
                )
              ) : (
                <div className="w-full" style={{ height: 0 }} />
              )}
            </div>
          );
        })}
      </div>
    </ChartFrame>
  );
}
