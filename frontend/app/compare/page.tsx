import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { MetricLineChart } from "../../components/metric-line-chart";
import { StaticMetricChart } from "../../components/static-metric-chart";
import { getComparisonCharts } from "../../lib/charts";
import {
  formatMoneyInMillions,
  formatPercent,
  listFinancialCompanies,
  type FinancialCompany,
  type FinancialPeriod,
} from "../../lib/financials";

export const metadata: Metadata = {
  title: "2社比較",
  description: "EDINETの直近5年度データを2社で比較",
};

type ComparePageProps = {
  searchParams: Promise<{
    left?: string | string[];
    right?: string | string[];
  }>;
};

type ComparisonMetric = {
  label: string;
  read: (period: FinancialPeriod) => number | null;
  format: (value: number | null) => string;
};

const COMPARISON_METRICS: ComparisonMetric[] = [
  {
    label: "売上高",
    read: (period) => period.metrics.revenue,
    format: formatMoneyInMillions,
  },
  {
    label: "営業利益",
    read: (period) => period.metrics.operating_income,
    format: formatMoneyInMillions,
  },
  {
    label: "純利益",
    read: (period) => period.metrics.net_income,
    format: formatMoneyInMillions,
  },
  {
    label: "営業利益率",
    read: (period) => period.calculated_metrics.operating_margin_pct,
    format: formatPercent,
  },
  {
    label: "ROE",
    read: (period) => period.metrics.roe_pct,
    format: formatPercent,
  },
  {
    label: "FCF",
    read: (period) => period.calculated_metrics.free_cash_flow,
    format: formatMoneyInMillions,
  },
];

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function findCompany(companies: FinancialCompany[], ticker: string | undefined) {
  return companies.find((company) => company.ticker === ticker);
}

function periodByYear(company: FinancialCompany): Map<number, FinancialPeriod> {
  return new Map(company.periods.map((period) => [period.fiscal_year, period]));
}

function latestPeriod(company: FinancialCompany): FinancialPeriod {
  return [...company.periods].sort((a, b) => b.fiscal_year - a.fiscal_year)[0]!;
}

function toMillions(value: number | null): number | null {
  return value === null ? null : value / 1_000_000;
}

function latestStats(period: FinancialPeriod) {
  return [
    ["売上高", formatMoneyInMillions(period.metrics.revenue), "百万円"],
    ["営業利益", formatMoneyInMillions(period.metrics.operating_income), "百万円"],
    ["営業利益率", formatPercent(period.calculated_metrics.operating_margin_pct), ""],
    ["ROE", formatPercent(period.metrics.roe_pct), ""],
  ] as const;
}

