import { loadCompanies } from "../lib/companies";

type KanbanColumn = {
  tier: string;
  items: Awaited<ReturnType<typeof loadCompanies>>;
};

function groupByTier(
  companies: Awaited<ReturnType<typeof loadCompanies>>,
): KanbanColumn[] {
  const grouped = new Map<string, Awaited<ReturnType<typeof loadCompanies>>>();

  for (const company of companies) {
    if (!grouped.has(company.tier)) {
      grouped.set(company.tier, []);
    }
    grouped.get(company.tier)!.push(company);
  }

  return [...grouped.entries()]
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([tier, items]) => ({ tier, items }));
}

export default async function HomePage() {
  const companies = await loadCompanies();
  const columns = groupByTier(companies);

  return (
    <main className="page">
      <header className="hero">
        <h1>IR Ticker Kanban</h1>
        <p>{companies.length}社を Tier ごとに表示</p>
      </header>

      <section className="board">
        {columns.map((column) => (
          <article key={column.tier} className="column">
            <h2>Tier {column.tier}</h2>
            <div className="cards">
              {column.items.map((company) => (
                <div key={company.ticker} className="card">
                  <p className="ticker">{company.ticker}</p>
                  <h3>{company.name}</h3>
                  <dl>
                    <div>
                      <dt>平均年収</dt>
                      <dd>{company.avgSalaryMan}万円</dd>
                    </div>
                    <div>
                      <dt>Tier</dt>
                      <dd>{company.tier}</dd>
                    </div>
                  </dl>
                  {company.note ? <p className="note">{company.note}</p> : null}
                </div>
              ))}
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
