import { promises as fs } from "node:fs";
import path from "node:path";

export type CompanyMeta = {
  name: string;
  tier: string | number;
  avg_salary_man: number | null;
  location?: string;
  status?: string;
  listing_status?: string;
  avg_salary_fiscal_year?: number;
  edinet_code?: string;
  targets?: string[];
  note?: string;
};

export type Company = {
  ticker: string;
  name: string;
  tier: string;
  status: "direct" | "indirect";
  avgSalaryMan: number | null;
  avgSalaryFiscalYear: number | null;
  edinetCode: string;
  targets: string[];
  listingStatus: string;
  rawFinancialsAvailable: boolean;
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

  let rawFilenames: string[] = [];
  try {
    rawFilenames = await fs.readdir(path.resolve(process.cwd(), "..", "data", "raw"));
  } catch {
    // The raw directory is optional in fresh environments.
  }

  return Object.entries(parsed).map(([ticker, meta]) => ({
    ticker,
    name: meta.name,
    tier: String(meta.tier),
    status: meta.status === "indirect" ? "indirect" : "direct",
    avgSalaryMan: meta.avg_salary_man,
    avgSalaryFiscalYear: meta.avg_salary_fiscal_year ?? null,
    edinetCode: meta.edinet_code ?? "",
    targets: meta.targets?.length ? meta.targets : [meta.name],
    listingStatus: meta.listing_status ?? "listed",
    rawFinancialsAvailable: rawFilenames.some((filename) =>
      filename.startsWith(
        `${ticker.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}__financials__`,
      ),
    ),
    note: meta.note ?? "",
  }));
}
