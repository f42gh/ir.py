"""Build the local Parquet/DuckDB warehouse and publish web artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "ir-py-matplotlib-cache"),
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import seaborn as sns
from matplotlib.ticker import FuncFormatter

if __package__:
    from . import build_financials
else:
    import build_financials


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_VERSION = "1.0"
COMPARISON_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MONEY_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "equity",
    "operating_cash_flow",
    "investing_cash_flow",
)
PERCENT_METRICS = ("roe_pct",)

DIM_COMPANIES_SCHEMA = pa.schema(
    [
        ("company_order", pa.int32()),
        ("ticker", pa.string()),
        ("name", pa.string()),
        ("edinet_code", pa.string()),
        ("currency", pa.string()),
        ("status", pa.string()),
        ("tier", pa.string()),
        ("listing_status", pa.string()),
        ("avg_salary_man", pa.float64()),
        ("avg_salary_fiscal_year", pa.int32()),
    ]
)

FINANCIAL_HISTORY_SCHEMA = pa.schema(
    [
        ("company_order", pa.int32()),
        ("ticker", pa.string()),
        ("fiscal_year", pa.int32()),
        ("metric_name", pa.string()),
        ("value", pa.decimal128(38, 4)),
        ("unit", pa.string()),
        ("accounting_standard", pa.string()),
        ("consolidated", pa.bool_()),
        ("document_id", pa.string()),
        ("raw_fetched_at", pa.timestamp("us", tz="UTC")),
        ("raw_sha256", pa.string()),
        ("raw_file", pa.string()),
    ]
)

SOURCE_HISTORY_SCHEMA = pa.schema(
    [
        ("company_order", pa.int32()),
        ("ticker", pa.string()),
        ("fiscal_year", pa.int32()),
        ("document_id", pa.string()),
        ("document_type", pa.string()),
        ("filed_at", pa.date32()),
        ("url", pa.string()),
        ("raw_fetched_at", pa.timestamp("us", tz="UTC")),
        ("raw_sha256", pa.string()),
        ("raw_file", pa.string()),
    ]
)


class AnalyticsError(Exception):
    """An expected, user-facing analytics pipeline failure."""


@dataclass(frozen=True)
class AnalyticsCompany:
    order: int
    ticker: str
    name: str
    edinet_code: str
    status: str
    tier: str
    listing_status: str
    avg_salary_man: float | None
    avg_salary_fiscal_year: int | None
    slug: str

    def as_build_spec(self) -> build_financials.CompanySpec:
        return build_financials.CompanySpec(
            ticker=self.ticker,
            name=self.name,
            edinet_code=self.edinet_code,
            slug=self.slug,
            order=self.order,
        )


@dataclass(frozen=True)
class RawSnapshot:
    company: AnalyticsCompany
    path: Path
    raw_file: str
    fetched_at: datetime
    sha256: str
    periods: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ComparisonPair:
    id: str
    left: str
    right: str


@dataclass(frozen=True)
class StatsMetric:
    id: str
    column: str
    label: str
    english_label: str
    value_kind: str
    unit: str


@dataclass(frozen=True)
class ScatterSpec:
    id: str
    label: str
    description: str
    x_metric: str
    y_metric: str
    x_scale: str = "linear"


@dataclass(frozen=True)
class WarehouseResult:
    mart: pd.DataFrame
    generated_at: datetime
    snapshot_count: int
    missing_tickers: tuple[str, ...]


STATS_METRICS = (
    StatsMetric("revenue", "revenue", "売上高", "Revenue", "money", "百万円"),
    StatsMetric(
        "revenue_yoy_pct",
        "revenue_yoy_pct",
        "売上高YoY",
        "Revenue YoY",
        "percent",
        "%",
    ),
    StatsMetric(
        "operating_income",
        "operating_income",
        "営業利益",
        "Operating income",
        "money",
        "百万円",
    ),
    StatsMetric(
        "operating_margin_pct",
        "operating_margin_pct",
        "営業利益率",
        "Operating margin",
        "percent",
        "%",
    ),
    StatsMetric("roe_pct", "roe_pct", "ROE", "ROE", "percent", "%"),
    StatsMetric(
        "free_cash_flow",
        "free_cash_flow",
        "FCF",
        "Free cash flow",
        "money",
        "百万円",
    ),
)

STATS_METRIC_BY_ID = {metric.id: metric for metric in STATS_METRICS}

SCATTER_SPECS = (
    ScatterSpec(
        "growth-profitability",
        "成長率 × 営業利益率",
        "売上高の前年比成長率と、本業の収益性を比較します。",
        "revenue_yoy_pct",
        "operating_margin_pct",
    ),
    ScatterSpec(
        "margin-return",
        "営業利益率 × ROE",
        "本業の収益性と、株主資本に対する利益効率を比較します。",
        "operating_margin_pct",
        "roe_pct",
    ),
    ScatterSpec(
        "scale-cash",
        "売上高 × FCF",
        "企業規模と、投資後に残るキャッシュフローを比較します。",
        "revenue",
        "free_cash_flow",
        x_scale="log",
    ),
)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AnalyticsError(f"{label}を読み込めません: {path}") from exc
    if not isinstance(payload, dict):
        raise AnalyticsError(f"{label}のトップレベルがオブジェクトではありません。")
    return payload


def load_companies(path: Path) -> tuple[AnalyticsCompany, ...]:
    payload = _load_json_object(path, label="企業メタデータ")
    companies: list[AnalyticsCompany] = []
    seen_slugs: set[str] = set()
    seen_tickers: set[str] = set()

    for order, (ticker, meta) in enumerate(payload.items()):
        if not isinstance(ticker, str) or not isinstance(meta, dict):
            raise AnalyticsError("企業メタデータに不正な項目があります。")
        name = meta.get("name")
        edinet_code = meta.get("edinet_code")
        status = meta.get("status", "direct")
        if not isinstance(name, str) or not name.strip():
            raise AnalyticsError(f"{ticker} の企業名が不正です。")
        if not isinstance(edinet_code, str) or not re.fullmatch(r"E\d{5}", edinet_code):
            raise AnalyticsError(f"{ticker} のEDINETコードが不正です。")
        if status not in {"direct", "indirect"}:
            raise AnalyticsError(f"{ticker} のstatusが不正です。")

        salary = meta.get("avg_salary_man")
        if salary is not None and (isinstance(salary, bool) or not isinstance(salary, (int, float))):
            raise AnalyticsError(f"{ticker} の平均年間給与が数値ではありません。")
        salary_year = meta.get("avg_salary_fiscal_year")
        if salary_year is not None and (
            isinstance(salary_year, bool) or not isinstance(salary_year, int)
        ):
            raise AnalyticsError(f"{ticker} の平均年間給与年度が整数ではありません。")

        slug = build_financials.ticker_slug(ticker)
        if ticker in seen_tickers or slug in seen_slugs:
            raise AnalyticsError(f"企業メタデータのtickerまたはslugが重複しています: {ticker}")
        seen_tickers.add(ticker)
        seen_slugs.add(slug)
        companies.append(
            AnalyticsCompany(
                order=order,
                ticker=ticker,
                name=name.strip(),
                edinet_code=edinet_code,
                status=status,
                tier=str(meta.get("tier", "")),
                listing_status=str(meta.get("listing_status", "listed")),
                avg_salary_man=float(salary) if salary is not None else None,
                avg_salary_fiscal_year=salary_year,
                slug=slug,
            )
        )

    if not companies:
        raise AnalyticsError("企業メタデータが空です。")
    return tuple(companies)


def _relative_raw_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def discover_snapshots(
    input_dir: Path,
    companies: tuple[AnalyticsCompany, ...],
    *,
    allow_missing: bool,
) -> tuple[tuple[RawSnapshot, ...], tuple[str, ...]]:
    direct_companies = tuple(company for company in companies if company.status == "direct")
    companies_by_slug = {company.slug: company for company in direct_companies}
    discovered: list[RawSnapshot] = []
    seen_keys: dict[tuple[str, datetime], str] = {}

    for path in sorted(input_dir.glob("*__financials__*.json")):
        match = build_financials.INPUT_NAME_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        company = companies_by_slug.get(match.group("slug"))
        if company is None:
            continue

        try:
            fetched_at = _parse_utc_timestamp(build_financials.parse_fetched_at(path))
            body = path.read_bytes()
        except (OSError, build_financials.BuildError) as exc:
            raise AnalyticsError(f"財務rawを読み込めません: {path}") from exc
        sha256 = hashlib.sha256(body).hexdigest()
        key = (company.ticker, fetched_at)
        previous_hash = seen_keys.get(key)
        if previous_hash is not None:
            if previous_hash != sha256:
                raise AnalyticsError(
                    f"同じ企業・取得日時に異なるrawがあります: {company.ticker} {fetched_at.isoformat()}"
                )
            continue
        seen_keys[key] = sha256

        try:
            payload = build_financials.load_raw(path)
            built_company, _ = build_financials.build_company(
                payload,
                input_path=path,
                company=company.as_build_spec(),
            )
        except build_financials.BuildError as exc:
            raise AnalyticsError(f"財務rawの検証に失敗しました: {path}: {exc}") from exc
        discovered.append(
            RawSnapshot(
                company=company,
                path=path,
                raw_file=_relative_raw_path(path),
                fetched_at=fetched_at,
                sha256=sha256,
                periods=tuple(built_company["periods"]),
            )
        )

    available = {snapshot.company.ticker for snapshot in discovered}
    missing = tuple(
        company.ticker for company in direct_companies if company.ticker not in available
    )
    if missing and not allow_missing:
        raise AnalyticsError(
            "直接取得企業の財務rawがありません: " + ", ".join(missing)
        )
    if not discovered:
        raise AnalyticsError("分析対象の財務rawが見つかりません。")
    return (
        tuple(sorted(discovered, key=lambda item: (item.company.order, item.fetched_at))),
        missing,
    )


def _decimal_value(value: int | float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def build_dimension_rows(companies: tuple[AnalyticsCompany, ...]) -> list[dict[str, Any]]:
    return [
        {
            "company_order": company.order,
            "ticker": company.ticker,
            "name": company.name,
            "edinet_code": company.edinet_code,
            "currency": "JPY",
            "status": company.status,
            "tier": company.tier,
            "listing_status": company.listing_status,
            "avg_salary_man": company.avg_salary_man,
            "avg_salary_fiscal_year": company.avg_salary_fiscal_year,
        }
        for company in companies
    ]


def build_history_rows(
    snapshots: tuple[RawSnapshot, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    financial_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        for period in snapshot.periods:
            metrics = period["metrics"]
            source = period["source_document"]
            for metric_name in (*MONEY_METRICS, *PERCENT_METRICS):
                financial_rows.append(
                    {
                        "company_order": snapshot.company.order,
                        "ticker": snapshot.company.ticker,
                        "fiscal_year": period["fiscal_year"],
                        "metric_name": metric_name,
                        "value": _decimal_value(metrics[metric_name]),
                        "unit": "JPY" if metric_name in MONEY_METRICS else "PERCENTAGE_POINT",
                        "accounting_standard": period["accounting_standard"],
                        "consolidated": period["consolidated"],
                        "document_id": source["document_id"],
                        "raw_fetched_at": snapshot.fetched_at,
                        "raw_sha256": snapshot.sha256,
                        "raw_file": snapshot.raw_file,
                    }
                )
            filed_at = source["filed_at"]
            source_rows.append(
                {
                    "company_order": snapshot.company.order,
                    "ticker": snapshot.company.ticker,
                    "fiscal_year": period["fiscal_year"],
                    "document_id": source["document_id"],
                    "document_type": source["document_type"],
                    "filed_at": date.fromisoformat(filed_at) if filed_at else None,
                    "url": source["url"],
                    "raw_fetched_at": snapshot.fetched_at,
                    "raw_sha256": snapshot.sha256,
                    "raw_file": snapshot.raw_file,
                }
            )
    return financial_rows, source_rows


def _write_parquet(rows: list[dict[str, Any]], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression="zstd", version="2.6")


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


MART_SQL = """
CREATE TABLE company_year_metrics_data AS
WITH snapshot_keys AS (
    SELECT DISTINCT ticker, raw_fetched_at, raw_sha256
    FROM financial_history_data
),
ranked_snapshots AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY ticker
            ORDER BY raw_fetched_at DESC, raw_sha256 DESC
        ) AS snapshot_rank
    FROM snapshot_keys
),
latest_facts AS (
    SELECT history.*
    FROM financial_history_data AS history
    JOIN ranked_snapshots AS snapshots
      USING (ticker, raw_fetched_at, raw_sha256)
    WHERE snapshots.snapshot_rank = 1
),
pivoted AS (
    SELECT
        dimensions.company_order,
        dimensions.ticker,
        dimensions.name,
        dimensions.edinet_code,
        dimensions.currency,
        facts.fiscal_year,
        CAST(NULL AS DATE) AS fiscal_year_end,
        MAX(facts.accounting_standard) AS accounting_standard,
        BOOL_AND(facts.consolidated) AS consolidated,
        MAX(CASE WHEN metric_name = 'revenue' THEN CAST(value AS BIGINT) END) AS revenue,
        MAX(CASE WHEN metric_name = 'operating_income' THEN CAST(value AS BIGINT) END) AS operating_income,
        MAX(CASE WHEN metric_name = 'net_income' THEN CAST(value AS BIGINT) END) AS net_income,
        MAX(CASE WHEN metric_name = 'total_assets' THEN CAST(value AS BIGINT) END) AS total_assets,
        MAX(CASE WHEN metric_name = 'equity' THEN CAST(value AS BIGINT) END) AS equity,
        MAX(CASE WHEN metric_name = 'operating_cash_flow' THEN CAST(value AS BIGINT) END) AS operating_cash_flow,
        MAX(CASE WHEN metric_name = 'investing_cash_flow' THEN CAST(value AS BIGINT) END) AS investing_cash_flow,
        CAST(MAX(CASE WHEN metric_name = 'roe_pct' THEN value END) AS DOUBLE) AS roe_pct,
        facts.raw_fetched_at AS fetched_at,
        facts.raw_sha256 AS snapshot_sha256
    FROM latest_facts AS facts
    JOIN dim_companies_data AS dimensions USING (ticker)
    GROUP BY
        dimensions.company_order,
        dimensions.ticker,
        dimensions.name,
        dimensions.edinet_code,
        dimensions.currency,
        facts.fiscal_year,
        facts.raw_fetched_at,
        facts.raw_sha256
),
lagged AS (
    SELECT
        *,
        LAG(revenue, 1) OVER (
            PARTITION BY ticker ORDER BY fiscal_year
        ) AS previous_revenue,
        LAG(revenue, 3) OVER (
            PARTITION BY ticker ORDER BY fiscal_year
        ) AS starting_revenue_3p
    FROM pivoted
),
calculated AS (
    SELECT
        *,
        CASE
            WHEN revenue IS NULL OR previous_revenue IS NULL OR previous_revenue = 0 THEN NULL
            ELSE CAST(ROUND((CAST(revenue AS DOUBLE) / previous_revenue - 1) * 100, 4) AS DOUBLE)
        END AS revenue_yoy_pct,
        CASE
            WHEN operating_income IS NULL OR revenue IS NULL OR revenue = 0 THEN NULL
            ELSE CAST(ROUND(CAST(operating_income AS DOUBLE) / revenue * 100, 4) AS DOUBLE)
        END AS operating_margin_pct,
        CASE
            WHEN operating_cash_flow IS NULL OR investing_cash_flow IS NULL THEN NULL
            ELSE operating_cash_flow + investing_cash_flow
        END AS free_cash_flow,
        CASE
            WHEN revenue IS NULL OR starting_revenue_3p IS NULL
              OR starting_revenue_3p <= 0 OR revenue < 0 THEN NULL
            ELSE CAST(ROUND(
                (POWER(CAST(revenue AS DOUBLE) / starting_revenue_3p, 1.0 / 3) - 1) * 100,
                4
            ) AS DOUBLE)
        END AS revenue_cagr_3y_pct
    FROM lagged
),
latest_sources AS (
    SELECT sources.*
    FROM source_documents_history_data AS sources
    JOIN ranked_snapshots AS snapshots
      USING (ticker, raw_fetched_at, raw_sha256)
    WHERE snapshots.snapshot_rank = 1
)
SELECT
    calculated.company_order,
    calculated.ticker,
    calculated.name,
    calculated.edinet_code,
    calculated.currency,
    calculated.fiscal_year,
    calculated.fiscal_year_end,
    calculated.accounting_standard,
    calculated.consolidated,
    calculated.revenue,
    calculated.operating_income,
    calculated.net_income,
    calculated.total_assets,
    calculated.equity,
    calculated.operating_cash_flow,
    calculated.investing_cash_flow,
    calculated.roe_pct,
    calculated.revenue_yoy_pct,
    calculated.operating_margin_pct,
    calculated.free_cash_flow,
    calculated.revenue_cagr_3y_pct,
    sources.document_id AS source_document_id,
    sources.document_type AS source_document_type,
    sources.filed_at AS source_filed_at,
    sources.url AS source_url,
    calculated.fetched_at,
    calculated.snapshot_sha256
