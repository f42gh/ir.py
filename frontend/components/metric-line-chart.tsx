export type ChartSeries = {
  label: string;
  color: string;
  values: Array<number | null>;
};

type MetricLineChartProps = {
  title: string;
  years: number[];
  series: ChartSeries[];
  valueKind: "money" | "percent";
};

const WIDTH = 720;
const HEIGHT = 240;
const PLOT_LEFT = 64;
const PLOT_RIGHT = 700;
const PLOT_TOP = 18;
const PLOT_BOTTOM = 196;

function formatAxisValue(value: number, kind: MetricLineChartProps["valueKind"]): string {
  if (kind === "percent") {
    return `${new Intl.NumberFormat("ja-JP", {
      maximumFractionDigits: 1,
    }).format(value)}%`;
  }
  return new Intl.NumberFormat("ja-JP", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatExactValue(value: number, kind: MetricLineChartProps["valueKind"]): string {
  const formatted = new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: kind === "percent" ? 2 : 0,
  }).format(value);
  return kind === "percent" ? `${formatted}%` : `${formatted}百万円`;
}

function lineSegments(points: Array<{ x: number; y: number } | null>): string[] {
  const segments: string[] = [];
  let current: string[] = [];
  for (const point of points) {
    if (point === null) {
      if (current.length > 1) {
        segments.push(current.join(" "));
      }
      current = [];
      continue;
    }
    current.push(`${point.x},${point.y}`);
  }
  if (current.length > 1) {
    segments.push(current.join(" "));
  }
  return segments;
}

export function MetricLineChart({
  title,
  years,
  series,
  valueKind,
}: MetricLineChartProps) {
  const allValues = series.flatMap((item) =>
    item.values.filter((value): value is number => value !== null),
  );

  if (years.length === 0 || allValues.length === 0) {
    return (
      <section className="border border-zinc-300 p-4">
        <h3 className="text-sm font-semibold text-zinc-950">{title}</h3>
        <p className="mt-8 text-sm text-zinc-400">表示できるデータがありません。</p>
      </section>
    );
  }

  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  let min = Math.min(0, rawMin);
  let max = Math.max(0, rawMax);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const padding = (max - min) * 0.08;
  min = rawMin < 0 ? min - padding : min;
  max += padding;

  const xForIndex = (index: number) =>
    years.length === 1
      ? (PLOT_LEFT + PLOT_RIGHT) / 2
      : PLOT_LEFT + (index / (years.length - 1)) * (PLOT_RIGHT - PLOT_LEFT);
  const yForValue = (value: number) =>
    PLOT_BOTTOM - ((value - min) / (max - min)) * (PLOT_BOTTOM - PLOT_TOP);
  const ticks = Array.from({ length: 5 }, (_, index) => min + ((max - min) * index) / 4);

  return (
    <section className="border border-zinc-300 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-zinc-950">{title}</h3>
        <div className="flex flex-wrap gap-3 text-[11px] text-zinc-600">
          {series.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-4" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="mt-3 h-auto w-full"
        role="img"
        aria-label={`${title}の年度推移`}
      >
        {ticks.map((tick) => {
          const y = yForValue(tick);
          return (
            <g key={tick}>
              <line
                x1={PLOT_LEFT}
                x2={PLOT_RIGHT}
                y1={y}
                y2={y}
                stroke="#e4e4e7"
                strokeWidth="1"
              />
              <text
                x={PLOT_LEFT - 8}
                y={y + 4}
                textAnchor="end"
                fontSize="10"
                fill="#71717a"
              >
                {formatAxisValue(tick, valueKind)}
              </text>
            </g>
          );
        })}

        {years.map((year, index) => (
          <text
            key={year}
            x={xForIndex(index)}
            y={PLOT_BOTTOM + 24}
            textAnchor="middle"
            fontSize="10"
            fill="#71717a"
          >
            FY{String(year).slice(-2)}
          </text>
        ))}

        {series.map((item) => {
          const points = item.values.map((value, index) =>
            value === null
              ? null
              : { x: xForIndex(index), y: yForValue(value) },
          );
          return (
            <g key={item.label}>
              {lineSegments(points).map((segment, index) => (
                <polyline
                  key={`${item.label}-${index}`}
                  points={segment}
                  fill="none"
                  stroke={item.color}
                  strokeWidth="2.5"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {points.map((point, index) =>
                point === null ? null : (
                  <circle
                    key={`${item.label}-${years[index]}`}
                    cx={point.x}
                    cy={point.y}
                    r="3.5"
                    fill="#ffffff"
                    stroke={item.color}
                    strokeWidth="2"
                  >
                    <title>
                      {`${item.label} FY${years[index]}: ${formatExactValue(item.values[index]!, valueKind)}`}
                    </title>
                  </circle>
                ),
              )}
            </g>
          );
        })}
      </svg>
    </section>
  );
}
