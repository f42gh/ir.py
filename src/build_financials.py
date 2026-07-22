"""Build deterministic frontend financial JSON from a saved EDINET DB response."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_EDINET_CODE = "E05725"
EXPECTED_PERIOD = "annual"
EXPECTED_YEAR_COUNT = 5
INPUT_NAME_PATTERN = re.compile(
    r"^(?P<slug>[a-z0-9_]+)__financials__(?P<timestamp>\d{8}T\d{6}Z)\.json$"
)

MONEY_FIELDS = {
    "revenue": "revenue",
    "operating_income": "operating_income",
    "net_income": "net_income",
    "total_assets": "total_assets",
    "equity": "shareholders_equity",
    "operating_cash_flow": "cf_operating",
    "investing_cash_flow": "cf_investing",
}

ACCOUNTING_STANDARD_MAP = {
    "JP": "JGAAP",
    "JP_GAAP": "JGAAP",
    "IFRS": "IFRS",
    "US": "USGAAP",
    "US_GAAP": "USGAAP",
}


class BuildError(Exception):
    """An expected, user-facing Phase 3 build failure."""


@dataclass(frozen=True)
class CompanySpec:
    """Metadata needed to validate and identify one company's raw data."""

    ticker: str
    name: str
    edinet_code: str
    slug: str
    order: int


def parse_fetched_at(input_path: Path) -> str:
    """Extract and validate the UTC fetch timestamp encoded in a raw filename."""

    match = INPUT_NAME_PATTERN.fullmatch(input_path.name)
    if match is None:
        raise BuildError(
            "入力ファイル名は "
            "<企業slug>__financials__YYYYMMDDTHHMMSSZ.json 形式にしてください。"
        )
    timestamp = match.group("timestamp")
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise BuildError("入力ファイル名の取得日時が不正です。") from exc
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_input_slug(input_path: Path) -> str:
    """Extract the stable company slug encoded in a raw filename."""

    match = INPUT_NAME_PATTERN.fullmatch(input_path.name)
    if match is None:
        raise BuildError(
            "入力ファイル名は "
            "<企業slug>__financials__YYYYMMDDTHHMMSSZ.json 形式にしてください。"
        )
    return match.group("slug")


def ticker_slug(ticker: str) -> str:
    """Convert a ticker to the same stable slug used by the fetch CLI."""

    slug = re.sub(r"[^a-z0-9]+", "_", ticker.lower()).strip("_")
    if not slug:
        raise BuildError(f"ティッカーをファイル名へ変換できません: {ticker}")
    return slug


def load_company_specs(path: Path) -> tuple[CompanySpec, ...]:
    """Load ordered company identities from the local metadata JSON."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BuildError(f"企業メタデータを読み込めません: {path}") from exc
    if not isinstance(payload, dict):
        raise BuildError("企業メタデータのトップレベルがオブジェクトではありません。")

    specs: list[CompanySpec] = []
    seen_codes: set[str] = set()
    for order, (ticker, meta) in enumerate(payload.items()):
        if not isinstance(ticker, str) or not isinstance(meta, dict):
            raise BuildError("企業メタデータに不正な項目があります。")
        name = meta.get("name")
        edinet_code = meta.get("edinet_code")
        if not isinstance(name, str) or not name.strip():
            raise BuildError(f"{ticker} の企業名が不正です。")
        if not isinstance(edinet_code, str) or not re.fullmatch(r"E\d{5}", edinet_code):
            raise BuildError(f"{ticker} のEDINETコードが不正です。")
        if edinet_code in seen_codes:
            raise BuildError(f"EDINETコードが重複しています: {edinet_code}")
        seen_codes.add(edinet_code)
        specs.append(
            CompanySpec(
                ticker=ticker,
                name=name.strip(),
                edinet_code=edinet_code,
                slug=ticker_slug(ticker),
                order=order,
            )
        )

    if not specs:
        raise BuildError("企業メタデータが空です。")
    return tuple(specs)


def load_raw(input_path: Path) -> dict[str, Any]:
    """Load a raw JSON object without modifying the source file."""

    try:
        payload = json.loads(input_path.read_bytes())
    except FileNotFoundError as exc:
        raise BuildError(f"入力ファイルが見つかりません: {input_path}") from exc
    except OSError as exc:
        raise BuildError(f"入力ファイルを読み込めません: {input_path}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BuildError("入力ファイルが有効なUTF-8 JSONではありません。") from exc
    if not isinstance(payload, dict):
        raise BuildError("rawのトップレベルがオブジェクトではありません。")
    return payload


def normalize_money(value: object, *, field: str, fiscal_year: int) -> int | None:
    """Convert an integer-like JSON number to integer yen."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildError(f"{fiscal_year}年度の {field} が数値ではありません。")
    if not math.isfinite(value) or int(value) != value:
        raise BuildError(f"{fiscal_year}年度の {field} が整数円ではありません。")
    return int(value)


