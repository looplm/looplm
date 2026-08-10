"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ChartFrame } from "./chart-frame";
import { formatCount, labelIndices, niceMax, ratioTicks, yTickValues } from "./chart-scale";

export interface LineSeries<T> {
  key: string;
  label: string;
  /** Tailwind text-* class; drives stroke and fill through currentColor. */
  className: string;
  /** Return null for a gap. A bucket with no data is not a zero. */
  value: (d: T) => number | null;
  area?: boolean;
}

export interface LineChartProps<T> {
  data: T[];
  rowKey: (d: T) => string;
  tooltipTitle: (d: T) => string;
  xLabel: (d: T, i: number) => string;
  series: LineSeries<T>[];
  /** Fixed axis, e.g. [0, 1] for a rate. Omit to autoscale. */
  yDomain?: [number, number];
  yFormat?: (v: number) => string;
  /** Dashed reference line, e.g. a pass-rate goal. */
  target?: { value: number; label: string; className?: string };
  hovered?: number | null;
  onHover?: (i: number | null) => void;
  hoverOffset?: number;
  action?: ReactNode;
  footer?: ReactNode;
}

const VB_W = 100;
const VB_H = 100;

/**
 * Multi-series line chart in inline SVG, no dependencies.
 *
 * Two details that matter: the viewBox is stretched with preserveAspectRatio="none", so
 * every stroke needs vectorEffect="non-scaling-stroke" or it renders as a wedge; and hover
 * is handled by an overlay of transparent columns rather than by hit-testing the 2px path,
 * which keeps the interaction identical to the bar charts.
 */
export function LineChart<T>({
  data,
  rowKey,
  tooltipTitle,
  xLabel,
  series,
  yDomain,
  yFormat = formatCount,
  target,
  hovered,
  onHover,
  hoverOffset = 0,
  action,
  footer,
}: LineChartProps<T>) {
  const [ownHover, setOwnHover] = useState<number | null>(null);
  const lifted = hovered !== undefined && onHover !== undefined;
  const activeHover = lifted ? hovered : ownHover;
  const setHover = lifted ? onHover : setOwnHover;

  const { min, max, ticks } = useMemo(() => {
    if (yDomain) {
      const [lo, hi] = yDomain;
      const isRatio = lo === 0 && hi === 1;
      return { min: lo, max: hi, ticks: isRatio ? ratioTicks() : yTickValues(hi) };
    }
    const values = data
      .flatMap((d) => series.map((s) => s.value(d)))
      .filter((v): v is number => v !== null);
    const top = niceMax(Math.max(...values, 1));
    return { min: 0, max: top, ticks: yTickValues(top) };
  }, [data, series, yDomain]);

  const span = max - min || 1;
  const toX = (i: number) => (data.length === 1 ? VB_W / 2 : (i / (data.length - 1)) * VB_W);
  const toY = (v: number) => VB_H - ((v - min) / span) * VB_H;

  // Split each series into runs of consecutive non-null points, so a gap stays a gap
  // instead of being bridged by a line through missing data.
  const seriesRuns = useMemo(
    () =>
      series.map((s) => {
        const runs: { i: number; v: number }[][] = [];
        let run: { i: number; v: number }[] = [];
        data.forEach((d, i) => {
          const v = s.value(d);
          if (v === null) {
            if (run.length) runs.push(run);
            run = [];
          } else {
            run.push({ i, v });
          }
        });
        if (run.length) runs.push(run);
        return { series: s, runs };
      }),
    [data, series],
  );

  if (data.length === 0) return null;

  const labelled = labelIndices(data.length);

  return (
    <ChartFrame
      yTicks={ticks.map(yFormat)}
      xLabels={data.map((d, i) => (labelled.has(i) ? xLabel(d, i) : null))}
      yAxisWidth="w-12"
      legend={series.map((s) => ({
        label: s.label,
        // The legend swatch needs a bg-* class while the line uses text-*.
        className: s.className.replace("text-", "bg-"),
      }))}
      action={action}
      footer={footer}
    >
      <div className="relative h-48">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          preserveAspectRatio="none"
          className="w-full h-full overflow-visible"
          aria-hidden="true"
        >
          {ticks.map((t) => (
            <line
              key={`grid-${t}`}
              x1={0}
              x2={VB_W}
              y1={toY(t)}
              y2={toY(t)}
              className="text-gray-100 dark:text-slate-800"
              stroke="currentColor"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {target ? (
            <line
              x1={0}
              x2={VB_W}
              y1={toY(target.value)}
              y2={toY(target.value)}
              className={target.className ?? "text-emerald-400"}
              stroke="currentColor"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {seriesRuns.map(({ series: s, runs }) => {
            return (
              <g key={s.key} className={s.className}>
                {runs.map((points, ri) => {
                  const path = points
                    .map((p, pi) => `${pi === 0 ? "M" : "L"}${toX(p.i).toFixed(2)},${toY(p.v).toFixed(2)}`)
                    .join(" ");
                  return (
                    <g key={ri}>
                      {s.area && points.length > 1 ? (
                        <path
                          d={`${path} L${toX(points[points.length - 1].i).toFixed(2)},${VB_H} L${toX(points[0].i).toFixed(2)},${VB_H} Z`}
                          fill="currentColor"
                          fillOpacity={0.12}
                          stroke="none"
                        />
                      ) : null}
                      <path
                        d={path}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        vectorEffect="non-scaling-stroke"
                      />
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
        {/* Point markers live outside the SVG on purpose. The viewBox is stretched with
            preserveAspectRatio="none", which distorts shape geometry: an SVG <circle>
            renders as a flat ellipse, and vectorEffect only corrects stroke width, not
            geometry. Positioning them as HTML by percentage keeps them round at any size. */}
        {seriesRuns.map(({ series: s, runs }) =>
          runs.map((points, ri) =>
            // A lone point would be invisible without a marker, and endpoint markers show
            // where a gap begins.
            points.length === 1 || runs.length > 1
              ? points.map((p) => (
                  <span
                    key={`${s.key}-${ri}-${p.i}`}
                    className={`absolute w-1.5 h-1.5 rounded-full bg-current pointer-events-none ${s.className}`}
                    style={{
                      left: `${toX(p.i)}%`,
                      top: `${toY(p.v)}%`,
                      transform: "translate(-50%, -50%)",
                    }}
                  />
                ))
              : null,
          ),
        )}
        <div className="absolute inset-0 flex">
          {data.map((d, i) => {
            const hoverIdx = i + hoverOffset;
            const isHovered = activeHover === hoverIdx;
            return (
              <div
                key={rowKey(d)}
                className="flex-1 relative"
                onMouseEnter={() => setHover(hoverIdx)}
                onMouseLeave={() => setHover(null)}
              >
                {isHovered ? (
                  <>
                    <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300 dark:bg-slate-600" />
                    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap shadow-lg pointer-events-none">
                      <div className="font-medium mb-1">{tooltipTitle(d)}</div>
                      {series.map((s) => {
                        const v = s.value(d);
                        return (
                          <div key={s.key} className="flex items-center gap-1">
                            <span
                              className={`w-2 h-2 rounded-sm inline-block ${s.className.replace("text-", "bg-")}`}
                            />
                            {v === null ? "no data" : yFormat(v)} {s.label.toLowerCase()}
                          </div>
                        );
                      })}
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900 dark:border-t-slate-700" />
                    </div>
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </ChartFrame>
  );
}
