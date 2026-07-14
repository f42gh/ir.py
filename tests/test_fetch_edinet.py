from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from src import fetch_edinet


FIXED_TIME = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def search_payload(*companies: dict[str, object]) -> dict[str, object]:
    return {"data": list(companies), "meta": {"query": "3092"}}


def zozo_company(**overrides: object) -> dict[str, object]:
    company: dict[str, object] = {
        "name": "株式会社ＺＯＺＯ",
        "name_ja": "株式会社ＺＯＺＯ",
        "sec_code": "30920",
        "edinet_code": "E05725",
    }
    company.update(overrides)
    return company


def financial_payload() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for year in range(2025, 2020, -1):
        rows.append(
            {
                "fiscal_year": year,
                "accounting_standard": "JP",
                "revenue": 100_000_000_000 + year,
                "operating_income": 20_000_000_000 + year,
                "net_income": 14_000_000_000 + year,
                "total_assets": 180_000_000_000 + year,
                "shareholders_equity": 90_000_000_000 + year,
                "cf_operating": 24_000_000_000 + year,
                "cf_investing": -6_000_000_000 - year,
                "roe_official": 0.155,
                "doc_id": f"S{year}",
                "submit_date": f"{year}-06-30",
                "edinet_filing_url": f"https://example.com/{year}",
            }
        )
    return {"data": rows, "meta": {}}


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


class ApiKeyTests(unittest.TestCase):
    def test_missing_api_key_fails_before_client_is_created(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(fetch_edinet.os.environ, {}, clear=True),
            patch.object(fetch_edinet.httpx, "Client") as client_class,
            redirect_stderr(stderr),
        ):
            exit_code = fetch_edinet.main([])

        self.assertEqual(exit_code, 1)
        client_class.assert_not_called()
        self.assertIn("EDINET_DB_API_KEY", stderr.getvalue())

    def test_api_key_is_trimmed(self) -> None:
        self.assertEqual(
            fetch_edinet.require_api_key({"EDINET_DB_API_KEY": "  secret  "}),
            "secret",
        )


class CompanySelectionTests(unittest.TestCase):
    def test_selects_exact_security_code_and_normalized_name(self) -> None:
        payload = search_payload(
            {"name": "別会社", "sec_code": "30921", "edinet_code": "E00001"},
            zozo_company(),
        )

        selected = fetch_edinet.select_zozo(payload)

        self.assertEqual(selected["edinet_code"], "E05725")

    def test_rejects_no_exact_security_code(self) -> None:
        with self.assertRaisesRegex(fetch_edinet.FetchError, "見つかりません"):
            fetch_edinet.select_zozo(search_payload())

    def test_rejects_duplicate_exact_security_code(self) -> None:
        with self.assertRaisesRegex(fetch_edinet.FetchError, "複数"):
            fetch_edinet.select_zozo(
                search_payload(zozo_company(), zozo_company(name="株式会社ZOZO"))
            )

    def test_rejects_unexpected_name(self) -> None:
        with self.assertRaisesRegex(fetch_edinet.FetchError, "企業名"):
            fetch_edinet.select_zozo(
                search_payload(zozo_company(name="別会社", name_ja="別会社"))
            )

    def test_rejects_unexpected_edinet_code(self) -> None:
        with self.assertRaisesRegex(fetch_edinet.FetchError, "E05725"):
            fetch_edinet.select_zozo(
                search_payload(zozo_company(edinet_code="E00000"))
            )


