from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from src import build_analytics, build_financials


def raw_payload(edinet_code: str, *, revenue_base: int) -> dict[str, object]:
    return {
        "data": [
            {
                "fiscal_year": year,
                "accounting_standard": "JP",
                "revenue": revenue_base + year,
                "operating_income": 20_000_000_000,
                "net_income": 10_000_000_000,
                "total_assets": 150_000_000_000,
                "shareholders_equity": 70_000_000_000,
                "cf_operating": 15_000_000_000,
                "cf_investing": -5_000_000_000,
                "roe_official": 0.1,
                "doc_id": f"S{year}",
                "submit_date": f"{year}-06-30 15:00",
                "edinet_filing_url": f"https://example.com/{year}",
            }
            for year in range(2021, 2026)
        ],
        "meta": {"edinet_code": edinet_code, "period": "annual"},
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class AnalyticsWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir()
        self.companies_path = self.root / "companies.json"
        write_json(
            self.companies_path,
            {
                "1111.T": {
                    "name": "Example",
                    "status": "direct",
                    "edinet_code": "E00001",
                    "tier": "1",
                    "avg_salary_man": 800,
                },
                "9999.T": {
                    "name": "Indirect",
                    "status": "indirect",
                    "edinet_code": "E99999",
                },
            },
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_snapshot(self, timestamp: str, revenue_base: int) -> Path:
        path = self.raw_dir / f"1111_t__financials__{timestamp}.json"
        write_json(path, raw_payload("E00001", revenue_base=revenue_base))
        return path

    def test_preserves_all_snapshots_and_mart_uses_latest(self) -> None:
        self._write_snapshot("20260720T000000Z", 100_000_000_000)
        self._write_snapshot("20260722T000000Z", 200_000_000_000)
        companies = build_analytics.load_companies(self.companies_path)
        snapshots, missing = build_analytics.discover_snapshots(
            self.raw_dir, companies, allow_missing=False
        )

        warehouse = self.root / "warehouse"
        result = build_analytics.build_warehouse(
            warehouse, companies, snapshots, missing
        )

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(len(result.mart), 5)
        self.assertEqual(int(result.mart.iloc[0]["revenue"]), 200_000_002_021)
        connection = duckdb.connect(str(warehouse / "analytics.duckdb"), read_only=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM financial_history").fetchone()[0],
                80,
            )
            value_type = connection.execute(
                "SELECT column_type FROM (DESCRIBE financial_history) "
                "WHERE column_name = 'value'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(value_type, "DECIMAL(38,4)")

    def test_new_frontend_export_matches_legacy_document(self) -> None:
        input_path = self._write_snapshot("20260722T000000Z", 200_000_000_000)
        payload = build_financials.load_raw(input_path)
        companies = build_analytics.load_companies(self.companies_path)
        snapshots, missing = build_analytics.discover_snapshots(
            self.raw_dir, companies, allow_missing=False
        )
        warehouse = self.root / "warehouse"
        result = build_analytics.build_warehouse(
            warehouse, companies, snapshots, missing
        )
        actual = build_analytics.build_frontend_document(
            result.mart, result.generated_at
        )
        company, _ = build_financials.build_company(
            payload,
            input_path=input_path,
            company=companies[0].as_build_spec(),
        )
        expected = {
            "schema_version": "1.0",
            "generated_at": "2026-07-22T00:00:00Z",
            "companies": [company],
        }
        self.assertEqual(actual, expected)

    def test_missing_direct_company_is_strict_by_default(self) -> None:
        companies = build_analytics.load_companies(self.companies_path)
        with self.assertRaisesRegex(build_analytics.AnalyticsError, "財務rawがありません"):
            build_analytics.discover_snapshots(
                self.raw_dir, companies, allow_missing=False
            )

    def test_invalid_comparison_does_not_replace_existing_outputs(self) -> None:
        self._write_snapshot("20260722T000000Z", 200_000_000_000)
        comparisons_path = self.root / "comparisons.json"
        write_json(
            comparisons_path,
            {
                "schema_version": "1.0",
                "pairs": [{"id": "broken", "left": "1111.T", "right": "1111.T"}],
            },
        )
        frontend_json = self.root / "frontend" / "financials.json"
        stats_json = self.root / "frontend" / "stats.json"
        frontend_json.parent.mkdir()
        frontend_json.write_bytes(b"original")
        charts_dir = self.root / "frontend" / "public" / "charts"
        warehouse_dir = self.root / "published-warehouse"
        args = argparse.Namespace(
            input_dir=self.raw_dir,
            companies=self.companies_path,
            warehouse_dir=warehouse_dir,
            frontend_json=frontend_json,
            stats_json=stats_json,
            charts_dir=charts_dir,
            comparisons=comparisons_path,
            allow_missing=False,
        )

        with self.assertRaisesRegex(build_analytics.AnalyticsError, "同じ企業"):
            build_analytics.run_pipeline(args)

        self.assertEqual(frontend_json.read_bytes(), b"original")
        self.assertFalse(warehouse_dir.exists())
        self.assertFalse(charts_dir.exists())

    def test_stats_failure_does_not_replace_existing_outputs(self) -> None:
        self._write_snapshot("20260722T000000Z", 200_000_000_000)
        comparisons_path = self.root / "comparisons.json"
        write_json(comparisons_path, {"schema_version": "1.0", "pairs": []})
        frontend_json = self.root / "frontend" / "financials.json"
        stats_json = self.root / "frontend" / "stats.json"
        frontend_json.parent.mkdir()
        frontend_json.write_bytes(b"financials-original")
        stats_json.write_bytes(b"stats-original")
        charts_dir = self.root / "frontend" / "public" / "charts"
        warehouse_dir = self.root / "published-warehouse"
        args = argparse.Namespace(
            input_dir=self.raw_dir,
            companies=self.companies_path,
            warehouse_dir=warehouse_dir,
            frontend_json=frontend_json,
            stats_json=stats_json,
            charts_dir=charts_dir,
            comparisons=comparisons_path,
            allow_missing=False,
        )

        with patch.object(
            build_analytics,
            "render_stats",
            side_effect=build_analytics.AnalyticsError("stats generation failed"),
        ):
            with self.assertRaisesRegex(build_analytics.AnalyticsError, "stats generation"):
                build_analytics.run_pipeline(args)

        self.assertEqual(frontend_json.read_bytes(), b"financials-original")
        self.assertEqual(stats_json.read_bytes(), b"stats-original")
        self.assertFalse(warehouse_dir.exists())
        self.assertFalse(charts_dir.exists())


class ChartTests(unittest.TestCase):
    def test_svg_is_deterministic_and_has_no_date_metadata(self) -> None:
        frame = pd.DataFrame(
            {
                "fiscal_year": [2023, 2024, 2025],
                "revenue": [100_000_000, 120_000_000, 110_000_000],
                "operating_income": [-10_000_000, 0, 20_000_000],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.svg"
            second = root / "second.svg"
            kwargs = {
                "frame": frame,
                "series": (
                    ("revenue", "Revenue", "#18181b"),
                    ("operating_income", "Op. income", "#0f766e"),
                ),
                "value_kind": "money",
            }
            build_analytics.render_line_chart(output=first, **kwargs)
            build_analytics.render_line_chart(output=second, **kwargs)

            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()

        self.assertEqual(first_bytes, second_bytes)
        self.assertNotIn(b"dc:date", first_bytes)
        self.assertIn(b"Revenue", first_bytes)

    def test_renders_configured_comparison_and_manifest(self) -> None:
        rows = []
        for ticker, scale in (("1111.T", 1), ("2222.T", 2)):
            for year in (2024, 2025):
                rows.append(
                    {
                        "ticker": ticker,
                        "fiscal_year": year,
                        "revenue": scale * year * 1_000_000,
                        "operating_income": scale * 100_000_000,
                        "operating_margin_pct": scale * 5.0,
                        "roe_pct": scale * 4.0,
                        "operating_cash_flow": scale * 90_000_000,
                        "free_cash_flow": scale * 60_000_000,
                    }
                )
        mart = pd.DataFrame(rows)
        companies = tuple(
            build_analytics.AnalyticsCompany(
                order=index,
                ticker=ticker,
                name=ticker,
                edinet_code=f"E0000{index + 1}",
                status="direct",
                tier="",
                listing_status="listed",
                avg_salary_man=None,
                avg_salary_fiscal_year=None,
                slug=build_financials.ticker_slug(ticker),
            )
            for index, ticker in enumerate(("1111.T", "2222.T"))
        )
        comparison = build_analytics.ComparisonPair(
            id="one-vs-two", left="1111.T", right="2222.T"
        )
        with tempfile.TemporaryDirectory() as directory:
            chart_dir = Path(directory) / "charts"
            manifest = build_analytics.render_charts(
                mart,
                (comparison,),
                companies,
                chart_dir,
                build_analytics._parse_utc_timestamp("2026-07-22T00:00:00Z"),
            )
            generated_files = list(chart_dir.rglob("*.svg"))

        self.assertEqual(len(generated_files), 9)
        self.assertEqual(manifest["comparisons"][0]["id"], "one-vs-two")
        self.assertEqual(
            manifest["comparisons"][0]["charts"]["revenue"],
            "/charts/comparisons/one-vs-two/revenue.svg",
        )

    def test_stats_rankings_descriptive_values_and_scatter_exclusions(self) -> None:
        rows = [
            {
                "company_order": 0,
                "ticker": "1111.T",
                "name": "One",
                "fiscal_year": 2024,
                "revenue": 900_000,
                "revenue_yoy_pct": 5.0,
                "operating_income": -1_000_000,
                "operating_margin_pct": -10.0,
                "roe_pct": None,
                "free_cash_flow": -5_000_000,
            },
            {
                "company_order": 1,
                "ticker": "2222.T",
                "name": "Two",
                "fiscal_year": 2024,
                "revenue": 2_000_000,
                "revenue_yoy_pct": 10.0,
                "operating_income": 0,
                "operating_margin_pct": 0.0,
                "roe_pct": 5.0,
                "free_cash_flow": 0,
            },
            {
                "company_order": 2,
                "ticker": "3333.T",
                "name": "Three",
                "fiscal_year": 2024,
                "revenue": 2_500_000,
                "revenue_yoy_pct": 15.0,
                "operating_income": 1_000_000,
                "operating_margin_pct": 10.0,
                "roe_pct": 10.0,
                "free_cash_flow": 2_000_000,
            },
        ]
        for company_order, (ticker, name, revenue, margin) in enumerate(
            (
                ("1111.T", "One", 1_000_000, -10.0),
                ("2222.T", "Two", 3_000_000, 0.0),
                ("3333.T", "Three", 3_000_000, 20.0),
                ("4444.T", "Four", None, None),
            )
        ):
            rows.append(
                {
                    "company_order": company_order,
                    "ticker": ticker,
                    "name": name,
                    "fiscal_year": 2025,
                    "revenue": revenue,
                    "revenue_yoy_pct": 10.0 * (company_order + 1),
                    "operating_income": (-1 + company_order) * 1_000_000,
                    "operating_margin_pct": margin,
                    "roe_pct": None if company_order == 0 else 5.0 * company_order,
                    "free_cash_flow": (-5 + company_order * 5) * 1_000_000,
                }
            )
        mart = pd.DataFrame(rows)
        generated_at = build_analytics._parse_utc_timestamp("2026-07-22T00:00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir = root / "first"
            second_dir = root / "second"
            document = build_analytics.render_stats(mart, first_dir, generated_at)
            build_analytics.render_stats(mart, second_dir, generated_at)
            generated_files = list(first_dir.rglob("*.svg"))
            first_svg = (
                first_dir / "stats/fy2025/rankings/revenue.svg"
            ).read_bytes()
            second_svg = (
                second_dir / "stats/fy2025/rankings/revenue.svg"
            ).read_bytes()

        self.assertEqual(document["years"], [2025])
        self.assertEqual(document["default_year"], 2025)
        self.assertEqual(len(generated_files), 9)
        descriptive = document["results"]["2025"]["descriptive"]["revenue"]
        self.assertEqual(descriptive["count"], 3)
        self.assertEqual(descriptive["missing"], 1)
        self.assertEqual(descriptive["mean"], 2.3333)
        self.assertEqual(descriptive["median"], 3.0)
        self.assertEqual(descriptive["stddev"], 1.1547)
        self.assertEqual(descriptive["q1"], 2.0)
        self.assertEqual(descriptive["q3"], 3.0)
        ranking = document["results"]["2025"]["rankings"]["revenue"]["rows"]
        self.assertEqual(
            [(row["ticker"], row["rank"]) for row in ranking],
            [("2222.T", 1), ("3333.T", 1), ("1111.T", 3), ("4444.T", None)],
        )
        growth_scatter = document["results"]["2025"]["scatters"][
            "growth-profitability"
        ]
        self.assertEqual(growth_scatter["included_count"], 3)
        self.assertEqual(growth_scatter["excluded_tickers"], ["4444.T"])
        scale_scatter = document["results"]["2025"]["scatters"]["scale-cash"]
        self.assertEqual(scale_scatter["excluded_tickers"], ["4444.T"])
        self.assertEqual(first_svg, second_svg)
        self.assertNotIn(b"dc:date", first_svg)


if __name__ == "__main__":
    unittest.main()
