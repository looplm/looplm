interface SparklineProps {
  data: number[];
  /** Tailwind text-color class; drives both the line and its faint fill via currentColor. */
  className?: string;
}

/** Tiny dependency-free trend line. Autoscales to its own min/max so shape is visible. */
export function Sparkline({ data, className = "text-indigo-500" }: SparklineProps) {
  if (!data || data.length < 2) return null;

  const w = 100;
  const h = 28;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min;
  const n = data.length;

  const pts = data.map((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = range === 0 ? h / 2 : h - ((v - min) / range) * (h - 2) - 1;
    return [x, y] as const;
  });

  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className={`w-full h-7 ${className}`}
      aria-hidden="true"
    >
      <path d={area} fill="currentColor" fillOpacity={0.12} stroke="none" />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
