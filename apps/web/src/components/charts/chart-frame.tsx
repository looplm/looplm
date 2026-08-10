import type { ReactNode } from "react";
import { PLOT_H } from "./chart-scale";

export interface ChartLegendItem {
  label: string;
  /** Tailwind bg-* class for the swatch. */
  className: string;
}

export interface ChartFrameProps {
  /** Pre-formatted tick labels, ascending. The frame reverses them for top-down layout. */
  yTicks: string[];
  /** One entry per column; null suppresses that label. */
  xLabels: (string | null)[];
  yAxisWidth?: "w-8" | "w-12" | "w-14";
  legend?: ChartLegendItem[];
  /** Top-right slot, for a bucket toggle or a badge. */
  action?: ReactNode;
  footer?: ReactNode;
  /** The plot area. Must render exactly PLOT_H tall. */
  children: ReactNode;
}

/**
 * Axis chrome shared by the bar and line charts: y ticks, the plot slot, x labels
 * and the legend. Keeps the two chart types visually identical.
 */
export function ChartFrame({
  yTicks,
  xLabels,
  yAxisWidth = "w-8",
  legend,
  action,
  footer,
  children,
}: ChartFrameProps) {
  const labelInset = yAxisWidth === "w-8" ? "ml-8" : yAxisWidth === "w-12" ? "ml-12" : "ml-14";

  return (
    <div>
      {action ? <div className="flex justify-end mb-2">{action}</div> : null}
      <div className="flex">
        <div
          className={`flex flex-col justify-between ${PLOT_H} pr-2 text-xs text-gray-400 dark:text-slate-500 ${yAxisWidth} shrink-0`}
        >
          {[...yTicks].reverse().map((tick, i) => (
            <span key={`${tick}-${i}`} className="text-right leading-none">
              {tick}
            </span>
          ))}
        </div>
        <div className="flex-1 relative min-w-0">
          {children}
          <div className="flex mt-2">
            {xLabels.map((label, i) => (
              <div
                key={i}
                // The end labels are anchored rather than centred. A column is only a few
                // pixels wide on a dense axis, so a centred nowrap label at either end
                // overflows the plot and spills into the neighbouring card.
                className={`flex-1 flex min-w-0 ${
                  i === 0
                    ? "justify-start"
                    : i === xLabels.length - 1
                      ? "justify-end"
                      : "justify-center"
                }`}
              >
                {label ? (
                  // nowrap because without it a label like "05-12" breaks onto two lines.
                  <span className="text-[10px] leading-none whitespace-nowrap text-gray-400 dark:text-slate-500">
                    {label}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
      {legend && legend.length > 0 ? (
        <div
          className={`flex flex-wrap gap-4 mt-3 text-xs text-gray-500 dark:text-slate-400 ${labelInset}`}
        >
          {legend.map((item) => (
            <span key={item.label} className="flex items-center gap-1">
              <span className={`w-3 h-3 rounded inline-block ${item.className}`} />
              {item.label}
            </span>
          ))}
        </div>
      ) : null}
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  );
}
