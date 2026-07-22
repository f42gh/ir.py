from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import build_financials


def raw_payload(edinet_code: str, *, revenue: int) -> dict[str, object]:
    return {
        "data": [
            {
                "fiscal_year": year,
                "accounting_standard": "JP",
                "revenue": revenue + year,
                "operating_income": 20_000_000_000,
                "net_income": 10_000_000_000,
                "total_assets": 150_000_000_000,
                "shareholders_equity": 70_000_000_000,
                "cf_operating": 15_000_000_000,
                "cf_investing": -5_000_000_000,
                "roe_official": 0.1,
                "doc_id": f"S{year}",
                "submit_date": f"{year}-06-30 15:00",
                "edinet_filing_url": f"https://example.com/{edinet_code}/{year}",
            }
            for year in range(2021, 2026)
        ],
        "meta": {
            "edinet_code": edinet_code,
            "period": "annual",
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class MultipleCompanyBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir()
        self.companies_path = self.root / "companies.json"
        write_json(
            self.companies_path,
            {
                "2222.T": {
                    "name": "Second in filename, first in metadata",
                    "edinet_code": "E00002",
                },
                "1111.T": {
                    "name": "First in filename, second in metadata",
                    "edinet_code": "E00001",
                },
            },
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_builds_latest_raw_per_company_in_metadata_order(self) -> None:
        old_path = self.raw_dir / "2222_t__financials__20260720T000000Z.json"
        newest_path = self.raw_dir / "2222_t__financials__20260722T000000Z.json"
        other_path = self.raw_dir / "1111_t__financials__20260721T000000Z.json"
        write_json(old_path, raw_payload("E00002", revenue=100_000_000_000))
        write_json(newest_path, raw_payload("E00002", revenue=200_000_000_000))
        write_json(other_path, raw_payload("E00001", revenue=300_000_000_000))

        specs = build_financials.load_company_specs(self.companies_path)
        inputs = build_financials.resolve_inputs(
            input_paths=None,
            input_dir=self.raw_dir,
            company_specs=specs,
        )
        document = build_financials.build_multi_document(inputs)

        self.assertEqual(
            [company["ticker"] for company in document["companies"]],
            ["2222.T", "1111.T"],
        )
        self.assertEqual(document["generated_at"], "2026-07-22T00:00:00Z")
        self.assertEqual(
            document["companies"][0]["periods"][0]["metrics"]["revenue"],
            200_000_002_021,
        )

    def test_cli_writes_combined_document(self) -> None:
        write_json(
            self.raw_dir / "2222_t__financials__20260722T000000Z.json",
            raw_payload("E00002", revenue=200_000_000_000),
        )
        write_json(
            self.raw_dir / "1111_t__financials__20260721T000000Z.json",
            raw_payload("E00001", revenue=300_000_000_000),
        )
        output_path = self.root / "frontend" / "financials.json"

        exit_code = build_financials.main(
            [
                "--input-dir",
                str(self.raw_dir),
                "--companies",
                str(self.companies_path),
                "--output",
                str(output_path),
            ]
        )

        self.assertEqual(exit_code, 0)
        document = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(document["companies"]), 2)

    def test_mismatched_edinet_code_preserves_existing_output(self) -> None:
        write_json(
            self.raw_dir / "2222_t__financials__20260722T000000Z.json",
            raw_payload("E99999", revenue=200_000_000_000),
        )
        output_path = self.root / "financials.json"
        output_path.write_bytes(b"original")

        exit_code = build_financials.main(
            [
                "--input-dir",
                str(self.raw_dir),
                "--companies",
                str(self.companies_path),
                "--output",
                str(output_path),
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(output_path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
