import financialsData from "../data/financials.json";

export type FinancialMetrics = {
  revenue: number | null;
  operating_income: number | null;
  net_income: number | null;
  total_assets: number | null;
  equity: number | null;
  operating_cash_flow: number | null;
  investing_cash_flow: number | null;
  roe_pct: number | null;
};

export type CalculatedMetrics = {
  revenue_yoy_pct: number | null;
  operating_margin_pct: number | null;
  free_cash_flow: number | null;
  revenue_cagr_3y_pct: number | null;
};

export type SourceDocument = {
  document_id: string | null;
  document_type: string;
  filed_at: string | null;
  url: string | null;
};

export type FinancialPeriod = {
  fiscal_year: number;
  fiscal_year_end: string | null;
  accounting_standard: string;
  consolidated: boolean;
  metrics: FinancialMetrics;
  calculated_metrics: CalculatedMetrics;
  source_document: SourceDocument;
  fetched_at: string;
};

export type FinancialCompany = {
  ticker: string;
  name: string;
  edinet_code: string;
  currency: string;
  periods: FinancialPeriod[];
};

export type FinancialsData = {
  schema_version: string;
  generated_at: string;
  companies: FinancialCompany[];
};

const data = financialsData as FinancialsData;

export function listFinancialCompanies(): FinancialCompany[] {
  return data.companies;
}

export function getFinancialCompany(ticker: string): FinancialCompany | null {
  return data.companies.find((company) => company.ticker === ticker) ?? null;
}

export function getFinancialsGeneratedAt(): string {
  return data.generated_at;
}

export function formatMoneyInMillions(value: number | null): string {
  if (value === null) {
    return "—";
  }

  return new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: 0,
  }).format(value / 1_000_000);
}

export function formatPercent(value: number | null): string {
  if (value === null) {
    return "—";
  }

  return `${new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: 2,
  }).format(value)}%`;
}

export function formatDate(value: string | null): string {
  if (value === null) {
    return "—";
  }

  const [year, month, day] = value.split("-");
  if (!year || !month || !day) {
    return value;
  }

  return `${year}/${month}/${day}`;
}

export function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Tokyo",
  }).format(date);
}