export default async function ComparePage({ searchParams }: ComparePageProps) {
  const companies = listFinancialCompanies();
  if (companies.length < 2) {
    notFound();
  }

  const params = await searchParams;
  const left = findCompany(companies, firstParam(params.left)) ?? companies[0]!;
  const requestedRight = findCompany(companies, firstParam(params.right));
  const right =
    requestedRight && requestedRight.ticker !== left.ticker
      ? requestedRight
      : companies.find((company) => company.ticker !== left.ticker)!;
  const staticCharts = getComparisonCharts(left.ticker, right.ticker);

  const leftPeriods = periodByYear(left);
  const rightPeriods = periodByYear(right);
  const years = [...leftPeriods.keys()]
    .filter((year) => rightPeriods.has(year))
    .sort((a, b) => a - b);
  const leftLatest = latestPeriod(left);
  const rightLatest = latestPeriod(right);

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
      <nav>
        <Link
          href="/"
          className="inline-flex text-sm text-zinc-600 underline decoration-zinc-300 underline-offset-4 hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-950"
        >
          ← 企業一覧へ戻る
        </Link>
      </nav>

      <header className="mt-8 border-b border-zinc-300 pb-7">
        <p className="font-mono text-[11px] tracking-[0.18em] text-zinc-500 uppercase">
          EDINET MVP
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950">
          2社比較
        </h1>
        <p className="mt-2 text-sm text-zinc-500">
          共通する直近年度を、金額は百万円単位で比較します。
        </p>
      </header>

      <form className="mt-6 grid gap-3 border border-zinc-300 bg-zinc-50 p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label className="grid gap-1.5 text-xs font-medium text-zinc-600">
          企業A
          <select
            name="left"
            defaultValue={left.ticker}
            className="h-10 border border-zinc-400 bg-white px-3 text-sm text-zinc-950 focus:outline-2 focus:outline-offset-1 focus:outline-zinc-950"
          >
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} {company.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-zinc-600">
          企業B
          <select
            name="right"
            defaultValue={right.ticker}
            className="h-10 border border-zinc-400 bg-white px-3 text-sm text-zinc-950 focus:outline-2 focus:outline-offset-1 focus:outline-zinc-950"
          >
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} {company.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="h-10 bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
        >
          比較する
        </button>
      </form>

      <section className="mt-8 grid gap-4 lg:grid-cols-2" aria-label="最新年度の比較">
        {[
          { company: left, period: leftLatest, marker: "企業A" },
          { company: right, period: rightLatest, marker: "企業B" },
        ].map(({ company, period, marker }) => (
          <article key={company.ticker} className="border border-zinc-300 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-medium text-zinc-500">{marker}</p>
                <h2 className="mt-1 text-xl font-semibold text-zinc-950">{company.name}</h2>
                <p className="mt-1 font-mono text-xs text-zinc-500">
                  {company.ticker} · FY{period.fiscal_year}
                </p>
              </div>
              <Link
                href={`/companies/${company.ticker}`}
                className="text-xs font-medium text-zinc-950 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-950"
              >
                詳細 →
              </Link>
            </div>
            <dl className="mt-5 grid grid-cols-2 border-l border-t border-zinc-300">
              {latestStats(period).map(([label, value, unit]) => (
                <div key={label} className="border-r border-b border-zinc-300 p-3">
                  <dt className="text-xs text-zinc-500">{label}</dt>
                  <dd className="mt-1.5 font-mono text-lg font-medium text-zinc-950">
                    {value}
                  </dd>
                  {unit ? <p className="text-[10px] text-zinc-400">{unit}</p> : null}
                </div>
              ))}
            </dl>
          </article>
        ))}
      </section>

      <section className="mt-12" aria-labelledby="comparison-charts-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="comparison-charts-heading" className="text-lg font-semibold text-zinc-950">
            5年度グラフ
          </h2>
          <p className="text-xs text-zinc-500">
            {left.name} / {right.name}
          </p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {staticCharts ? (
            <>
              <StaticMetricChart
                title="売上高"
                src={staticCharts.charts.revenue}
                alt={`${left.name}と${right.name}の売上高比較`}
              />
              <StaticMetricChart
                title="営業利益率"
                src={staticCharts.charts.operating_margin_pct}
                alt={`${left.name}と${right.name}の営業利益率比較`}
              />
              <div className="lg:col-span-2">
                <StaticMetricChart
                  title="フリーキャッシュフロー"
                  src={staticCharts.charts.free_cash_flow}
                  alt={`${left.name}と${right.name}のフリーキャッシュフロー比較`}
                />
              </div>
            </>
          ) : (
            <>
              <MetricLineChart
                title="売上高"
                years={years}
                valueKind="money"
                series={[
                  {
                    label: left.name,
                    color: "#18181b",
                    values: years.map((year) =>
                      toMillions(leftPeriods.get(year)?.metrics.revenue ?? null),
                    ),
                  },
                  {
                    label: right.name,
                    color: "#0f766e",
                    values: years.map((year) =>
                      toMillions(rightPeriods.get(year)?.metrics.revenue ?? null),
                    ),
                  },
                ]}
              />
              <MetricLineChart
                title="営業利益率"
                years={years}
                valueKind="percent"
                series={[
                  {
                    label: left.name,
                    color: "#18181b",
                    values: years.map(
                      (year) =>
                        leftPeriods.get(year)?.calculated_metrics.operating_margin_pct ?? null,
                    ),
                  },
                  {
                    label: right.name,
                    color: "#0f766e",
                    values: years.map(
                      (year) =>
                        rightPeriods.get(year)?.calculated_metrics.operating_margin_pct ?? null,
                    ),
                  },
                ]}
              />
              <div className="lg:col-span-2">
                <MetricLineChart
                  title="フリーキャッシュフロー"
                  years={years}
                  valueKind="money"
                  series={[
                    {
                      label: left.name,
                      color: "#18181b",
                      values: years.map((year) =>
                        toMillions(
                          leftPeriods.get(year)?.calculated_metrics.free_cash_flow ?? null,
                        ),
                      ),
                    },
                    {
                      label: right.name,
                      color: "#0f766e",
                      values: years.map((year) =>
                        toMillions(
                          rightPeriods.get(year)?.calculated_metrics.free_cash_flow ?? null,
                        ),
                      ),
                    },
                  ]}
                />
              </div>
            </>
          )}
        </div>
      </section>

      <section className="mt-12" aria-labelledby="comparison-table-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="comparison-table-heading" className="text-lg font-semibold text-zinc-950">
            年度別比較
          </h2>
          <p className="text-xs text-zinc-500">金額単位：百万円</p>
        </div>
        <div className="mt-4 overflow-x-auto border border-zinc-300">
          <table className="w-full min-w-[920px] border-collapse text-sm">
            <thead className="bg-zinc-100 text-left text-xs font-medium text-zinc-600">
              <tr>
                <th className="border-b border-zinc-300 px-4 py-3">年度</th>
                <th className="border-b border-zinc-300 px-4 py-3">指標</th>
                <th className="border-b border-zinc-300 px-4 py-3 text-right">
                  {left.name}
                </th>
                <th className="border-b border-zinc-300 px-4 py-3 text-right">
                  {right.name}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-300 text-zinc-800">
              {years
                .slice()
                .reverse()
                .flatMap((year) =>
                  COMPARISON_METRICS.map((metric, metricIndex) => {
                    const leftPeriod = leftPeriods.get(year)!;
                    const rightPeriod = rightPeriods.get(year)!;
                    return (
                      <tr key={`${year}-${metric.label}`} className="hover:bg-zinc-50">
                        {metricIndex === 0 ? (
                          <th
                            scope="rowgroup"
                            rowSpan={COMPARISON_METRICS.length}
                            className="border-r border-zinc-300 px-4 py-3 text-left align-top font-mono font-medium text-zinc-950"
                          >
                            FY{year}
                          </th>
                        ) : null}
                        <th scope="row" className="px-4 py-3 text-left font-medium text-zinc-600">
                          {metric.label}
                        </th>
                        <td className="px-4 py-3 text-right font-mono">
                          {metric.format(metric.read(leftPeriod))}
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {metric.format(metric.read(rightPeriod))}
                        </td>
                      </tr>
                    );
                  }),
                )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
