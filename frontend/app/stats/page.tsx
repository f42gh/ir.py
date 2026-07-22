import type { Metadata } from "next";
import Link from "next/link";

import {
  formatStatsValue,
  getStatsData,
  type DescriptiveStatistics,
  type StatsMetricDefinition,
} from "../../lib/stats";

export const metadata: Metadata = {
  title: "企業統計",
  description: "EDINET財務データの企業ランキング、散布図、記述統計",
};

type StatsPageProps = {
  searchParams: Promise<{
    year?: string | string[];
    ranking?: string | string[];
    scatter?: string | string[];
  }>;
};

const STAT_LABELS: Array<[keyof DescriptiveStatistics, string]> = [
  ["count", "件数"],
  ["missing", "欠損"],
  ["mean", "平均"],
  ["median", "中央値"],
  ["stddev", "標準偏差"],
  ["min", "最小"],
  ["q1", "Q1"],
  ["q3", "Q3"],
  ["max", "最大"],
];

const EXCLUSION_LABELS: Record<string, string> = {
  missing_x: "X軸が欠損",
  missing_y: "Y軸が欠損",
  missing_x_and_y: "X・Y軸が欠損",
  non_positive_x_for_log: "対数軸で扱えないゼロ以下のX値",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function formatStatistic(
  key: keyof DescriptiveStatistics,
  value: number | null,
  metric: StatsMetricDefinition,
): string {
  if (key === "count" || key === "missing") {
    return value === null ? "—" : String(value);
  }
  return formatStatsValue(value, metric);
}

export default async function StatsPage({ searchParams }: StatsPageProps) {
  const data = getStatsData();
  const params = await searchParams;
  const requestedYear = Number(firstParam(params.year));
  const year = data.years.includes(requestedYear)
    ? requestedYear
    : data.default_year;
  const requestedRanking = firstParam(params.ranking);
  const rankingId =
    requestedRanking && Object.hasOwn(data.metrics, requestedRanking)
      ? requestedRanking
      : data.default_ranking;
  const requestedScatter = firstParam(params.scatter);
  const scatterId =
    requestedScatter && Object.hasOwn(data.scatter_definitions, requestedScatter)
      ? requestedScatter
      : data.default_scatter;

  const result = data.results[String(year)]!;
  const rankingMetric = data.metrics[rankingId]!;
  const ranking = result.rankings[rankingId]!;
  const scatterDefinition = data.scatter_definitions[scatterId]!;
  const scatter = result.scatters[scatterId]!;
  const xMetric = data.metrics[scatterDefinition.x_metric]!;
  const yMetric = data.metrics[scatterDefinition.y_metric]!;
  const selectedStats = result.descriptive[rankingId]!;

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
      <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <Link
          href="/"
          className="text-zinc-600 underline decoration-zinc-300 underline-offset-4 hover:text-zinc-950"
        >
          ← 企業一覧
        </Link>
        <Link
          href="/compare"
          className="text-zinc-600 underline decoration-zinc-300 underline-offset-4 hover:text-zinc-950"
        >
          2社比較 →
        </Link>
      </nav>

      <header className="mt-8 border-b border-zinc-300 pb-7">
        <p className="font-mono text-[11px] tracking-[0.18em] text-zinc-500 uppercase">
          EDINET STATS
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950">
          企業ランキング・統計
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-500">
          全対象企業に共通する年度を、同じ条件で比較します。順位は値が大きい順であり、投資評価や企業の優劣を示すものではありません。
        </p>
      </header>

      <form className="mt-6 grid gap-3 border border-zinc-300 bg-zinc-50 p-4 md:grid-cols-[0.7fr_1fr_1.2fr_auto] md:items-end">
        <label className="grid gap-1.5 text-xs font-medium text-zinc-600">
          共通年度
          <select
            name="year"
            defaultValue={year}
            className="h-10 border border-zinc-400 bg-white px-3 text-sm text-zinc-950"
          >
            {data.years.map((availableYear) => (
              <option key={availableYear} value={availableYear}>
                FY{availableYear}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-zinc-600">
          ランキング指標
          <select
            name="ranking"
            defaultValue={rankingId}
            className="h-10 border border-zinc-400 bg-white px-3 text-sm text-zinc-950"
          >
            {Object.entries(data.metrics).map(([id, metric]) => (
              <option key={id} value={id}>
                {metric.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-zinc-600">
          散布図
          <select
            name="scatter"
            defaultValue={scatterId}
            className="h-10 border border-zinc-400 bg-white px-3 text-sm text-zinc-950"
          >
            {Object.entries(data.scatter_definitions).map(([id, definition]) => (
              <option key={id} value={id}>
                {definition.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="h-10 bg-zinc-950 px-6 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-950"
        >
          生成
        </button>
      </form>

      <section className="mt-10" aria-labelledby="ranking-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-zinc-500">FY{year}</p>
            <h2 id="ranking-heading" className="mt-1 text-xl font-semibold text-zinc-950">
              {rankingMetric.label}ランキング
            </h2>
          </div>
          <p className="text-xs text-zinc-500">
            対象 {result.company_count}社・欠損 {selectedStats.missing}社・単位 {rankingMetric.unit}
          </p>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.7fr)]">
          <figure className="border border-zinc-300 p-4">
            <figcaption className="text-sm font-semibold text-zinc-950">
              値が大きい順
            </figcaption>
            <img
              src={ranking.chart}
              alt={`FY${year} ${rankingMetric.label}の全社ランキング`}
              className="mt-3 h-auto w-full"
            />
          </figure>
          <aside className="border border-zinc-300 p-4" aria-label="選択指標の記述統計">
            <h3 className="text-sm font-semibold text-zinc-950">記述統計</h3>
            <dl className="mt-3 grid grid-cols-2 border-l border-t border-zinc-300">
              {STAT_LABELS.map(([key, label]) => (
                <div key={key} className="border-r border-b border-zinc-300 p-3">
                  <dt className="text-[11px] text-zinc-500">{label}</dt>
                  <dd className="mt-1 font-mono text-sm text-zinc-950">
                    {formatStatistic(key, selectedStats[key], rankingMetric)}
                  </dd>
                </div>
              ))}
            </dl>
          </aside>
        </div>

        <div className="mt-4 overflow-x-auto border border-zinc-300">
          <table className="w-full min-w-[620px] border-collapse text-left text-sm">
            <thead className="bg-zinc-100 text-xs text-zinc-600">
              <tr>
                <th className="px-4 py-2.5 font-medium">順位</th>
                <th className="px-4 py-2.5 font-medium">Ticker</th>
                <th className="px-4 py-2.5 font-medium">企業</th>
                <th className="px-4 py-2.5 text-right font-medium">値（{rankingMetric.unit}）</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200">
              {ranking.rows.map((row) => (
                <tr key={row.ticker} className="hover:bg-zinc-50">
                  <td className="px-4 py-2.5 font-mono text-zinc-600">{row.rank ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-zinc-600">
                    <Link href={`/companies/${row.ticker}`} className="underline decoration-zinc-300 underline-offset-4">
                      {row.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 font-medium text-zinc-950">{row.name}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-zinc-950">
                    {formatStatsValue(row.value, rankingMetric)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-14" aria-labelledby="scatter-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-zinc-500">FY{year}</p>
            <h2 id="scatter-heading" className="mt-1 text-xl font-semibold text-zinc-950">
              {scatterDefinition.label}
            </h2>
          </div>
          <p className="text-xs text-zinc-500">
            表示 {scatter.included_count}社・除外 {scatter.exclusions.length}社
          </p>
        </div>
        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.7fr)]">
          <figure className="border border-zinc-300 p-4">
            <figcaption className="text-sm font-semibold text-zinc-950">
              {scatterDefinition.description}
            </figcaption>
            <img
              src={scatter.chart}
              alt={`FY${year} ${scatterDefinition.label}の企業散布図`}
              className="mt-3 h-auto w-full"
            />
          </figure>
          <aside className="border border-zinc-300 p-4">
            <h3 className="text-sm font-semibold text-zinc-950">軸と対象データ</h3>
            <dl className="mt-3 space-y-3 text-sm">
              <div>
                <dt className="text-xs text-zinc-500">X軸</dt>
                <dd className="mt-0.5 text-zinc-950">
                  {xMetric.label}（{xMetric.unit}）
                  {scatterDefinition.x_scale === "log" ? "・対数" : ""}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-500">Y軸</dt>
                <dd className="mt-0.5 text-zinc-950">{yMetric.label}（{yMetric.unit}）</dd>
              </div>
            </dl>
            {scatter.exclusions.length > 0 ? (
              <div className="mt-5 border-t border-zinc-300 pt-4">
                <h4 className="text-xs font-medium text-zinc-600">除外企業</h4>
                <ul className="mt-2 space-y-1 text-xs text-zinc-500">
                  {scatter.exclusions.map((item) => (
                    <li key={item.ticker}>
                      <span className="font-mono text-zinc-700">{item.ticker}</span>{" "}
                      {EXCLUSION_LABELS[item.reason] ?? item.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </aside>
        </div>

        <details className="mt-4 border border-zinc-300">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-950">
            散布図の元データを表示
          </summary>
          <div className="overflow-x-auto border-t border-zinc-300">
            <table className="w-full min-w-[680px] border-collapse text-left text-sm">
              <thead className="bg-zinc-100 text-xs text-zinc-600">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Ticker</th>
                  <th className="px-4 py-2.5 font-medium">企業</th>
                  <th className="px-4 py-2.5 text-right font-medium">{xMetric.label}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{yMetric.label}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200">
                {scatter.rows.map((row) => (
                  <tr key={row.ticker}>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-600">{row.ticker}</td>
                    <td className="px-4 py-2.5 text-zinc-950">{row.name}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{formatStatsValue(row.x, xMetric)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{formatStatsValue(row.y, yMetric)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="mt-14" aria-labelledby="descriptive-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="descriptive-heading" className="text-xl font-semibold text-zinc-950">
            全指標の記述統計
          </h2>
          <p className="text-xs text-zinc-500">標準偏差は標本標準偏差、四分位数は線形補間</p>
        </div>
        <div className="mt-4 overflow-x-auto border border-zinc-300">
          <table className="w-full min-w-[1050px] border-collapse text-right text-sm">
            <thead className="bg-zinc-100 text-xs text-zinc-600">
              <tr>
                <th className="px-3 py-2.5 text-left font-medium">指標</th>
                {STAT_LABELS.map(([, label]) => (
                  <th key={label} className="px-3 py-2.5 font-medium">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200">
              {Object.entries(data.metrics).map(([id, metric]) => {
                const statistics = result.descriptive[id]!;
                return (
                  <tr key={id} className={id === rankingId ? "bg-amber-50" : ""}>
                    <th className="px-3 py-2.5 text-left font-medium text-zinc-950">
                      {metric.label}
                      <span className="ml-1 text-[10px] font-normal text-zinc-400">{metric.unit}</span>
                    </th>
                    {STAT_LABELS.map(([key]) => (
                      <td key={key} className="px-3 py-2.5 font-mono text-xs text-zinc-700">
                        {formatStatistic(key, statistics[key], metric)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
