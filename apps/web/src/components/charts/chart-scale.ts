/**
 * Shared axis maths for the hand-rolled charts.
 *
 * The values here are lifted verbatim from the original chart in
 * `app/(app)/feedback/feedback-chart.tsx` so anything built on these primitives lines up
 * pixel for pixel with the charts already shipped on Feedback, Dashboard and Costs.
 */

/** Plot height in pixels. Must stay in sync with PLOT_H. */
export const PLOT_PX = 192;

/** Tailwind class for the plot height. Must stay in sync with PLOT_PX. */
export const PLOT_H = "h-48";

/** Round a maximum up to a readable axis top. */
export function niceMax(max: number): number {
  if (!Number.isFinite(max) || max <= 0) return 5;
  return max <= 5 ? 5 : Math.ceil(max / 5) * 5;
}

/** Five ascending ticks from 0 to `top`, inclusive. */
export function yTickValues(top: number): number[] {
  return [0, Math.round(top / 4), Math.round(top / 2), Math.round((top * 3) / 4), top];
}

/** Five ascending ratio ticks, for a 0..1 axis. */
export function ratioTicks(): number[] {
  return [0, 0.25, 0.5, 0.75, 1];
}

/**
 * Show roughly `target` x-axis labels, skipping the rest.
 * Dense axes become unreadable long before they become inaccurate.
 */
export function labelInterval(count: number, target = 6): number {
  return Math.max(1, Math.floor(count / target));
}

/**
 * Which column indices get an x-axis label.
 *
 * The final column is labelled so the axis states where it ends, but only when it is far
 * enough from the previous label to not overlap it. Labelling it unconditionally collides
 * whenever the count is not a clean multiple of the interval.
 */
export function labelIndices(count: number, target = 6): Set<number> {
  const interval = labelInterval(count, target);
  const indices = new Set<number>();
  for (let i = 0; i < count; i += interval) indices.add(i);
  const last = count - 1;
  const previous = Math.max(...indices);
  if (last - previous >= Math.ceil(interval / 2)) indices.add(last);
  return indices;
}

export interface BarLayout {
  gapPx: number;
  minBarPx: number;
}

/**
 * Bar gap and minimum width, scaled to the column count.
 *
 * A fixed 6px minimum plus a 3px gap is comfortable for a few weeks of data but forces a
 * hard minimum width past the container once there are dozens of columns, which makes the
 * chart overflow its card. These bounds keep 90+ daily columns inside a half-width card.
 */
export function barLayout(count: number): BarLayout {
  if (count <= 20) return { gapPx: 3, minBarPx: 6 };
  if (count <= 60) return { gapPx: 2, minBarPx: 3 };
  return { gapPx: 1, minBarPx: 1 };
}

/** Percentage formatter for rate axes and tooltips. */
export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Thousands-separated integer, for count axes and tooltips. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return Math.round(value).toLocaleString();
}
