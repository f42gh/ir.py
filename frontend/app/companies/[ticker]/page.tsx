import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { MetricLineChart } from "../../../components/metric-line-chart";
import { StaticMetricChart } from "../../../components/static-metric-chart";
import { getCompanyCharts } from "../../../lib/charts";
import {
  formatDate,
  formatMoneyInMillions,
  formatPercent,
  formatTimestamp,
  getFinancialCompany,
  getFinancialsGeneratedAt,
  listFinancialCompanies,
  type FinancialPeriod,
} from "../../../lib/financials";

type CompanyPageProps = {
  params: Promise<{ ticker: string }>;
};

type MetricCard = {
  label: string;
  value: string;
  unit?: string;
};

function toMillions(value: number | null): number | null {
  return value === null ? null : value / 1_000_000;
}

export function generateStaticParams() {
  return listFinancialCompanies().map((company) => ({ ticker: company.ticker }));
}

export async function generateMetadata({ params }: CompanyPageProps): Promise<Metadata> {
  const { ticker } = await params;
  const company = getFinancialCompany(decodeURIComponent(ticker));

  return company
    ? {
        title: `${company.name} 財務詳細`,
        description: `${company.name}の直近5年度の財務データ`,
      }
    : { title: "企業が見つかりません" };
}

function buildLatestMetrics(period: FinancialPeriod): MetricCard[] {
  return [
    { label: "売上高", value: formatMoneyInMillions(period.metrics.revenue), unit: "百万円" },
    {
      label: "営業利益",
      value: formatMoneyInMillions(period.metrics.operating_income),
      unit: "百万円",
    },
    { label: "純利益", value: formatMoneyInMillions(period.metrics.net_income), unit: "百万円" },
    {
      label: "営業利益率",
      value: formatPercent(period.calculated_metrics.operating_margin_pct),
    },
    { label: "ROE", value: formatPercent(period.metrics.roe_pct) },
    {
      label: "営業CF",
      value: formatMoneyInMillions(period.metrics.operating_cash_flow),
      unit: "百万円",
    },
    {
      label: "FCF",
      value: formatMoneyInMillions(period.calculated_metrics.free_cash_flow),
      unit: "百万円",
    },
  ];
}

