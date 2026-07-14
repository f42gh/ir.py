from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from src import build_financials


RAW_NAME = "zozo__financials__20260714T050058Z.json"


def raw_payload() -> dict[str, object]:
    values = [
        (2022, 166_199_000_000, 49_656_000_000, 34_492_000_000, 0.625),
        (2023, 183_423_000_000, 56_421_000_000, 39_526_000_000, 0.601),
        (2024, 197_016_000_000, 60_079_000_000, 44_341_000_000, 0.550),
        (2025, 213_131_000_000, 64_756_000_000, 45_346_000_000, 0.494),
        (2026, 228_373_000_000, 69_366_000_000, 47_926_000_000, 0.466),
    ]
    cash_flows = {
        2022: (39_895_000_000, -1_283_000_000),
        2023: (36_671_000_000, -10_588_000_000),
        2024: (42_589_000_000, -9_879_000_000),
        2025: (60_114_000_000, -6_285_000_000),
        2026: (52_531_000_000, -28_897_000_000),
    }
    rows = []
    for year, revenue, operating_income, net_income, roe in values:
        operating_cf, investing_cf = cash_flows[year]
        rows.append(
            {
                "fiscal_year": year,
                "accounting_standard": "JP",
                "revenue": float(revenue),
                "operating_income": float(operating_income),
                "net_income": float(net_income),
                "total_assets": float(100_000_000_000 + year),
                "shareholders_equity": float(50_000_000_000 + year),
                "net_assets": float(99_000_000_000 + year),
                "cf_operating": float(operating_cf),
                "cf_investing": float(investing_cf),
                "roe_official": roe,
                "doc_id": f"S{year}",
                "submit_date": f"{year}-06-14 15:00",
                "edinet_filing_url": f"https://example.com/{year}",
            }
        )
    return {
        "data": rows,
        "meta": {
            "edinet_code": "E05725",
            "period": "annual",
        },
    }


class TimestampTests(unittest.TestCase):
    def test_parses_timestamp_from_filename(self) -> None:
        result = build_financials.parse_fetched_at(Path(RAW_NAME))
        self.assertEqual(result, "2026-07-14T05:00:58Z")

    def test_rejects_wrong_filename_or_impossible_date(self) -> None:
        for name in (
            "financials.json",
            "zozo__search__20260714T050058Z.json",
            "zozo__financials__20260230T050058Z.json",
        ):
            with self.subTest(name=name):
                with self.assertRaises(build_financials.BuildError):
                    build_financials.parse_fetched_at(Path(name))


