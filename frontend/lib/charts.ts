import chartManifestData from "../data/chart-manifest.json";

export type CompanyChartSet = {
  profitability: string;
  returns: string;
  cashflow: string;
};

export type ComparisonChartSet = {
  id: string;
  left: string;
  right: string;
  charts: {
    revenue: string;
    operating_margin_pct: string;
    free_cash_flow: string;
  };
};

type ChartManifest = {
  schema_version: string;
  generated_at: string;
  companies: Record<string, CompanyChartSet>;
  comparisons: ComparisonChartSet[];
};

const manifest = chartManifestData as ChartManifest;

export function getCompanyCharts(ticker: string): CompanyChartSet | null {
  return manifest.companies[ticker] ?? null;
}

export function getComparisonCharts(
  left: string,
  right: string,
): ComparisonChartSet | null {
  return (
    manifest.comparisons.find(
      (comparison) => comparison.left === left && comparison.right === right,
    ) ?? null
  );
}