export default async function CompanyPage({ params }: CompanyPageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = decodeURIComponent(rawTicker);
  const company = getFinancialCompany(ticker);

  if (!company) {
    notFound();
  }

  const periods = [...company.periods].sort((a, b) => a.fiscal_year - b.fiscal_year);
  const staticCharts = getCompanyCharts(ticker);
  const latestPeriod = periods.at(-1);
  if (!latestPeriod) {
    notFound();
  }

  const latestMetrics = buildLatestMetrics(latestPeriod);

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
      <nav className="flex items-center justify-between gap-4">
        <Link
          href="/"
          className="inline-flex text-sm text-zinc-600 underline decoration-zinc-300 underline-offset-4 hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-950"
        >
          ← 企業一覧へ戻る
        </Link>
        <Link
          href={`/compare?left=${encodeURIComponent(company.ticker)}`}
          className="inline-flex text-sm font-medium text-zinc-950 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-950"
        >
          2社比較 →
        </Link>
      </nav>

      <header className="mt-8 border-b border-zinc-300 pb-8">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="font-mono text-sm text-zinc-500">{company.ticker}</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950 sm:text-4xl">
              {company.name}
            </h1>
            <p className="mt-3 text-sm text-zinc-600">
              EDINETコード {company.edinet_code} ・ {company.currency} ・ 連結
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:text-right">
            <div>
              <dt className="text-zinc-500">最新年度</dt>
              <dd className="mt-1 font-medium text-zinc-950">FY{latestPeriod.fiscal_year}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">会計基準</dt>
              <dd className="mt-1 font-medium text-zinc-950">
                {latestPeriod.accounting_standard}
              </dd>
            </div>
          </dl>
        </div>
      </header>

      <section className="mt-10" aria-labelledby="latest-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="latest-heading" className="text-lg font-semibold text-zinc-950">
            FY{latestPeriod.fiscal_year} 主要指標
          </h2>
          <p className="text-xs text-zinc-500">金額単位：百万円</p>
        </div>

        <dl className="mt-4 grid border-l border-t border-zinc-300 sm:grid-cols-2 lg:grid-cols-4">
          {latestMetrics.map((metric) => (
            <div key={metric.label} className="border-r border-b border-zinc-300 p-5">
              <dt className="text-sm text-zinc-500">{metric.label}</dt>
              <dd className="mt-3 font-mono text-2xl font-medium tracking-tight text-zinc-950">
                {metric.value}
              </dd>
              {metric.unit ? <p className="mt-1 text-xs text-zinc-400">{metric.unit}</p> : null}
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-12" aria-labelledby="charts-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="charts-heading" className="text-lg font-semibold text-zinc-950">
            5年度グラフ
          </h2>
          <p className="text-xs text-zinc-500">金額単位：百万円</p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {staticCharts ? (
            <>
              <StaticMetricChart
                title="売上高・営業利益"
                src={staticCharts.profitability}
                alt={`${company.name}の売上高と営業利益の5年度推移`}
              />
              <StaticMetricChart
                title="営業利益率・ROE"
                src={staticCharts.returns}
                alt={`${company.name}の営業利益率とROEの5年度推移`}
              />
              <div className="lg:col-span-2">
                <StaticMetricChart
                  title="営業キャッシュフロー・フリーキャッシュフロー"
                  src={staticCharts.cashflow}
                  alt={`${company.name}の営業キャッシュフローとフリーキャッシュフローの5年度推移`}
                />
              </div>
            </>
          ) : (
            <>
              <MetricLineChart
                title="売上高・営業利益"
                years={periods.map((period) => period.fiscal_year)}
                valueKind="money"
                series={[
                  {
                    label: "売上高",
                    color: "#18181b",
                    values: periods.map((period) => toMillions(period.metrics.revenue)),
                  },
                  {
                    label: "営業利益",
                    color: "#0f766e",
                    values: periods.map((period) =>
                      toMillions(period.metrics.operating_income),
                    ),
                  },
                ]}
              />
              <MetricLineChart
                title="営業利益率"
                years={periods.map((period) => period.fiscal_year)}
                valueKind="percent"
                series={[
                  {
                    label: "営業利益率",
                    color: "#7c3aed",
                    values: periods.map(
                      (period) => period.calculated_metrics.operating_margin_pct,
                    ),
                  },
                ]}
              />
              <div className="lg:col-span-2">
                <MetricLineChart
                  title="営業キャッシュフロー・フリーキャッシュフロー"
                  years={periods.map((period) => period.fiscal_year)}
                  valueKind="money"
                  series={[
                    {
                      label: "営業CF",
                      color: "#0369a1",
                      values: periods.map((period) =>
                        toMillions(period.metrics.operating_cash_flow),
                      ),
                    },
                    {
                      label: "FCF",
                      color: "#c2410c",
                      values: periods.map((period) =>
                        toMillions(period.calculated_metrics.free_cash_flow),
                      ),
                    },
                  ]}
                />
              </div>
            </>
          )}
        </div>
      </section>

      <section className="mt-12" aria-labelledby="trend-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h2 id="trend-heading" className="text-lg font-semibold text-zinc-950">
              5年度推移
            </h2>
            <p className="mt-1 text-sm text-zinc-500">表示順：会計年度昇順</p>
          </div>
          <p className="text-xs text-zinc-500">金額単位：百万円</p>
        </div>

        <div className="mt-4 overflow-x-auto border border-zinc-300">
          <table className="w-full min-w-[1080px] border-collapse text-sm">
            <thead className="bg-zinc-100 text-left text-xs font-medium text-zinc-600">
              <tr>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3">年度</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">売上高</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">営業利益</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">純利益</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">売上前年比</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">営業利益率</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">ROE</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">営業CF</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">FCF</th>
                <th scope="col" className="border-b border-zinc-300 px-4 py-3 text-right">3年CAGR</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-300 font-mono text-zinc-800">
              {periods.map((period) => (
                <tr key={period.fiscal_year} className="hover:bg-zinc-50">
                  <th scope="row" className="px-4 py-4 text-left font-medium text-zinc-950">
                    FY{period.fiscal_year}
                  </th>
                  <td className="px-4 py-4 text-right">{formatMoneyInMillions(period.metrics.revenue)}</td>
                  <td className="px-4 py-4 text-right">{formatMoneyInMillions(period.metrics.operating_income)}</td>
                  <td className="px-4 py-4 text-right">{formatMoneyInMillions(period.metrics.net_income)}</td>
                  <td className="px-4 py-4 text-right">{formatPercent(period.calculated_metrics.revenue_yoy_pct)}</td>
                  <td className="px-4 py-4 text-right">{formatPercent(period.calculated_metrics.operating_margin_pct)}</td>
                  <td className="px-4 py-4 text-right">{formatPercent(period.metrics.roe_pct)}</td>
                  <td className="px-4 py-4 text-right">{formatMoneyInMillions(period.metrics.operating_cash_flow)}</td>
                  <td className="px-4 py-4 text-right">{formatMoneyInMillions(period.calculated_metrics.free_cash_flow)}</td>
                  <td className="px-4 py-4 text-right">{formatPercent(period.calculated_metrics.revenue_cagr_3y_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-12 border-t border-zinc-300 pt-8" aria-labelledby="source-heading">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 id="source-heading" className="text-lg font-semibold text-zinc-950">
              出典
            </h2>
            <p className="mt-1 text-sm text-zinc-500">
              各年度の有価証券報告書をEDINETで確認できます。
            </p>
          </div>
          <p className="text-xs text-zinc-500">
            JSON生成：{formatTimestamp(getFinancialsGeneratedAt())}
          </p>
        </div>

        <ul className="mt-4 divide-y divide-zinc-300 border-y border-zinc-300">
          {periods.map((period) => (
            <li
              key={period.fiscal_year}
              className="grid gap-2 py-4 text-sm sm:grid-cols-[100px_140px_1fr_auto] sm:items-center"
            >
              <span className="font-mono font-medium text-zinc-950">FY{period.fiscal_year}</span>
              <span className="text-zinc-600">提出 {formatDate(period.source_document.filed_at)}</span>
              <span className="font-mono text-xs text-zinc-500">
                {period.source_document.document_id ?? "文書IDなし"}
              </span>
              {period.source_document.url ? (
                <a
                  href={period.source_document.url}
                  target="_blank"
                  rel="noreferrer"
                  className="justify-self-start font-medium text-zinc-950 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-950 sm:justify-self-end"
                >
                  EDINET原本 ↗
                </a>
              ) : (
                <span className="text-zinc-400 sm:text-right">リンクなし</span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
