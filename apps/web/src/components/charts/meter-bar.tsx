export interface MeterSegment {
  key: string;
  label: string;
  value: number;
  /** Tailwind bg-* class. */
  className: string;
}

export interface MeterBarProps {
  segments: MeterSegment[];
  /** Denominator. Omit to use the segment sum, i.e. a 100% stacked meter. */
  total?: number;
  height?: "h-1.5" | "h-2.5";
  showLegend?: boolean;
  className?: string;
}

/**
 * A single-value progress bar or a 100% stacked breakdown, depending on `total`.
 *
 * `JobProgressBar` in eval-shared.tsx is not reusable here: it takes an EvalJob and
 * early-returns unless the job is running.
 */
export function MeterBar({
  segments,
  total,
  height = "h-2.5",
  showLegend = false,
  className = "",
}: MeterBarProps) {
  const sum = segments.reduce((acc, s) => acc + Math.max(s.value, 0), 0);
  const denominator = total ?? sum;

  return (
    <div className={className}>
      <div
        className={`w-full ${height} rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden flex`}
      >
        {denominator > 0
          ? segments.map((s) => {
              const pct = (Math.max(s.value, 0) / denominator) * 100;
              if (pct <= 0) return null;
              return (
                <div
                  key={s.key}
                  className={s.className}
                  style={{ width: `${pct}%` }}
                  title={`${s.label}: ${s.value.toLocaleString()}`}
                />
              );
            })
          : null}
      </div>
      {showLegend ? (
        <div className="flex flex-wrap gap-3 mt-2 text-xs text-gray-500 dark:text-slate-400">
          {segments.map((s) => (
            <span key={s.key} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-sm inline-block ${s.className}`} />
              {s.label} {s.value.toLocaleString()}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
