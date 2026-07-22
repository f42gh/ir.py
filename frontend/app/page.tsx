import Link from "next/link";

import { loadCompanies } from "../lib/companies";
import { listFinancialCompanies } from "../lib/financials";

export default async function HomePage() {
  const companies = await loadCompanies();
  const availableTickers = new Set(
    listFinancialCompanies().map((company) => company.ticker),
  );
  const targetCount = companies.reduce(
    (count, company) => count + company.targets.length,
    0,
  );
  const directCount = companies.filter(
    (company) => company.status === "direct",
  ).length;

  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-zinc-300 pb-5">
        <div>
          <p className="font-mono text-[11px] tracking-[0.18em] text-zinc-500 uppercase">
            EDINET MVP
          </p>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-zinc-950 sm:text-3xl">
            財務ダッシュボード
          </h1>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <p className="text-zinc-500">
            財務推移：{availableTickers.size}社・各5年度
          </p>
          <Link
            href="/compare"
            className="font-medium text-zinc-950 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-950"
          >
            2社比較 →
          </Link>
        </div>
      </header>

      <section className="mt-6" aria-labelledby="company-list-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="company-list-heading" className="text-base font-semibold text-zinc-950">
            対象企業
          </h2>
          <div className="flex flex-wrap gap-x-4 text-xs text-zinc-500">
            <span>応募先 {targetCount}</span>
            <span>直接 {directCount}</span>
            <span>間接 {companies.length - directCount}</span>
            <span>給与：最新有報・万円</span>
          </div>
        </div>

        <div className="mt-2 overflow-hidden border border-zinc-300">
          <div className="hidden grid-cols-[92px_minmax(220px,1fr)_72px_56px_116px_120px] gap-3 border-b border-zinc-300 bg-zinc-100 px-4 py-2 text-[11px] font-medium text-zinc-600 lg:grid">
            <span>銘柄コード</span>
            <span>応募先 / EDINET参照先</span>
            <span>Status</span>
            <span>Tier</span>
            <span>平均年間給与</span>
            <span>財務データ</span>
          </div>

          <ul className="divide-y divide-zinc-300">
            {companies.map((company) => {
              const isAvailable = availableTickers.has(company.ticker);
              const isDirect = company.status === "direct";
              const content = (
                <>
                  <span className="flex items-center gap-1.5 font-mono text-xs text-zinc-600">
                    {company.ticker}
                    {company.listingStatus === "delisted" ? (
                      <span className="border border-zinc-400 px-1 py-0.5 font-sans text-[9px] tracking-wide text-zinc-600">
                        旧
                      </span>
                    ) : null}
                  </span>
                  <span>
                    <span className="block text-sm font-medium text-zinc-950">
                      {company.targets.join(" / ")}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-zinc-500">
                      {company.name}
                      {company.edinetCode ? ` · ${company.edinetCode}` : ""}
                    </span>
                  </span>
                  <span>
                    <span
                      className={
                        isDirect
                          ? "inline-flex border border-emerald-700/30 bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800"
                          : "inline-flex border border-zinc-400 bg-zinc-200 px-1.5 py-0.5 text-[11px] font-medium text-zinc-600"
                      }
                    >
                      {isDirect ? "直接" : "間接"}
                    </span>
                  </span>
                  <span className="text-xs text-zinc-600">
                    {company.tier ? `T${company.tier}` : "—"}
                  </span>
                  <span className="text-xs text-zinc-700">
                    {company.avgSalaryMan === null
                      ? "—"
                      : `${company.avgSalaryMan.toLocaleString("ja-JP", {
                          maximumFractionDigits: 1,
                        })}万円`}
                    {company.avgSalaryFiscalYear ? (
                      <span className="ml-1 text-[10px] text-zinc-400">
                        FY{String(company.avgSalaryFiscalYear).slice(-2)}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={
                      isAvailable
                        ? "text-xs font-medium text-zinc-950"
                        : company.rawFinancialsAvailable
                          ? "text-xs font-medium text-zinc-600"
                        : "text-xs text-zinc-400"
                    }
                  >
                    {isAvailable
                      ? "表示可 →"
                      : company.rawFinancialsAvailable
                        ? "raw取得済"
                        : "未取得"}
                  </span>
                </>
              );

              return (
                <li key={company.ticker}>
                  {isAvailable ? (
                    <Link
                      href={`/companies/${company.ticker}`}
                      className={`grid grid-cols-[76px_minmax(0,1fr)_56px] items-center gap-x-3 gap-y-2 px-4 py-3 transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-950 lg:grid-cols-[92px_minmax(220px,1fr)_72px_56px_116px_120px] ${
                        isDirect
                          ? "hover:bg-zinc-100 focus-visible:bg-zinc-100"
                          : "bg-zinc-100/80 opacity-80 hover:opacity-100 focus-visible:opacity-100"
                      }`}
                    >
                      {content}
                    </Link>
                  ) : (
                    <div
                      className={`grid grid-cols-[76px_minmax(0,1fr)_56px] items-center gap-x-3 gap-y-2 px-4 py-3 lg:grid-cols-[92px_minmax(220px,1fr)_72px_56px_116px_120px] ${
                        isDirect ? "bg-white" : "bg-zinc-100/80 opacity-80"
                      }`}
                      aria-disabled="true"
                    >
                      {content}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </section>
    </main>
  );
}
