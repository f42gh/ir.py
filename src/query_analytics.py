"""Run a read-only SQL query against the generated analytics warehouse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成済みDuckDB分析基盤へ読み取り専用SQLを実行します。"
    )
    parser.add_argument("sql", help="実行するSELECTまたはDESCRIBE SQL")
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data/warehouse/analytics.duckdb",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database.is_file():
        print(f"エラー: DuckDBが見つかりません: {args.database}", file=sys.stderr)
        return 1
    try:
        connection = duckdb.connect(str(args.database), read_only=True)
        try:
            result = connection.execute(args.sql)
            columns = [item[0] for item in result.description or ()]
            rows = result.fetchall()
        finally:
            connection.close()
    except duckdb.Error as exc:
        print(f"エラー: SQLを実行できません: {exc}", file=sys.stderr)
        return 1

    if columns:
        print("\t".join(columns))
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