class FetchJsonTests(unittest.TestCase):
    def make_client(self, handler: httpx.MockTransport) -> httpx.Client:
        return httpx.Client(base_url=fetch_edinet.BASE_URL, transport=handler)

    def test_maps_auth_and_rate_limit_errors_without_response_body(self) -> None:
        for status, expected in ((401, "APIキー"), (403, "APIキー"), (429, "利用上限")):
            with self.subTest(status=status):
                transport = httpx.MockTransport(
                    lambda request, status=status: httpx.Response(
                        status, content=b'{"secret":"must-not-appear"}'
                    )
                )
                with self.make_client(transport) as client:
                    with self.assertRaisesRegex(fetch_edinet.FetchError, expected) as caught:
                        fetch_edinet.fetch_json(
                            client, "/example", params={}, label="テスト取得"
                        )
                self.assertNotIn("must-not-appear", str(caught.exception))

    def test_rejects_other_non_success_status(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, content=b"server error")
        )
        with self.make_client(transport) as client:
            with self.assertRaisesRegex(fetch_edinet.FetchError, "HTTP 500"):
                fetch_edinet.fetch_json(
                    client, "/example", params={}, label="テスト取得"
                )

    def test_rejects_invalid_json(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        )
        with self.make_client(transport) as client:
            with self.assertRaisesRegex(fetch_edinet.FetchError, "有効なJSON"):
                fetch_edinet.fetch_json(
                    client, "/example", params={}, label="テスト取得"
                )

    def test_maps_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with self.make_client(httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(fetch_edinet.FetchError, "タイムアウト"):
                fetch_edinet.fetch_json(
                    client, "/example", params={}, label="テスト取得"
                )


class InspectionTests(unittest.TestCase):
    def test_reports_missing_and_zero_without_confusing_them(self) -> None:
        payload = financial_payload()
        rows = payload["data"]
        assert isinstance(rows, list)
        del rows[0]["cf_investing"]
        rows[1]["cf_investing"] = 0
        rows[2]["doc_id"] = None

        result = fetch_edinet.inspect_financials(payload)

        self.assertEqual(result.fiscal_years, (2025, 2024, 2023, 2022, 2021))
        self.assertEqual(result.year_order, "descending")
        self.assertEqual(result.accounting_standards, ("JP",))
        self.assertEqual(result.missing_values["cf_investing"], (2025,))
        self.assertEqual(result.zero_values["cf_investing"], (2024,))
        self.assertEqual(result.missing_source_values["doc_id"], (2023,))

    def test_rejects_wrong_year_count(self) -> None:
        payload = financial_payload()
        rows = payload["data"]
        assert isinstance(rows, list)
        rows.pop()
        with self.assertRaisesRegex(fetch_edinet.FetchError, "5年度分"):
            fetch_edinet.inspect_financials(payload)

    def test_rejects_duplicate_or_unordered_years(self) -> None:
        duplicate = financial_payload()
        duplicate_rows = duplicate["data"]
        assert isinstance(duplicate_rows, list)
        duplicate_rows[1]["fiscal_year"] = 2025
        with self.assertRaisesRegex(fetch_edinet.FetchError, "重複"):
            fetch_edinet.inspect_financials(duplicate)

        unordered = financial_payload()
        unordered_rows = unordered["data"]
        assert isinstance(unordered_rows, list)
        unordered_rows[1], unordered_rows[2] = unordered_rows[2], unordered_rows[1]
        with self.assertRaisesRegex(fetch_edinet.FetchError, "年度順"):
            fetch_edinet.inspect_financials(unordered)


class WorkflowTests(unittest.TestCase):
    def test_preserves_exact_response_bytes_and_request_contract(self) -> None:
        search_body = json_bytes(search_payload(zozo_company()))
        financial_body = json_bytes(financial_payload())
        seen_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            self.assertEqual(request.headers["X-API-Key"], "test-key")
            if request.url.path == "/v1/search":
                self.assertEqual(request.url.params["q"], "3092")
                self.assertEqual(request.url.params["limit"], "5")
                return httpx.Response(200, content=search_body)
            if request.url.path == "/v1/companies/E05725/financials":
                self.assertEqual(request.url.params["years"], "5")
                self.assertEqual(request.url.params["period"], "annual")
                self.assertNotIn("include_nulls", request.url.params)
                return httpx.Response(200, content=financial_body)
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with httpx.Client(
                base_url=fetch_edinet.BASE_URL,
                headers={"X-API-Key": "test-key"},
                transport=httpx.MockTransport(handler),
            ) as client:
                result = fetch_edinet.fetch_zozo(
                    client, output_dir=output_dir, clock=lambda: FIXED_TIME
                )

            self.assertEqual(len(seen_requests), 2)
            self.assertEqual(result.search_path.read_bytes(), search_body)
            self.assertEqual(result.financials_path.read_bytes(), financial_body)
            self.assertEqual(
                result.search_path.name, "zozo__search__20260714T120000Z.json"
            )
            self.assertNotIn(b"test-key", result.search_path.read_bytes())
            self.assertNotIn(b"test-key", result.financials_path.read_bytes())

    def test_http_failures_leave_no_raw_files(self) -> None:
        search_body = json_bytes(search_payload(zozo_company()))

        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                def handler(
                    request: httpx.Request, status: int = status
                ) -> httpx.Response:
                    if request.url.path == "/v1/search":
                        return httpx.Response(200, content=search_body)
                    return httpx.Response(status, content=b'{"error":"invalid"}')

                with tempfile.TemporaryDirectory() as directory:
                    output_dir = Path(directory)
                    with httpx.Client(
                        base_url=fetch_edinet.BASE_URL,
                        transport=httpx.MockTransport(handler),
                    ) as client:
                        with self.assertRaises(fetch_edinet.FetchError):
                            fetch_edinet.fetch_zozo(client, output_dir=output_dir)
                    self.assertEqual(list(output_dir.iterdir()), [])

    def test_timeout_leaves_no_raw_files(self) -> None:
        search_body = json_bytes(search_payload(zozo_company()))

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/search":
                return httpx.Response(200, content=search_body)
            raise httpx.ReadTimeout("timed out", request=request)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with httpx.Client(
                base_url=fetch_edinet.BASE_URL,
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(fetch_edinet.FetchError):
                    fetch_edinet.fetch_zozo(client, output_dir=output_dir)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_invalid_financial_json_leaves_no_raw_files(self) -> None:
        search_body = json_bytes(search_payload(zozo_company()))

        def handler(request: httpx.Request) -> httpx.Response:
            content = search_body if request.url.path == "/v1/search" else b"invalid"
            return httpx.Response(200, content=content)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with httpx.Client(
                base_url=fetch_edinet.BASE_URL,
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(fetch_edinet.FetchError):
                    fetch_edinet.fetch_zozo(client, output_dir=output_dir)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_existing_raw_file_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "zozo__search__20260714T120000Z.json"
            existing.write_bytes(b"original")

            with self.assertRaisesRegex(fetch_edinet.FetchError, "上書きしません"):
                fetch_edinet.save_raw(
                    b"replacement",
                    output_dir=output_dir,
                    kind="search",
                    fetched_at=FIXED_TIME,
                )

            self.assertEqual(existing.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
