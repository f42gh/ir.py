"""Fetch and preserve ZOZO financial responses from the EDINET DB API."""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "https://edinetdb.jp/v1"
API_KEY_ENV = "EDINET_DB_API_KEY"
SEARCH_QUERY = "3092"
EXPECTED_SEC_CODE = "30920"
EXPECTED_COMPANY_NAME = "株式会社ZOZO"
EXPECTED_EDINET_CODE = "E05725"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
TIMEOUT_SECONDS = 10.0

FINANCIAL_FIELDS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "shareholders_equity",
    "cf_operating",
    "cf_investing",
    "roe_official",
)
SOURCE_FIELDS = ("doc_id", "submit_date", "edinet_filing_url")


class FetchError(Exception):
    """An expected, user-facing Phase 2 fetch failure."""


@dataclass(frozen=True)
class FinancialInspection:
    fiscal_years: tuple[int, ...]
    year_order: str
    accounting_standards: tuple[str, ...]
    missing_values: dict[str, tuple[int, ...]]
    zero_values: dict[str, tuple[int, ...]]
    missing_source_values: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class FetchResult:
    company_name: str
    edinet_code: str
    search_path: Path
    financials_path: Path
    inspection: FinancialInspection


def require_api_key(environ: Mapping[str, str] | None = None) -> str:
    """Return the configured API key, or fail before any HTTP request."""

    source = os.environ if environ is None else environ
    api_key = source.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise FetchError(
            f"環境変数 {API_KEY_ENV} が未設定です。"
            " .env に設定し、uv run --env-file .env で実行してください。"
        )
    return api_key


def normalize_company_name(value: str) -> str:
    """Normalize full-width Latin characters before comparing a company name."""

    return unicodedata.normalize("NFKC", value).strip()


def select_zozo(search_payload: object) -> dict[str, Any]:
    """Select ZOZO using an exact security-code and normalized-name match."""

    if not isinstance(search_payload, dict) or not isinstance(
        search_payload.get("data"), list
    ):
        raise FetchError("企業検索レスポンスの data が配列ではありません。")

    candidates = [
        item
        for item in search_payload["data"]
        if isinstance(item, dict) and item.get("sec_code") == EXPECTED_SEC_CODE
    ]
    if not candidates:
        raise FetchError(
            f"証券コード {EXPECTED_SEC_CODE} に完全一致する企業が見つかりません。"
        )
    if len(candidates) > 1:
        raise FetchError(f"証券コード {EXPECTED_SEC_CODE} に一致する企業が複数あります。")

    company = candidates[0]
    raw_name = company.get("name_ja") or company.get("name")
    if not isinstance(raw_name, str) or normalize_company_name(
        raw_name
    ) != EXPECTED_COMPANY_NAME:
        raise FetchError("証券コードは一致しましたが、企業名が株式会社ZOZOではありません。")
    if company.get("edinet_code") != EXPECTED_EDINET_CODE:
        raise FetchError("ZOZOのEDINETコードが想定値 E05725 と一致しません。")
    return company


def _response_error(status_code: int, label: str) -> FetchError:
    if status_code in (401, 403):
        return FetchError(
            f"{label}に失敗しました（HTTP {status_code}）。APIキーを確認してください。"
        )
    if status_code == 429:
        return FetchError(
            f"{label}に失敗しました（HTTP 429）。API利用上限を確認してください。"
            " 自動再試行は行いません。"
        )
    return FetchError(f"{label}に失敗しました（HTTP {status_code}）。")