def normalize_accounting_standard(value: object) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    return ACCOUNTING_STANDARD_MAP.get(value, "UNKNOWN")


def normalize_roe(value: object, *, fiscal_year: int) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildError(f"{fiscal_year}年度の roe_official が数値ではありません。")
    if not math.isfinite(value):
        raise BuildError(f"{fiscal_year}年度の roe_official が有限値ではありません。")
    return round_percentage(value * 100)


def normalize_optional_string(
    value: object, *, field: str, fiscal_year: int
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BuildError(f"{fiscal_year}年度の {field} が文字列ではありません。")
    return value


def normalize_filed_at(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").date().isoformat()
    except ValueError:
        return None


def round_percentage(value: float) -> float:
    rounded = round(value, 4)
    return 0.0 if rounded == 0 else rounded


def calculate_revenue_yoy(
    current_revenue: int | None, previous_revenue: int | None
) -> float | None:
    if current_revenue is None or previous_revenue in (None, 0):
        return None
    return round_percentage((current_revenue / previous_revenue - 1) * 100)


def calculate_operating_margin(
    operating_income: int | None, revenue: int | None
) -> float | None:
    if operating_income is None or revenue in (None, 0):
        return None
    return round_percentage(operating_income / revenue * 100)


def calculate_free_cash_flow(
    operating_cash_flow: int | None, investing_cash_flow: int | None
) -> int | None:
    if operating_cash_flow is None or investing_cash_flow is None:
        return None
    return operating_cash_flow + investing_cash_flow


def calculate_revenue_cagr_3y(
    current_revenue: int | None, starting_revenue: int | None
) -> float | None:
    if current_revenue is None or starting_revenue is None:
        return None
    if starting_revenue <= 0 or current_revenue < 0:
        return None
    return round_percentage(((current_revenue / starting_revenue) ** (1 / 3) - 1) * 100)


def _validated_rows(
    payload: Mapping[str, Any], *, expected_edinet_code: str = EXPECTED_EDINET_CODE
) -> list[dict[str, Any]]:
    meta = payload.get("meta")
    rows = payload.get("data")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise BuildError("rawにはdata配列とmetaオブジェクトが必要です。")
    if meta.get("edinet_code") != expected_edinet_code:
        raise BuildError(
            "rawのEDINETコードが企業メタデータと一致しません: "
            f"expected={expected_edinet_code}, actual={meta.get('edinet_code')}"
        )
    if meta.get("period") != EXPECTED_PERIOD:
        raise BuildError("rawが年次財務データではありません。")
    if len(rows) != EXPECTED_YEAR_COUNT:
        raise BuildError(f"rawが{EXPECTED_YEAR_COUNT}年度分ではありません。")
    if not all(isinstance(row, dict) for row in rows):
        raise BuildError("dataにオブジェクトではない年度行が含まれています。")

    years: list[int] = []
    for row in rows:
        fiscal_year = row.get("fiscal_year")
        if not isinstance(fiscal_year, int) or isinstance(fiscal_year, bool):
            raise BuildError("fiscal_year が整数ではありません。")
        years.append(fiscal_year)
    if len(set(years)) != len(years):
        raise BuildError("fiscal_year が重複しています。")
    return sorted(rows, key=lambda row: row["fiscal_year"])


def _transform_period(row: Mapping[str, Any], *, fetched_at: str) -> dict[str, Any]:
    fiscal_year = row["fiscal_year"]
    metrics = {
        output_field: normalize_money(
            row.get(raw_field), field=raw_field, fiscal_year=fiscal_year
        )
        for output_field, raw_field in MONEY_FIELDS.items()
    }
    metrics["roe_pct"] = normalize_roe(
        row.get("roe_official"), fiscal_year=fiscal_year
    )

    return {
        "fiscal_year": fiscal_year,
        "fiscal_year_end": None,
        "accounting_standard": normalize_accounting_standard(
            row.get("accounting_standard")
        ),
        "consolidated": True,
        "metrics": metrics,
        "calculated_metrics": {},
        "source_document": {
            "document_id": normalize_optional_string(
                row.get("doc_id"), field="doc_id", fiscal_year=fiscal_year
            ),
            "document_type": "annual_securities_report",
            "filed_at": normalize_filed_at(row.get("submit_date")),
            "url": normalize_optional_string(
                row.get("edinet_filing_url"),
                field="edinet_filing_url",
                fiscal_year=fiscal_year,
            ),
        },
        "fetched_at": fetched_at,
    }


def _add_calculated_metrics(periods: list[dict[str, Any]]) -> None:
    for index, period in enumerate(periods):
        metrics = period["metrics"]
        previous_metrics = periods[index - 1]["metrics"] if index > 0 else None
        starting_metrics = periods[index - 3]["metrics"] if index >= 3 else None
        period["calculated_metrics"] = {
            "revenue_yoy_pct": calculate_revenue_yoy(
                metrics["revenue"],
                previous_metrics["revenue"] if previous_metrics else None,
            ),
            "operating_margin_pct": calculate_operating_margin(
                metrics["operating_income"], metrics["revenue"]
            ),
            "free_cash_flow": calculate_free_cash_flow(
                metrics["operating_cash_flow"], metrics["investing_cash_flow"]
            ),
            "revenue_cagr_3y_pct": calculate_revenue_cagr_3y(
                metrics["revenue"],
                starting_metrics["revenue"] if starting_metrics else None,
            ),
        }


def build_document(payload: Mapping[str, Any], *, input_path: Path) -> dict[str, Any]:
    """Validate and transform a ZOZO raw payload into schema version 1.0."""

    fetched_at = parse_fetched_at(input_path)
    periods = [
        _transform_period(row, fetched_at=fetched_at)
        for row in _validated_rows(payload)
    ]
    _add_calculated_metrics(periods)
    return {
        "schema_version": "1.0",
        "generated_at": fetched_at,
        "companies": [
            {
                "ticker": "3092.T",
                "name": "ZOZO",
                "edinet_code": EXPECTED_EDINET_CODE,
                "currency": "JPY",
                "periods": periods,
            }
        ],
    }


def build_company(
    payload: Mapping[str, Any], *, input_path: Path, company: CompanySpec
) -> tuple[dict[str, Any], str]:
    """Build one normalized company object and return its fetch timestamp."""

    input_slug = parse_input_slug(input_path)
    if input_slug != company.slug:
        raise BuildError(
            f"rawファイル名の企業slugが一致しません: {input_slug} != {company.slug}"
        )
    fetched_at = parse_fetched_at(input_path)
    periods = [
        _transform_period(row, fetched_at=fetched_at)
        for row in _validated_rows(
            payload, expected_edinet_code=company.edinet_code
        )
    ]
    _add_calculated_metrics(periods)
    return (
        {
            "ticker": company.ticker,
            "name": company.name,
            "edinet_code": company.edinet_code,
            "currency": "JPY",
            "periods": periods,
        },
        fetched_at,
    )


def build_multi_document(
    inputs: Sequence[tuple[CompanySpec, Path, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Build one deterministic frontend document from multiple company raws."""

    if not inputs:
        raise BuildError("分析用JSONへ変換するrawがありません。")

    companies: list[dict[str, Any]] = []
    fetched_at_values: list[str] = []
    seen_tickers: set[str] = set()
    for company, input_path, payload in sorted(inputs, key=lambda item: item[0].order):
        if company.ticker in seen_tickers:
            raise BuildError(f"同じ企業のrawが重複しています: {company.ticker}")
        built_company, fetched_at = build_company(
            payload, input_path=input_path, company=company
        )
        seen_tickers.add(company.ticker)
        companies.append(built_company)
        fetched_at_values.append(fetched_at)

    return {
        "schema_version": "1.0",
        "generated_at": max(fetched_at_values),
        "companies": companies,
    }


def resolve_inputs(
    *,
    input_paths: Sequence[Path] | None,
    input_dir: Path | None,
    company_specs: Sequence[CompanySpec],
) -> list[tuple[CompanySpec, Path, dict[str, Any]]]:
    """Resolve explicit or latest-per-company raw paths against company metadata."""

    specs_by_slug = {company.slug: company for company in company_specs}
    if len(specs_by_slug) != len(company_specs):
        raise BuildError("企業メタデータのslugが重複しています。")

    if input_dir is not None:
        try:
            candidates = sorted(input_dir.glob("*__financials__*.json"))
        except OSError as exc:
            raise BuildError(f"rawディレクトリを読み込めません: {input_dir}") from exc
        latest_by_slug: dict[str, Path] = {}
        for candidate in candidates:
            try:
                slug = parse_input_slug(candidate)
                parse_fetched_at(candidate)
            except BuildError:
                continue
            if slug in specs_by_slug:
                latest_by_slug[slug] = candidate
        paths = list(latest_by_slug.values())
    else:
        paths = list(input_paths or ())

    if not paths:
        raise BuildError("企業メタデータに対応する財務rawが見つかりません。")

    resolved: list[tuple[CompanySpec, Path, dict[str, Any]]] = []
    seen_slugs: set[str] = set()
    for path in paths:
        slug = parse_input_slug(path)
        company = specs_by_slug.get(slug)
        if company is None:
            raise BuildError(f"rawに対応する企業メタデータがありません: {path.name}")
        if slug in seen_slugs:
            raise BuildError(f"同じ企業のrawが複数指定されています: {company.ticker}")
        seen_slugs.add(slug)
        resolved.append((company, path, load_raw(path)))
    return resolved


def write_json_atomic(document: Mapping[str, Any], output_path: Path) -> None:
    """Write deterministic UTF-8 JSON without exposing a partial output file."""

    try:
        serialized = (
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as exc:
        raise BuildError("画面用JSONへ変換できない値が含まれています。") from exc

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BuildError(f"出力先ディレクトリを作成できません: {output_path.parent}") from exc

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, output_path)
    except OSError as exc:
        raise BuildError(f"画面用JSONを保存できません: {output_path}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="保存済みEDINET DBレスポンスから画面用JSONを生成します。"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input",
        action="append",
        type=Path,
        help="財務raw JSON。複数社はオプションを繰り返して指定",
    )
    source.add_argument(
        "--input-dir",
        type=Path,
        help="企業ごとに最新の財務rawを選ぶディレクトリ",
    )
    parser.add_argument(
        "--companies",
        type=Path,
        help="複数社ビルド用の企業メタデータJSON",
    )
    parser.add_argument("--output", required=True, type=Path, help="画面用JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_paths = args.input or []
        if any(path.resolve() == args.output.resolve() for path in input_paths):
            raise BuildError("入力ファイルと出力ファイルには別のパスを指定してください。")
        if args.input_dir is not None and args.companies is None:
            raise BuildError("--input-dir には --companies の指定が必要です。")
        if len(input_paths) > 1 and args.companies is None:
            raise BuildError("複数の --input には --companies の指定が必要です。")

        if args.companies is None:
            input_path = input_paths[0]
            payload = load_raw(input_path)
            document = build_document(payload, input_path=input_path)
        else:
            company_specs = load_company_specs(args.companies)
            inputs = resolve_inputs(
                input_paths=input_paths,
                input_dir=args.input_dir,
                company_specs=company_specs,
            )
            document = build_multi_document(inputs)
        write_json_atomic(document, args.output)
    except BuildError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(f"生成: {args.output}")
    for company in document["companies"]:
        years = ", ".join(str(period["fiscal_year"]) for period in company["periods"])
        print(
            f"企業: {company['ticker']} {company['name']} "
            f"({company['edinet_code']}) [{years}]"
        )
    print(f"企業数: {len(document['companies'])}")
    print(f"取得日時: {document['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
