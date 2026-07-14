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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_EDINET_CODE = "E05725"
EXPECTED_PERIOD = "annual"
EXPECTED_YEAR_COUNT = 5
INPUT_NAME_PATTERN = re.compile(
    r"^zozo__financials__(?P<timestamp>\d{8}T\d{6}Z)\.json$"
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


def parse_fetched_at(input_path: Path) -> str:
    """Extract and validate the UTC fetch timestamp encoded in a raw filename."""

    match = INPUT_NAME_PATTERN.fullmatch(input_path.name)
    if match is None:
        raise BuildError(
            "入力ファイル名は "
            "zozo__financials__YYYYMMDDTHHMMSSZ.json 形式にしてください。"
        )
    timestamp = match.group("timestamp")
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise BuildError("入力ファイル名の取得日時が不正です。") from exc
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _validated_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    meta = payload.get("meta")
    rows = payload.get("data")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise BuildError("rawにはdata配列とmetaオブジェクトが必要です。")
    if meta.get("edinet_code") != EXPECTED_EDINET_CODE:
        raise BuildError("rawのEDINETコードがE05725ではありません。")
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
    parser.add_argument("--input", required=True, type=Path, help="財務raw JSON")
    parser.add_argument("--output", required=True, type=Path, help="画面用JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise BuildError("入力ファイルと出力ファイルには別のパスを指定してください。")
        payload = load_raw(args.input)
        document = build_document(payload, input_path=args.input)
        write_json_atomic(document, args.output)
    except BuildError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    periods = document["companies"][0]["periods"]
    years = ", ".join(str(period["fiscal_year"]) for period in periods)
    print(f"生成: {args.output}")
    print(f"企業: ZOZO ({EXPECTED_EDINET_CODE})")
    print(f"対象年度: {years}")
    print(f"取得日時: {document['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
