import statsData from "../data/stats.json";

export type StatsValueKind = "money" | "percent";

export type StatsMetricDefinition = {
  label: string;
  english_label: string;
  unit: string;
  value_kind: StatsValueKind;
};

export type DescriptiveStatistics = {
  count: number;
  missing: number;
  mean: number | null;
  median: number | null;
  stddev: number | null;
  min: number | null;
  q1: number | null;
  q3: number | null;
  max: number | null;
};

export type RankingRow = {
  rank: number | null;
  ticker: string;
  name: string;
  value: number | null;
};

export type ScatterDefinition = {
  label: string;
  description: string;
  x_metric: string;
  y_metric: string;
  x_scale: "linear" | "log";
};

export type ScatterRow = {
  ticker: string;
  name: string;
  x: number;
  y: number;
};

export type ScatterExclusion = {
  ticker: string;
  reason: string;
};

export type StatsYearResult = {
  company_count: number;
  descriptive: Record<string, DescriptiveStatistics>;
  rankings: Record<
    string,
    {
      chart: string;
      rows: RankingRow[];
    }
  >;
  scatters: Record<
    string,
    {
      chart: string;
      included_count: number;
      excluded_tickers: string[];
      exclusions: ScatterExclusion[];
      rows: ScatterRow[];
    }
  >;
};

export type StatsData = {
  schema_version: string;
  generated_at: string;
  default_year: number;
  default_ranking: string;
  default_scatter: string;
  years: number[];
  metrics: Record<string, StatsMetricDefinition>;
  scatter_definitions: Record<string, ScatterDefinition>;
  results: Record<string, StatsYearResult>;
};

const data = statsData as StatsData;

export function getStatsData(): StatsData {
  return data;
}

export function formatStatsValue(
  value: number | null,
  metric: StatsMetricDefinition,
): string {
  if (value === null) {
    return "—";
  }
  const formatted = new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: metric.value_kind === "money" ? 2 : 2,
  }).format(value);
  return metric.value_kind === "percent" ? `${formatted}%` : formatted;
}
