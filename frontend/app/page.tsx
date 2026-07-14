import Link from "next/link";

import { loadCompanies } from "../lib/companies";
import { listFinancialCompanies } from "../lib/financials";

export default async function HomePage() {
  const companies = await loadCompanies();
  const availableTickers = new Set(
    listFinancialCompanies().map((company) => company.ticker),
  );

  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-4 py-10 sm:px-6 lg:px-8 lg:py-16">
      <header className="border-b border-zinc-300 pb-8">
        <p className="font-mono text-xs tracking-[0.18em] text-zinc-500 uppercase">
          EDINET MVP
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-950 sm:text-4xl">
          財務ダッシュボード
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-600 sm:text-base">
          EDINETの年次財務データを、企業ごとに確認できます。現在はZOZOの直近5年度を公開しています。
        </p>
      </header>

      <section className="mt-10" aria-labelledby="company-list-heading">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 id="company-list-heading" className="text-lg font-semibold text-zinc-950">
              対象企業
            </h2>
            <p className="mt-1 text-sm text-zinc-500">MVP対象 {companies.length}社</p>
          </div>
          <p className="text-xs text-zinc-500">財務データは順次追加予定</p>
        </div>

        <div className="mt-4 overflow-hidden border border-zinc-300">
          <div className="hidden grid-cols-[120px_1fr_100px_180px] border-b border-zinc-300 bg-zinc-100 px-5 py-3 text-xs font-medium text-zinc-600 sm:grid">
            <span>銘柄コード</span>
            <span>企業名</span>
            <span>Tier</span>
            <span>財務データ</span>
          </div>

          <ul className="divide-y divide-zinc-300">
            {companies.map((company) => {
              const isAvailable = availableTickers.has(company.ticker);
              const content = (
                <>
                  <span className="font-mono text-sm text-zinc-600">{company.ticker}</span>
                  <span className="font-medium text-zinc-950">{company.name}</span>
                  <span className="text-sm text-zinc-600">Tier {company.tier}</span>
                  <span
                    className={
                      isAvailable
                        ? "text-sm font-medium text-zinc-950"
                        : "text-sm text-zinc-400"
                    }
                  >
                    {isAvailable ? "5年度取得済み →" : "未取得"}
                  </span>
                </>
              );

              return (
                <li key={company.ticker}>
                  {isAvailable ? (
                    <Link
                      href={`/companies/${company.ticker}`}
                      className="grid gap-2 px-5 py-5 transition-colors hover:bg-zinc-100 focus-visible:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-950 sm:grid-cols-[120px_1fr_100px_180px] sm:items-center"
                    >
                      {content}
                    </Link>
                  ) : (
                    <div
                      className="grid gap-2 bg-zinc-50 px-5 py-5 sm:grid-cols-[120px_1fr_100px_180px] sm:items-center"
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
