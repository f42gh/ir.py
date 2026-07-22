from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src import fetch_direct_companies


FIXED_TIME = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)


def financial_payload() -> dict[str, object]:
    return {
        "data": [
            {
                "fiscal_year": year,
                "accounting_standard": "JP",
                "revenue": 100_000_000_000,
                "operating_income": 20_000_000_000,
                "net_income": 10_000_000_000,
                "total_assets": 150_000_000_000,
                "shareholders_equity": 70_000_000_000,
                "cf_operating": 15_000_000_000,
                "cf_investing": -5_000_000_000,
                "roe_official": 0.1,
                "doc_id": f"S{year}",
                "submit_date": f"{year}-06-30",
                "edinet_filing_url": f"https://example.com/{year}",
            }
            for year in range(2021, 2026)
        ],
        "meta": {"period": "annual"},
    }


class CompanyLoadingTests(unittest.TestCase):
    def test_loads_only_direct_companies_in_file_order(self) -> None:
        payload = {
            "1111.T": {
                "name": "Direct One",
                "status": "direct",
                "edinet_code": "E00001",
            },
            "2222.T": {
                "name": "Indirect Two",
                "status": "indirect",
                "edinet_code": "E00002",
            },
            "3333.T": {
                "name": "Direct Three",
                "status": "direct",
                "edinet_code": "E00003",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "companies.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            companies = fetch_direct_companies.load_direct_companies(path)

        self.assertEqual([company.ticker for company in companies], ["1111.T", "3333.T"])

    def test_rejects_invalid_direct_edinet_code(self) -> None:
        payload = {
            "1111.T": {
                "name": "Broken",
                "status": "direct",
                "edinet_code": "invalid",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "companies.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(fetch_direct_companies.FetchError, "EDINETコード"):
                fetch_direct_companies.load_direct_companies(path)


class DirectFetchTests(unittest.TestCase):
    def test_fetches_five_years_and_saves_exact_response(self) -> None:
        body = json.dumps(financial_payload(), separators=(",", ":")).encode()
        seen_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(200, content=body)

        company = fetch_direct_companies.DirectCompany(
            ticker="1234.T",
            name="Example",
            edinet_code="E01234",
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with httpx.Client(
                base_url="https://example.com/v1",
                transport=httpx.MockTransport(handler),
            ) as client:
                result = fetch_direct_companies.fetch_direct_company(
                    client,
                    company,
                    output_dir=output_dir,
                    fetched_at=FIXED_TIME,
                )

            self.assertEqual(result.financials_path.read_bytes(), body)
            self.assertEqual(
                result.financials_path.name,
                "1234_t__financials__20260722T000000Z.json",
            )

        self.assertEqual(len(seen_requests), 1)
        request = seen_requests[0]
        self.assertEqual(request.url.path, "/v1/companies/E01234/financials")
        self.assertEqual(request.url.params["years"], "5")
        self.assertEqual(request.url.params["period"], "annual")


if __name__ == "__main__":
    unittest.main()
