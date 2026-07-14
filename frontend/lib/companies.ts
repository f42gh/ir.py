import { promises as fs } from "node:fs";
import path from "node:path";

export type CompanyMeta = {
  name: string;
  tier: string | number;
  avg_salary_man: number;
  note?: string;
};

export type Company = {
  ticker: string;
  name: string;
  tier: string;
  avgSalaryMan: number;
  note: string;
};

export async function loadCompanies(): Promise<Company[]> {
  const candidates = [
    path.resolve(process.cwd(), "..", "data", "COMPANIES.json"),
    path.resolve(process.cwd(), "..", "data", "companies.example.json"),
  ];
  let parsed: Record<string, CompanyMeta> = {};

  for (const filePath of candidates) {
    try {
      const raw = await fs.readFile(filePath, "utf-8");
      if (!raw.trim()) {
        continue;
      }
      parsed = JSON.parse(raw) as Record<string, CompanyMeta>;
      break;
    } catch {
      continue;
    }
  }

  return Object.entries(parsed)
    .map(([ticker, meta]) => ({
      ticker,
      name: meta.name,
      tier: String(meta.tier),
      avgSalaryMan: meta.avg_salary_man,
      note: meta.note ?? "",
    }))
    .sort((a, b) => a.tier.localeCompare(b.tier) || a.ticker.localeCompare(b.ticker));
}