class NormalizationTests(unittest.TestCase):
    def test_normalizes_integer_like_money(self) -> None:
        for value in (123, 123.0, -123.0, 0.0, None):
            with self.subTest(value=value):
                expected = None if value is None else int(value)
                self.assertEqual(
                    build_financials.normalize_money(
                        value, field="revenue", fiscal_year=2026
                    ),
                    expected,
                )

    def test_rejects_non_integer_money(self) -> None:
        for value in (1.5, "100", True, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(build_financials.BuildError):
                    build_financials.normalize_money(
                        value, field="revenue", fiscal_year=2026
                    )

    def test_maps_accounting_standards(self) -> None:
        cases = {
            "JP": "JGAAP",
            "JP_GAAP": "JGAAP",
            "IFRS": "IFRS",
            "US": "USGAAP",
            "US_GAAP": "USGAAP",
            "other": "UNKNOWN",
            None: "UNKNOWN",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    build_financials.normalize_accounting_standard(raw), expected
                )

    def test_normalizes_roe_and_filed_at(self) -> None:
        self.assertEqual(
            build_financials.normalize_roe(0.466, fiscal_year=2026), 46.6
        )
        self.assertIsNone(build_financials.normalize_roe(None, fiscal_year=2026))
        self.assertEqual(
            build_financials.normalize_filed_at("2026-06-08 15:34"), "2026-06-08"
        )
        self.assertIsNone(build_financials.normalize_filed_at("invalid"))


class CalculationTests(unittest.TestCase):
    def test_revenue_yoy(self) -> None:
        self.assertEqual(
            build_financials.calculate_revenue_yoy(183_423, 166_199), 10.3635
        )
        for current, previous in ((None, 100), (100, None), (100, 0)):
            self.assertIsNone(
                build_financials.calculate_revenue_yoy(current, previous)
            )

    def test_operating_margin_preserves_negative_results(self) -> None:
        self.assertEqual(
            build_financials.calculate_operating_margin(69_366, 228_373), 30.374
        )
        self.assertEqual(
            build_financials.calculate_operating_margin(-10, 100), -10.0
        )
        for operating_income, revenue in ((None, 100), (10, None), (10, 0)):
            self.assertIsNone(
                build_financials.calculate_operating_margin(
                    operating_income, revenue
                )
            )

    def test_free_cash_flow_uses_original_investing_sign(self) -> None:
        self.assertEqual(
            build_financials.calculate_free_cash_flow(52_531, -28_897), 23_634
        )
        self.assertIsNone(build_financials.calculate_free_cash_flow(None, -1))
        self.assertIsNone(build_financials.calculate_free_cash_flow(1, None))

    def test_three_year_cagr(self) -> None:
        self.assertEqual(
            build_financials.calculate_revenue_cagr_3y(213_131, 166_199), 8.6441
        )
        self.assertEqual(build_financials.calculate_revenue_cagr_3y(0, 100), -100.0)
        for current, starting in (
            (None, 100),
            (100, None),
            (-1, 100),
            (100, 0),
            (100, -1),
        ):
            self.assertIsNone(
                build_financials.calculate_revenue_cagr_3y(current, starting)
            )


class DocumentTests(unittest.TestCase):
    def build(self, payload: dict[str, object] | None = None) -> dict[str, object]:
        return build_financials.build_document(
            raw_payload() if payload is None else payload,
            input_path=Path(RAW_NAME),
        )

    def test_builds_expected_schema_and_values(self) -> None:
        document = self.build()
        self.assertEqual(document["schema_version"], "1.0")
        self.assertEqual(document["generated_at"], "2026-07-14T05:00:58Z")
        company = document["companies"][0]
        self.assertEqual(
            {key: company[key] for key in ("ticker", "name", "edinet_code", "currency")},
            {
                "ticker": "3092.T",
                "name": "ZOZO",
                "edinet_code": "E05725",
                "currency": "JPY",
            },
        )

        periods = company["periods"]
        self.assertEqual(
            [period["fiscal_year"] for period in periods],
            [2022, 2023, 2024, 2025, 2026],
        )
        self.assertTrue(all(period["fiscal_year_end"] is None for period in periods))
        self.assertTrue(all(period["consolidated"] is True for period in periods))
        self.assertTrue(
            all(period["accounting_standard"] == "JGAAP" for period in periods)
        )
        self.assertTrue(
            all(
                period["fetched_at"] == "2026-07-14T05:00:58Z"
                for period in periods
            )
        )

        latest = periods[-1]
        self.assertEqual(latest["metrics"]["revenue"], 228_373_000_000)
        self.assertEqual(latest["metrics"]["equity"], 50_000_002_026)
        self.assertNotEqual(latest["metrics"]["equity"], 99_000_002_026)
        self.assertEqual(latest["metrics"]["roe_pct"], 46.6)
        self.assertEqual(
            latest["source_document"],
            {
                "document_id": "S2026",
                "document_type": "annual_securities_report",
                "filed_at": "2026-06-14",
                "url": "https://example.com/2026",
            },
        )

    def test_calculated_metrics_match_zozo_expectations(self) -> None:
        periods = self.build()["companies"][0]["periods"]
        expected = [
            (None, 29.8774, 38_612_000_000, None, 62.5),
            (10.3635, 30.76, 26_083_000_000, None, 60.1),
            (7.4107, 30.4945, 32_710_000_000, None, 55.0),
            (8.1795, 30.3832, 53_829_000_000, 8.6441, 49.4),
            (7.1515, 30.374, 23_634_000_000, 7.5797, 46.6),
        ]
        for period, values in zip(periods, expected, strict=True):
            calculated = period["calculated_metrics"]
            actual = (
                calculated["revenue_yoy_pct"],
                calculated["operating_margin_pct"],
                calculated["free_cash_flow"],
                calculated["revenue_cagr_3y_pct"],
                period["metrics"]["roe_pct"],
            )
            self.assertEqual(actual, values)

    def test_sorts_shuffled_years(self) -> None:
        payload = raw_payload()
        payload["data"] = list(reversed(payload["data"]))
        periods = self.build(payload)["companies"][0]["periods"]
        self.assertEqual(
            [period["fiscal_year"] for period in periods],
            [2022, 2023, 2024, 2025, 2026],
        )

    def test_missing_zero_and_negative_values_remain_distinct(self) -> None:
        payload = raw_payload()
        first = payload["data"][0]
        first["operating_income"] = -100.0
        first["cf_operating"] = 0.0
        first["cf_investing"] = None
        first["revenue"] = None

        period = self.build(payload)["companies"][0]["periods"][0]
        self.assertIsNone(period["metrics"]["revenue"])
        self.assertEqual(period["metrics"]["operating_income"], -100)
        self.assertEqual(period["metrics"]["operating_cash_flow"], 0)
        self.assertIsNone(period["metrics"]["investing_cash_flow"])
        self.assertIsNone(period["calculated_metrics"]["operating_margin_pct"])
        self.assertIsNone(period["calculated_metrics"]["free_cash_flow"])

    def test_rejects_invalid_raw_contract(self) -> None:
        cases = []

        wrong_code = raw_payload()
        wrong_code["meta"]["edinet_code"] = "E00000"
        cases.append(wrong_code)

        quarterly = raw_payload()
        quarterly["meta"]["period"] = "quarterly"
        cases.append(quarterly)

        wrong_count = raw_payload()
        wrong_count["data"].pop()
        cases.append(wrong_count)

        duplicate = raw_payload()
        duplicate["data"][1]["fiscal_year"] = 2022
        cases.append(duplicate)

        fractional_money = raw_payload()
        fractional_money["data"][0]["revenue"] = 1.5
        cases.append(fractional_money)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(build_financials.BuildError):
                    self.build(payload)


class FileAndCliTests(unittest.TestCase):
    def test_atomic_output_is_deterministic_and_has_trailing_newline(self) -> None:
        document = build_financials.build_document(
            raw_payload(), input_path=Path(RAW_NAME)
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "financials.json"
            build_financials.write_json_atomic(document, output)
            first = output.read_bytes()
            build_financials.write_json_atomic(document, output)
            second = output.read_bytes()

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(json.loads(first)["schema_version"], "1.0")

    def test_invalid_json_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / RAW_NAME
            output_path = root / "financials.json"
            input_path.write_text("not-json", encoding="utf-8")
            output_path.write_bytes(b"original")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = build_financials.main(
                    ["--input", str(input_path), "--output", str(output_path)]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(output_path.read_bytes(), b"original")
            self.assertIn("有効なUTF-8 JSON", stderr.getvalue())

    def test_cli_builds_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / RAW_NAME
            output_path = root / "nested" / "financials.json"
            input_path.write_text(
                json.dumps(raw_payload(), ensure_ascii=False), encoding="utf-8"
            )

            exit_code = build_financials.main(
                ["--input", str(input_path), "--output", str(output_path)]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8"))["generated_at"],
                "2026-07-14T05:00:58Z",
            )


if __name__ == "__main__":
    unittest.main()
