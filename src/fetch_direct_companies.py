"""Fetch five annual financial rows for every directly resolvable company."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

if __package__:
    from .fetch_edinet import (
        BASE_URL,
        RAW_DIR,
        TIMEOUT_SECONDS,
        FetchError,
        FinancialInspection,
        fetch_json,
        inspect_financials,
        require_api_key,
        save_raw,
        utc_now,
    )
else:
    from fetch_edinet import (
        BASE_URL,
        RAW_DIR,
        TIMEOUT_SECONDS,
        FetchError,
        FinancialInspection,
        fetch_json,
        inspect_financials,
        require_api_key,
        save_raw,
        utc_now,
    )


COMPANIES_PATH = Path(__file__).resolve().parents[1] / "data" / "COMPANIES.json"


@dataclass(frozen=True)
class DirectCompany:
    ticker: str
    name: str
    edinet_code: str


@dataclass(frozen=True)
class DirectFetchResult:
    company: DirectCompany
    financials_path: Path
    inspection: FinancialInspection


def load_direct_companies(path: Path = COMPANIES_PATH) -> tuple[DirectCompany, ...]:
    """Load companies explicitly marked as directly resolvable in EDINET."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FetchError(f"企業メタデータを読み込めませんでした: {path}") from exc

    if not isinstance(payload, dict):
        raise FetchError("企業メタデータのトップレベルがオブジェクトではありません。")

    companies: list[DirectCompany] = []
    for ticker, meta in payload.items():
        if not isinstance(ticker, str) or not isinstance(meta, dict):
            raise FetchError("企業メタデータに不正な項目があります。")
        if meta.get("status") != "direct":
            continue

        name = meta.get("name")
        edinet_code = meta.get("edinet_code")
        if not isinstance(name, str) or not name.strip():
            raise FetchError(f"{ticker} の企業名が不正です。")
        if not isinstance(edinet_code, str) or not re.fullmatch(r"E\d{5}", edinet_code):
            raise FetchError(f"{ticker} のEDINETコードが不正です。")

        companies.append(
            DirectCompany(
                ticker=ticker,
                name=name.strip(),
                edinet_code=edinet_code,
            )
        )

    if not companies:
        raise FetchError("直接取得対象の企業がありません。")
    return tuple(companies)


def ticker_slug(ticker: str) -> str:
    """Return a filesystem-safe, stable slug derived from the ticker."""

    slug = re.sub(r"[^a-z0-9]+", "_", ticker.lower()).strip("_")
    if not slug:
        raise FetchError(f"ティッカーをファイル名へ変換できません: {ticker}")
    return slug


def fetch_direct_company(
    client: httpx.Client,
    company: DirectCompany,
    *,
    output_dir: Path = RAW_DIR,
    fetched_at: datetime | None = None,
) -> DirectFetchResult:
    """Fetch, validate, and preserve one company's five annual rows."""

    body, payload = fetch_json(
        client,
        f"/companies/{company.edinet_code}/financials",
        params={"years": 5, "period": "annual"},
        label=f"{company.name}の財務データ取得",
    )
    inspection = inspect_financials(payload)
    path = save_raw(
        body,
        output_dir=output_dir,
        kind="financials",
        fetched_at=utc_now() if fetched_at is None else fetched_at,
        slug=ticker_slug(company.ticker),
    )
    return DirectFetchResult(
        company=company,
        financials_path=path,
        inspection=inspection,
    )


def print_result(result: DirectFetchResult) -> None:
    years = ", ".join(map(str, result.inspection.fiscal_years))
    print(
        f"成功: {result.company.ticker} {result.company.name} "
        f"({result.company.edinet_code}) [{years}]"
    )
    print(f"  raw: {result.financials_path}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("エラー: このCLIはコマンドライン引数を受け取りません。", file=sys.stderr)
        return 1

    try:
        api_key = require_api_key()
        companies = load_direct_companies()
    except FetchError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    results: list[DirectFetchResult] = []
    failures: list[tuple[DirectCompany, FetchError]] = []
    with httpx.Client(
        base_url=BASE_URL,
        headers={"X-API-Key": api_key},
        timeout=TIMEOUT_SECONDS,
    ) as client:
        for company in companies:
            try:
                result = fetch_direct_company(client, company)
            except FetchError as exc:
                failures.append((company, exc))
                print(f"失敗: {company.ticker} {company.name}: {exc}", file=sys.stderr)
                if "HTTP 429" in str(exc):
                    print("API利用上限のため残りの取得を中止します。", file=sys.stderr)
                    break
            else:
                results.append(result)
                print_result(result)

    print(f"完了: 成功 {len(results)}社 / 失敗 {len(failures)}社")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