FROM calculated
LEFT JOIN latest_sources AS sources
  ON calculated.ticker = sources.ticker
 AND calculated.fiscal_year = sources.fiscal_year
 AND calculated.fetched_at = sources.raw_fetched_at
 AND calculated.snapshot_sha256 = sources.raw_sha256
ORDER BY calculated.company_order, calculated.fiscal_year
"""


def build_warehouse(
    stage_warehouse: Path,
    companies: tuple[AnalyticsCompany, ...],
    snapshots: tuple[RawSnapshot, ...],
    missing_tickers: tuple[str, ...],
) -> WarehouseResult:
    stage_warehouse.mkdir(parents=True, exist_ok=True)
    dim_path = stage_warehouse / "dim_companies.parquet"
    history_path = stage_warehouse / "financial_history.parquet"
    sources_path = stage_warehouse / "source_documents_history.parquet"
    mart_path = stage_warehouse / "company_year_metrics.parquet"
    database_path = stage_warehouse / "analytics.duckdb"

    financial_rows, source_rows = build_history_rows(snapshots)
    _write_parquet(build_dimension_rows(companies), DIM_COMPANIES_SCHEMA, dim_path)
    _write_parquet(financial_rows, FINANCIAL_HISTORY_SCHEMA, history_path)
    _write_parquet(source_rows, SOURCE_HISTORY_SCHEMA, sources_path)

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            f"CREATE TABLE dim_companies_data AS SELECT * FROM read_parquet('{_sql_path(dim_path)}')"
        )
        connection.execute(
            f"CREATE TABLE financial_history_data AS SELECT * FROM read_parquet('{_sql_path(history_path)}')"
        )
        connection.execute(
            "CREATE TABLE source_documents_history_data AS "
            f"SELECT * FROM read_parquet('{_sql_path(sources_path)}')"
        )
        connection.execute(MART_SQL)
        connection.execute(
            "COPY (SELECT * FROM company_year_metrics_data "
            "ORDER BY company_order, fiscal_year) "
            f"TO '{_sql_path(mart_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        connection.execute("CREATE VIEW companies AS SELECT * FROM dim_companies_data")
        connection.execute(
            "CREATE VIEW financial_history AS SELECT * FROM financial_history_data"
        )
        connection.execute(
            "CREATE VIEW source_document_history AS "
            "SELECT * FROM source_documents_history_data"
        )
        connection.execute(
            "CREATE VIEW company_year_metrics AS "
            "SELECT * FROM company_year_metrics_data"
        )
        mart = connection.execute(
            "SELECT * FROM company_year_metrics ORDER BY company_order, fiscal_year"
        ).fetchdf()
        generated_at = connection.execute(
            "SELECT MAX(fetched_at) FROM company_year_metrics"
        ).fetchone()[0]
    finally:
        connection.close()

    if mart.empty or generated_at is None:
        raise AnalyticsError("最新企業年度マートが空です。")
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    else:
        generated_at = generated_at.astimezone(timezone.utc)

    manifest = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": isoformat_utc(generated_at),
        "snapshot_count": len(snapshots),
        "financial_fact_count": len(financial_rows),
        "source_document_count": len(source_rows),
        "latest_company_year_count": len(mart),
        "missing_tickers": list(missing_tickers),
        "raw_inputs": [
            {
                "ticker": snapshot.company.ticker,
                "raw_file": snapshot.raw_file,
                "fetched_at": isoformat_utc(snapshot.fetched_at),
                "sha256": snapshot.sha256,
            }
            for snapshot in snapshots
        ],
    }
    write_json(stage_warehouse / "build_manifest.json", manifest)

    expected_files = {
        "dim_companies.parquet",
        "financial_history.parquet",
        "source_documents_history.parquet",
        "company_year_metrics.parquet",
        "analytics.duckdb",
        "build_manifest.json",
    }
    if {path.name for path in stage_warehouse.iterdir()} != expected_files:
        raise AnalyticsError("Warehouse成果物の構成が不正です。")

    return WarehouseResult(
        mart=mart,
        generated_at=generated_at,
        snapshot_count=len(snapshots),
        missing_tickers=missing_tickers,
    )


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _nullable_int(value: Any) -> int | None:
    return None if pd.isna(value) else int(value)


def _nullable_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    result = round(float(value), 4)
    return 0.0 if result == 0 else result


def _nullable_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def build_frontend_document(mart: pd.DataFrame, generated_at: datetime) -> dict[str, Any]:
    companies: list[dict[str, Any]] = []
    for _, company_rows in mart.groupby("ticker", sort=False):
        first = company_rows.iloc[0]
        periods: list[dict[str, Any]] = []
        for row in company_rows.sort_values("fiscal_year").itertuples(index=False):
            fetched_at = row.fetched_at.to_pydatetime() if isinstance(row.fetched_at, pd.Timestamp) else row.fetched_at
            periods.append(
                {
                    "fiscal_year": int(row.fiscal_year),
                    "fiscal_year_end": _nullable_date(row.fiscal_year_end),
                    "accounting_standard": row.accounting_standard,
                    "consolidated": bool(row.consolidated),
                    "metrics": {
                        "revenue": _nullable_int(row.revenue),
                        "operating_income": _nullable_int(row.operating_income),
                        "net_income": _nullable_int(row.net_income),
                        "total_assets": _nullable_int(row.total_assets),
                        "equity": _nullable_int(row.equity),
                        "operating_cash_flow": _nullable_int(row.operating_cash_flow),
                        "investing_cash_flow": _nullable_int(row.investing_cash_flow),
                        "roe_pct": _nullable_float(row.roe_pct),
                    },
                    "calculated_metrics": {
                        "revenue_yoy_pct": _nullable_float(row.revenue_yoy_pct),
                        "operating_margin_pct": _nullable_float(row.operating_margin_pct),
                        "free_cash_flow": _nullable_int(row.free_cash_flow),
                        "revenue_cagr_3y_pct": _nullable_float(row.revenue_cagr_3y_pct),
                    },
                    "source_document": {
                        "document_id": None if pd.isna(row.source_document_id) else row.source_document_id,
                        "document_type": row.source_document_type,
                        "filed_at": _nullable_date(row.source_filed_at),
                        "url": None if pd.isna(row.source_url) else row.source_url,
                    },
                    "fetched_at": isoformat_utc(fetched_at),
                }
            )
        companies.append(
            {
                "ticker": first["ticker"],
                "name": first["name"],
                "edinet_code": first["edinet_code"],
                "currency": first["currency"],
                "periods": periods,
            }
        )
    return {
        "schema_version": "1.0",
        "generated_at": isoformat_utc(generated_at),
        "companies": companies,
    }


def load_comparisons(path: Path, mart: pd.DataFrame) -> tuple[ComparisonPair, ...]:
    payload = _load_json_object(path, label="比較グラフ設定")
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("pairs"), list):
        raise AnalyticsError("比較グラフ設定はschema_version 1.0とpairs配列が必要です。")
    available = set(mart["ticker"].tolist())
    years_by_ticker = {
        ticker: set(group["fiscal_year"].astype(int).tolist())
        for ticker, group in mart.groupby("ticker", sort=False)
    }
    comparisons: list[ComparisonPair] = []
    seen_ids: set[str] = set()
    for raw_pair in payload["pairs"]:
        if not isinstance(raw_pair, dict):
            raise AnalyticsError("比較グラフ設定のpairがオブジェクトではありません。")
        pair_id = raw_pair.get("id")
        left = raw_pair.get("left")
        right = raw_pair.get("right")
        if not isinstance(pair_id, str) or not COMPARISON_ID_PATTERN.fullmatch(pair_id):
            raise AnalyticsError("比較グラフ設定のidが不正です。")
        if pair_id in seen_ids:
            raise AnalyticsError(f"比較グラフ設定のidが重複しています: {pair_id}")
        if not isinstance(left, str) or not isinstance(right, str):
            raise AnalyticsError(f"比較 {pair_id} のleft/rightが不正です。")
        if left == right:
            raise AnalyticsError(f"比較 {pair_id} に同じ企業が指定されています。")
        if left not in available or right not in available:
            raise AnalyticsError(f"比較 {pair_id} に分析データのない企業があります。")
        if not years_by_ticker[left].intersection(years_by_ticker[right]):
            raise AnalyticsError(f"比較 {pair_id} の2社に共通年度がありません。")
        seen_ids.add(pair_id)
        comparisons.append(ComparisonPair(id=pair_id, left=left, right=right))
    return tuple(comparisons)


def _money_formatter(value: float, _: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}T"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}B"
    return f"{value:,.0f}"


def _percent_formatter(value: float, _: float) -> str:
    return f"{value:.1f}%"


def _set_chart_theme() -> None:
    matplotlib.rcParams["svg.hashsalt"] = "ir-dashboard-v1"
    sns.set_theme(
        context="paper",
        style="whitegrid",
        palette="colorblind",
        font="DejaVu Sans",
        rc={
            "axes.edgecolor": "#d4d4d8",
            "axes.labelcolor": "#52525b",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "grid.color": "#e4e4e7",
            "grid.linewidth": 0.8,
            "xtick.color": "#71717a",
            "ytick.color": "#71717a",
        },
    )


def _save_svg(figure: Any, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(
        output,
        format="svg",
        bbox_inches="tight",
        metadata={"Date": None, "Creator": "ir.py analytics pipeline"},
    )
    plt.close(figure)
    normalized = "\n".join(
        line.rstrip() for line in output.read_text(encoding="utf-8").splitlines()
    )
    output.write_text(f"{normalized}\n", encoding="utf-8")


def render_line_chart(
    frame: pd.DataFrame,
    *,
    series: tuple[tuple[str, str, str], ...],
    output: Path,
    value_kind: str,
) -> None:
    _set_chart_theme()
    figure, axis = plt.subplots(figsize=(7.2, 2.8))
    years = frame["fiscal_year"].astype(int).tolist()
    plotted = False
    for column, label, color in series:
        values = pd.to_numeric(frame[column], errors="coerce")
        if value_kind == "money":
            values = values / 1_000_000
        if values.notna().any():
            plotted = True
        axis.plot(
            years,
            values,
            label=label,
            color=color,
            linewidth=2.2,
            marker="o",
            markersize=4.5,
            markerfacecolor="white",
            markeredgewidth=1.8,
        )
    axis.axhline(0, color="#a1a1aa", linewidth=0.9, zorder=0)
    axis.set_xticks(years, [f"FY{str(year)[-2:]}" for year in years])
    axis.set_ylabel("JPY million" if value_kind == "money" else "Percent")
    axis.yaxis.set_major_formatter(
        FuncFormatter(_money_formatter if value_kind == "money" else _percent_formatter)
    )
    axis.spines[["top", "right"]].set_visible(False)
    axis.margins(x=0.04, y=0.14)
    if plotted:
        axis.legend(frameon=False, loc="best", ncols=min(2, len(series)))
    else:
        axis.text(0.5, 0.5, "No data", ha="center", va="center", transform=axis.transAxes)
    _save_svg(figure, output)


def render_charts(
    mart: pd.DataFrame,
    comparisons: tuple[ComparisonPair, ...],
    companies: tuple[AnalyticsCompany, ...],
    stage_charts: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    company_by_ticker = {company.ticker: company for company in companies}
    company_manifest: dict[str, dict[str, str]] = {}
    comparison_manifest: list[dict[str, Any]] = []
    company_specs = (
        (
            "profitability",
            (("revenue", "Revenue", "#18181b"), ("operating_income", "Op. income", "#0f766e")),
            "money",
        ),
        (
            "returns",
            (("operating_margin_pct", "Op. margin", "#7c3aed"), ("roe_pct", "ROE", "#0369a1")),
            "percent",
        ),
        (
            "cashflow",
            (("operating_cash_flow", "Operating CF", "#0369a1"), ("free_cash_flow", "FCF", "#c2410c")),
            "money",
        ),
    )
    for ticker, frame in mart.groupby("ticker", sort=False):
        company = company_by_ticker[ticker]
        assets: dict[str, str] = {}
        for metric, series, value_kind in company_specs:
            relative = Path("companies") / company.slug / f"{metric}.svg"
            render_line_chart(
                frame.sort_values("fiscal_year"),
                series=series,
                output=stage_charts / relative,
                value_kind=value_kind,
            )
            assets[metric] = "/charts/" + relative.as_posix()
        company_manifest[ticker] = assets

    for pair in comparisons:
        left = mart[mart["ticker"] == pair.left].set_index("fiscal_year")
        right = mart[mart["ticker"] == pair.right].set_index("fiscal_year")
        years = sorted(set(left.index.astype(int)).intersection(right.index.astype(int)))
        comparison_frame = pd.DataFrame({"fiscal_year": years})
        comparison_specs = (
            "revenue",
            "operating_margin_pct",
            "free_cash_flow",
        )
        charts: dict[str, str] = {}
        for metric in comparison_specs:
            comparison_frame[f"left_{metric}"] = [left.loc[year, metric] for year in years]
            comparison_frame[f"right_{metric}"] = [right.loc[year, metric] for year in years]
            relative = Path("comparisons") / pair.id / f"{metric}.svg"
            render_line_chart(
                comparison_frame,
                series=(
                    (f"left_{metric}", pair.left, "#18181b"),
                    (f"right_{metric}", pair.right, "#0f766e"),
                ),
                output=stage_charts / relative,
                value_kind="percent" if metric == "operating_margin_pct" else "money",
            )
            charts[metric] = "/charts/" + relative.as_posix()
        comparison_manifest.append(
            {"id": pair.id, "left": pair.left, "right": pair.right, "charts": charts}
        )

    return {
        "schema_version": "1.0",
        "generated_at": isoformat_utc(generated_at),
        "companies": company_manifest,
        "comparisons": comparison_manifest,
    }


def common_stats_years(mart: pd.DataFrame) -> tuple[int, ...]:
    company_count = int(mart["ticker"].nunique())
    if company_count == 0:
        raise AnalyticsError("Stats対象企業がありません。")
    counts = mart.groupby("fiscal_year")["ticker"].nunique()
    years = tuple(
        sorted(int(year) for year, count in counts.items() if int(count) == company_count)
    )
    if not years:
        raise AnalyticsError("全企業に共通するStats対象年度がありません。")
    return years


def _stats_values(frame: pd.DataFrame, metric: StatsMetric) -> pd.Series:
    values = pd.to_numeric(frame[metric.column], errors="coerce").astype(float)
    if metric.value_kind == "money":
        values = values / 1_000_000
    return values


def _descriptive_statistics(values: pd.Series, company_count: int) -> dict[str, Any]:
    available = values.dropna()
    return {
        "count": int(available.count()),
        "missing": company_count - int(available.count()),
        "mean": _nullable_float(available.mean()),
        "median": _nullable_float(available.median()),
        "stddev": _nullable_float(available.std(ddof=1)),
        "min": _nullable_float(available.min()),
        "q1": _nullable_float(available.quantile(0.25, interpolation="linear")),
        "q3": _nullable_float(available.quantile(0.75, interpolation="linear")),
        "max": _nullable_float(available.max()),
    }


def _ranking_rows(frame: pd.DataFrame, metric: StatsMetric) -> list[dict[str, Any]]:
    working = frame[["company_order", "ticker", "name"]].copy()
    working["value"] = _stats_values(frame, metric)
    working["rank"] = working["value"].rank(
        method="min",
        ascending=False,
        na_option="keep",
    )
    working["missing"] = working["value"].isna()
    working = working.sort_values(
        ["missing", "rank", "company_order"],
        kind="stable",
        na_position="last",
    )
    return [
        {
            "rank": None if pd.isna(row.rank) else int(row.rank),
            "ticker": str(row.ticker),
            "name": str(row.name),
            "value": _nullable_float(row.value),
        }
        for row in working.itertuples(index=False)
    ]


def render_ranking_chart(
    rows: list[dict[str, Any]],
    *,
    metric: StatsMetric,
    output: Path,
) -> None:
    _set_chart_theme()
    plotted = pd.DataFrame([row for row in rows if row["value"] is not None])
    figure, axis = plt.subplots(figsize=(7.2, 5.6))
    if plotted.empty:
        axis.text(0.5, 0.5, "No data", ha="center", va="center", transform=axis.transAxes)
        axis.set_yticks([])
    else:
        sns.barplot(
            data=plotted,
            x="value",
            y="ticker",
            order=plotted["ticker"].tolist(),
            color="#0f766e",
            saturation=0.88,
            ax=axis,
        )
    axis.axvline(0, color="#71717a", linewidth=0.9, zorder=0)
    axis.set_xlabel(
        f"{metric.english_label} ({'JPY million' if metric.value_kind == 'money' else '%'})"
    )
    axis.set_ylabel("")
    axis.xaxis.set_major_formatter(
        FuncFormatter(_money_formatter if metric.value_kind == "money" else _percent_formatter)
    )
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.grid(axis="y", visible=False)
    _save_svg(figure, output)


def _scatter_exclusion_reason(
    x_value: float | None,
    y_value: float | None,
    *,
    x_scale: str,
) -> str | None:
    if x_value is None and y_value is None:
        return "missing_x_and_y"
    if x_value is None:
        return "missing_x"
    if y_value is None:
        return "missing_y"
    if x_scale == "log" and x_value <= 0:
        return "non_positive_x_for_log"
    return None


def _scatter_rows(
    frame: pd.DataFrame,
    spec: ScatterSpec,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    x_metric = STATS_METRIC_BY_ID[spec.x_metric]
    y_metric = STATS_METRIC_BY_ID[spec.y_metric]
    x_values = _stats_values(frame, x_metric)
    y_values = _stats_values(frame, y_metric)
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for index, row in frame.reset_index(drop=True).iterrows():
        x_value = _nullable_float(x_values.iloc[index])
        y_value = _nullable_float(y_values.iloc[index])
        reason = _scatter_exclusion_reason(x_value, y_value, x_scale=spec.x_scale)
        if reason is not None:
            exclusions.append({"ticker": str(row["ticker"]), "reason": reason})
            continue
        rows.append(
            {
                "ticker": str(row["ticker"]),
                "name": str(row["name"]),
                "x": x_value,
                "y": y_value,
            }
        )
    return rows, exclusions


def _axis_label(metric: StatsMetric) -> str:
    unit = "JPY million" if metric.value_kind == "money" else "%"
    return f"{metric.english_label} ({unit})"


def render_scatter_chart(
    rows: list[dict[str, Any]],
    *,
    spec: ScatterSpec,
    output: Path,
) -> None:
    _set_chart_theme()
    x_metric = STATS_METRIC_BY_ID[spec.x_metric]
    y_metric = STATS_METRIC_BY_ID[spec.y_metric]
    plotted = pd.DataFrame(rows)
    figure, axis = plt.subplots(figsize=(7.2, 4.8))
    if plotted.empty:
        axis.text(0.5, 0.5, "No data", ha="center", va="center", transform=axis.transAxes)
    else:
        sns.scatterplot(
            data=plotted,
            x="x",
            y="y",
            color="#0369a1",
            edgecolor="white",
            linewidth=0.8,
            s=54,
            ax=axis,
        )
        offsets = ((4, 5), (4, -10), (-4, 5), (-4, -10))
        for index, row in enumerate(plotted.itertuples(index=False)):
            offset = offsets[index % len(offsets)]
            axis.annotate(
                row.ticker,
                (row.x, row.y),
                xytext=offset,
                textcoords="offset points",
                fontsize=7,
                color="#3f3f46",
                ha="left" if offset[0] > 0 else "right",
            )
    if spec.x_scale == "log":
        axis.set_xscale("log")
    else:
        axis.axvline(0, color="#a1a1aa", linewidth=0.9, zorder=0)
    axis.axhline(0, color="#a1a1aa", linewidth=0.9, zorder=0)
    axis.set_xlabel(_axis_label(x_metric))
    axis.set_ylabel(_axis_label(y_metric))
    axis.xaxis.set_major_formatter(
        FuncFormatter(
            _money_formatter if x_metric.value_kind == "money" else _percent_formatter
        )
    )
    axis.yaxis.set_major_formatter(
        FuncFormatter(
            _money_formatter if y_metric.value_kind == "money" else _percent_formatter
        )
    )
    axis.spines[["top", "right"]].set_visible(False)
    axis.margins(x=0.12, y=0.15)
    _save_svg(figure, output)


def render_stats(
    mart: pd.DataFrame,
    stage_charts: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    years = common_stats_years(mart)
    metric_metadata = {
        metric.id: {
            "label": metric.label,
            "english_label": metric.english_label,
            "unit": metric.unit,
            "value_kind": metric.value_kind,
        }
        for metric in STATS_METRICS
    }
    scatter_metadata = {
        spec.id: {
            "label": spec.label,
            "description": spec.description,
            "x_metric": spec.x_metric,
            "y_metric": spec.y_metric,
            "x_scale": spec.x_scale,
        }
        for spec in SCATTER_SPECS
    }
    results: dict[str, Any] = {}
    for year in years:
        frame = mart[mart["fiscal_year"] == year].sort_values("company_order").copy()
        company_count = int(frame["ticker"].nunique())
        descriptive: dict[str, dict[str, Any]] = {}
        rankings: dict[str, dict[str, Any]] = {}
        scatters: dict[str, dict[str, Any]] = {}
        for metric in STATS_METRICS:
            values = _stats_values(frame, metric)
            descriptive[metric.id] = _descriptive_statistics(values, company_count)
            rows = _ranking_rows(frame, metric)
            relative = Path("stats") / f"fy{year}" / "rankings" / f"{metric.id}.svg"
            render_ranking_chart(rows, metric=metric, output=stage_charts / relative)
            rankings[metric.id] = {
                "chart": "/charts/" + relative.as_posix(),
                "rows": rows,
            }
        for spec in SCATTER_SPECS:
            rows, exclusions = _scatter_rows(frame, spec)
            relative = Path("stats") / f"fy{year}" / "scatters" / f"{spec.id}.svg"
            render_scatter_chart(rows, spec=spec, output=stage_charts / relative)
            scatters[spec.id] = {
                "chart": "/charts/" + relative.as_posix(),
                "included_count": len(rows),
                "excluded_tickers": [item["ticker"] for item in exclusions],
                "exclusions": exclusions,
                "rows": rows,
            }
        results[str(year)] = {
            "company_count": company_count,
            "descriptive": descriptive,
            "rankings": rankings,
            "scatters": scatters,
        }
    return {
        "schema_version": "1.0",
        "generated_at": isoformat_utc(generated_at),
        "default_year": max(years),
        "default_ranking": "revenue",
        "default_scatter": "growth-profitability",
        "years": list(years),
        "metrics": metric_metadata,
        "scatter_definitions": scatter_metadata,
        "results": results,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise AnalyticsError(f"JSONへ変換できない値があります: {path}") from exc
    path.write_text(serialized, encoding="utf-8")


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def publish_artifacts(targets: tuple[tuple[Path, Path], ...]) -> None:
    token = uuid.uuid4().hex
    completed: list[tuple[Path, Path | None]] = []
    try:
        for staged, destination in targets:
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup: Path | None = None
            if destination.exists():
                backup = destination.parent / f".{destination.name}.analytics-backup-{token}"
                os.replace(destination, backup)
            try:
                os.replace(staged, destination)
            except OSError:
                if backup is not None and backup.exists():
                    os.replace(backup, destination)
                raise
            completed.append((destination, backup))
    except OSError as exc:
        for destination, backup in reversed(completed):
            _remove_path(destination)
            if backup is not None and backup.exists():
                os.replace(backup, destination)
        raise AnalyticsError("生成物の公開に失敗したため元の状態へ戻しました。") from exc
    for _, backup in completed:
        if backup is not None:
            _remove_path(backup)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EDINET rawからParquet/DuckDB分析基盤とWeb成果物を生成します。"
    )
    parser.add_argument("--input-dir", type=Path, default=REPOSITORY_ROOT / "data/raw")
    parser.add_argument(
        "--companies", type=Path, default=REPOSITORY_ROOT / "data/COMPANIES.json"
    )
    parser.add_argument(
        "--warehouse-dir", type=Path, default=REPOSITORY_ROOT / "data/warehouse"
    )
    parser.add_argument(
        "--frontend-json",
        type=Path,
        default=REPOSITORY_ROOT / "frontend/data/financials.json",
    )
    parser.add_argument(
        "--stats-json",
        type=Path,
        default=REPOSITORY_ROOT / "frontend/data/stats.json",
    )
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=REPOSITORY_ROOT / "frontend/public/charts",
    )
    parser.add_argument(
        "--comparisons",
        type=Path,
        default=REPOSITORY_ROOT / "config/chart-comparisons.json",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="rawがないdirect企業を警告扱いにして部分生成します。",
    )
    return parser


def run_pipeline(args: argparse.Namespace) -> WarehouseResult:
    companies = load_companies(args.companies)
    snapshots, missing = discover_snapshots(
        args.input_dir,
        companies,
        allow_missing=args.allow_missing,
    )
    with tempfile.TemporaryDirectory(
        dir=REPOSITORY_ROOT,
        prefix=".analytics-build-",
    ) as temporary_directory:
        stage_root = Path(temporary_directory)
        stage_warehouse = stage_root / "warehouse"
        stage_frontend_json = stage_root / "financials.json"
        stage_stats_json = stage_root / "stats.json"
        stage_charts = stage_root / "charts"
        stage_chart_manifest = stage_root / "chart-manifest.json"
        result = build_warehouse(
            stage_warehouse,
            companies,
            snapshots,
            missing,
        )
        comparisons = load_comparisons(args.comparisons, result.mart)
        document = build_frontend_document(result.mart, result.generated_at)
        chart_manifest = render_charts(
            result.mart,
            comparisons,
            companies,
            stage_charts,
            result.generated_at,
        )
        stats_document = render_stats(
            result.mart,
            stage_charts,
            result.generated_at,
        )
        write_json(stage_frontend_json, document)
        write_json(stage_stats_json, stats_document)
        write_json(stage_chart_manifest, chart_manifest)
        publish_artifacts(
            (
                (stage_warehouse, args.warehouse_dir),
                (stage_frontend_json, args.frontend_json),
                (stage_stats_json, args.stats_json),
                (stage_charts, args.charts_dir),
                (stage_chart_manifest, args.frontend_json.parent / "chart-manifest.json"),
            )
        )
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_pipeline(args)
    except (AnalyticsError, build_financials.BuildError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    company_count = int(result.mart["ticker"].nunique())
    print(f"生成: {args.warehouse_dir}")
    print(f"公開: {args.frontend_json}")
    print(f"統計: {args.stats_json}")
    print(f"グラフ: {args.charts_dir}")
    print(
        f"完了: {company_count}社 / {len(result.mart)}企業年度 / "
        f"{result.snapshot_count}スナップショット"
    )
    if result.missing_tickers:
        print("未取得: " + ", ".join(result.missing_tickers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