def fetch_json(
    client: httpx.Client,
    endpoint: str,
    *,
    params: Mapping[str, str | int],
    label: str,
) -> tuple[bytes, object]:
    """Fetch one endpoint and return its exact bytes plus decoded JSON."""

    try:
        response = client.get(endpoint, params=params)
    except httpx.TimeoutException as exc:
        raise FetchError(f"{label}がタイムアウトしました。") from exc
    except httpx.RequestError as exc:
        raise FetchError(f"{label}で通信エラーが発生しました。") from exc

    if not 200 <= response.status_code < 300:
        raise _response_error(response.status_code, label)

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise FetchError(f"{label}のレスポンスが有効なJSONではありません。") from exc
    return response.content, payload


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def inspect_financials(payload: object) -> FinancialInspection:
    """Validate five annual rows and report missing and actual-zero values."""

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise FetchError("財務レスポンスの data が配列ではありません。")

    rows = payload["data"]
    if len(rows) != 5:
        raise FetchError(f"財務データが5年度分ではありません（取得件数: {len(rows)}）。")
    if not all(isinstance(row, dict) for row in rows):
        raise FetchError("財務データにオブジェクトではない年度行が含まれています。")

    fiscal_years: list[int] = []
    standards: list[str] = []
    missing_values: dict[str, list[int]] = {field: [] for field in FINANCIAL_FIELDS}
    zero_values: dict[str, list[int]] = {field: [] for field in FINANCIAL_FIELDS}
    missing_source: dict[str, list[int]] = {field: [] for field in SOURCE_FIELDS}

    for row in rows:
        year = row.get("fiscal_year")
        if not isinstance(year, int) or isinstance(year, bool):
            raise FetchError("fiscal_year が整数ではありません。")
        fiscal_years.append(year)

        standard = row.get("accounting_standard")
        if standard is None:
            pass
        elif isinstance(standard, str):
            standards.append(standard)
        else:
            raise FetchError(
                f"{year}年度の accounting_standard が文字列ではありません。"
            )

        for field in FINANCIAL_FIELDS:
            value = row.get(field)
            if value is None:
                missing_values[field].append(year)
            elif not _is_number(value):
                raise FetchError(f"{year}年度の {field} が数値ではありません。")
            elif value == 0:
                zero_values[field].append(year)

        for field in SOURCE_FIELDS:
            value = row.get(field)
            if value is None:
                missing_source[field].append(year)
            elif not isinstance(value, str):
                raise FetchError(f"{year}年度の {field} が文字列ではありません。")

    if len(set(fiscal_years)) != 5:
        raise FetchError("財務データの fiscal_year が重複しています。")
    if fiscal_years == sorted(fiscal_years):
        year_order = "ascending"
    elif fiscal_years == sorted(fiscal_years, reverse=True):
        year_order = "descending"
    else:
        raise FetchError("財務データの年度順が昇順・降順のどちらでもありません。")

    return FinancialInspection(
        fiscal_years=tuple(fiscal_years),
        year_order=year_order,
        accounting_standards=tuple(dict.fromkeys(standards)),
        missing_values={key: tuple(value) for key, value in missing_values.items()},
        zero_values={key: tuple(value) for key, value in zero_values.items()},
        missing_source_values={
            key: tuple(value) for key, value in missing_source.items()
        },
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def save_raw(
    body: bytes,
    *,
    output_dir: Path,
    kind: str,
    fetched_at: datetime,
) -> Path:
    """Save exact response bytes under an exclusive timestamped filename."""

    if fetched_at.tzinfo is None:
        raise FetchError("rawファイルの取得日時にはタイムゾーンが必要です。")
    timestamp = fetched_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"zozo__{kind}__{timestamp}.json"
    try:
        with path.open("xb") as file:
            file.write(body)
    except FileExistsError as exc:
        raise FetchError(f"rawファイルは既に存在するため上書きしません: {path}") from exc
    except OSError as exc:
        raise FetchError(f"rawファイルを保存できませんでした: {path}") from exc
    return path


def load_saved_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FetchError(f"保存済みJSONを読み直せませんでした: {path}") from exc


def fetch_zozo(
    client: httpx.Client,
    *,
    output_dir: Path = RAW_DIR,
    clock: Callable[[], datetime] = utc_now,
) -> FetchResult:
    """Fetch, validate, preserve, reread, and inspect both Phase 2 responses."""

    search_body, search_payload = fetch_json(
        client,
        "/search",
        params={"q": SEARCH_QUERY, "limit": 5},
        label="企業検索",
    )
    company = select_zozo(search_payload)

    financial_body, financial_payload = fetch_json(
        client,
        f"/companies/{EXPECTED_EDINET_CODE}/financials",
        params={"years": 5, "period": "annual"},
        label="財務データ取得",
    )
    inspect_financials(financial_payload)

    search_path = save_raw(
        search_body,
        output_dir=output_dir,
        kind="search",
        fetched_at=clock(),
    )
    financials_path = save_raw(
        financial_body,
        output_dir=output_dir,
        kind="financials",
        fetched_at=clock(),
    )

    inspection = inspect_financials(load_saved_json(financials_path))
    company_name = company.get("name_ja") or company.get("name")
    return FetchResult(
        company_name=str(company_name),
        edinet_code=EXPECTED_EDINET_CODE,
        search_path=search_path,
        financials_path=financials_path,
        inspection=inspection,
    )


def _format_occurrences(values: Mapping[str, tuple[int, ...]]) -> str:
    occurrences = [
        f"{field}={','.join(map(str, years))}"
        for field, years in values.items()
        if years
    ]
    return "; ".join(occurrences) if occurrences else "なし"


def print_result(result: FetchResult) -> None:
    inspection = result.inspection
    standards = ", ".join(inspection.accounting_standards) or "未記載"
    print(f"企業: {result.company_name} ({result.edinet_code})")
    print(f"検索raw: {result.search_path}")
    print(f"財務raw: {result.financials_path}")
    print(f"対象年度: {', '.join(map(str, inspection.fiscal_years))}")
    print(f"年度順: {inspection.year_order}")
    print(f"会計基準: {standards}")
    print(f"欠損値: {_format_occurrences(inspection.missing_values)}")
    print(f"実際のゼロ: {_format_occurrences(inspection.zero_values)}")
    print(f"出典情報の欠損: {_format_occurrences(inspection.missing_source_values)}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("エラー: Phase 2 CLIはコマンドライン引数を受け取りません。", file=sys.stderr)
        return 1

    try:
        api_key = require_api_key()
        with httpx.Client(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=TIMEOUT_SECONDS,
        ) as client:
            result = fetch_zozo(client)
    except FetchError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
