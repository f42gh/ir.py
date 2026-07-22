# IR Dashboard

EDINET由来の財務情報を取得・分析し、Next.jsで表示するための学習用リポジトリです。

```text
EDINET DB API
  → data/raw/（取得レスポンスを不変保存）
  → src/build_analytics.py（検証・標準化）
  → data/warehouse/（履歴Parquet・DuckDB・最新年度マート）
  ├→ frontend/data/financials.json（画面用JSON）
  ├→ frontend/data/stats.json（ランキング・記述統計）
  └→ frontend/public/charts/（matplotlib / seaborn SVG）
      → Next.js（企業一覧・5年度グラフ・2社比較・Stats・出典表示）
```

raw、変換処理、表示用データを分離し、APIへ再アクセスせず分析ロジックと画面を再生成できる構成です。

開発順序とMVPの範囲は [`docs/edinet-mvp-roadmap.md`](docs/edinet-mvp-roadmap.md) を参照してください。
Phase 2の取得手順は [`docs/phase2-fetch-preparation.md`](docs/phase2-fetch-preparation.md) にまとめています。
取得後の確認記録は [`docs/phase2-validation.md`](docs/phase2-validation.md) に残します。
Phase 3の変換方針は [`docs/phase3-json-preparation.md`](docs/phase3-json-preparation.md) にまとめています。

## ディレクトリ構成

- `frontend/`: Next.jsによる表示画面
- `frontend/data/`: 画面用JSONとチャートmanifest
- `frontend/public/charts/`: Web公開用の生成済みSVG
- `config/chart-comparisons.json`: 静的比較グラフの生成対象
- `data/COMPANIES.json`: ローカルで使用する企業メタデータ（Git管理外）
- `data/raw/`: EDINET DBの未加工レスポンス（Git管理外）
- `data/warehouse/`: 再生成可能なParquetとDuckDB（Git管理外）
- `data/companies.example.json`: 企業メタデータのサンプル
- `docs/`: 設計資料とロードマップ
- `pyproject.toml`: Phase 2以降で使うPython環境の定義
- `src/fetch_direct_companies.py`: 直接取得企業の財務データ一括取得CLI
- `src/build_analytics.py`: Warehouse・JSON・SVGの一括生成CLI
- `src/build_financials.py`: 旧JSON生成CLIと共通の財務変換処理
- `src/query_analytics.py`: DuckDBへの読み取り専用SQL実行CLI
- `tests/`: Python側のオフラインテスト

## 初期セットアップ

Python 3.12以上とNode.jsが必要です。

```bash
uv sync
cp .env.example .env
cp data/companies.example.json data/COMPANIES.json
cd frontend
pnpm install
```

## フロントエンド起動

```bash
cd frontend
pnpm dev
```

`http://localhost:3000` で企業一覧を確認できます。直接取得できる19社は詳細画面で5年度の主要指標・グラフ・出典を表示でき、任意の2社比較と共通年度の企業ランキング・散布図を確認できます。子会社・未上場など直接取得できない対象は、参照先を明示してグレー表示します。

`.env` の `EDINET_DB_API_KEY` に自分のAPIキーを設定してください。`.env` はGitの追跡対象外です。

## Phase 2データ取得

`.env` を読み込ませて、企業メタデータで `status: "direct"` とした対象の直近5年度の年次財務レスポンスを取得します。

```bash
uv run --env-file .env python src/fetch_direct_companies.py
```

成功すると、次の未加工JSONがUTCの取得日時付きで `data/raw/` に保存されます。既存ファイルは上書きしません。

```text
data/raw/{ticker_slug}__financials__YYYYMMDDTHHMMSSZ.json
```

Phase 2では分析指標やフロントエンド用JSONは生成しません。

## Phase 3分析基盤生成

保存済みrawから、履歴Parquet、DuckDB、最新年度マート、画面用JSON、Web向けSVGを一括生成します。この処理はEDINET DB APIを呼びません。

```bash
uv run python src/build_analytics.py
```

同じrawからは同じ分析データとSVGが生成されます。入力ファイルは変更せず、全成果物の生成と検証が成功してから公開先を置き換えます。途中で失敗した場合は既存のWarehouse、JSON、SVGを保持します。

企業slugに一致する全rawスナップショットを履歴として保存し、通常分析と画面では企業ごとの最新スナップショットを使用します。デフォルトでは、すべての`direct`企業にrawが必要です。一部企業だけで生成する場合は`--allow-missing`を明示します。

標準パスを変更する場合は次のオプションを利用できます。

```text
--input-dir
--companies
--warehouse-dir
--frontend-json
--stats-json
--charts-dir
--comparisons
```

旧形式の画面用JSONだけを生成する`src/build_financials.py`も互換用に残しています。

## DuckDBで分析する

Warehouseには次のビューがあります。

```text
companies
financial_history
source_document_history
company_year_metrics
```

SQLは読み取り専用CLIから実行できます。

```bash
uv run python src/query_analytics.py \
  "SELECT ticker, fiscal_year, revenue, operating_margin_pct FROM company_year_metrics ORDER BY ticker, fiscal_year"
```

`company_year_metrics.parquet`はPandasから直接読み込めるため、matplotlibやseabornを使った追加分析にも利用できます。

## Statsページ

`/stats`では、全対象企業が揃う共通年度について、売上高、売上高YoY、営業利益、営業利益率、ROE、FCFのランキングと記述統計を表示します。成長率×営業利益率、営業利益率×ROE、売上高×FCFの散布図も選択できます。

Stats JSONと36枚のSVGは`src/build_analytics.py`で事前生成されます。Webリクエスト時にPythonは実行せず、「生成」ボタンは年度・ランキング・散布図をGETパラメータで切り替えます。

## 静的比較グラフを追加する

企業詳細のSVGは全企業分を生成します。任意2社比較は通常はWeb側で動的描画し、`config/chart-comparisons.json`に登録した左右順と一致するときだけPython製SVGを使用します。

```json
{
  "schema_version": "1.0",
  "pairs": [
    {
      "id": "brainpad-vs-jdsc",
      "left": "3655.T",
      "right": "4418.T"
    }
  ]
}
```

設定に未知のticker、同じ企業、重複ID、共通年度のないペアがある場合、生成は失敗します。

再現対象のrawを固定したい場合は、`--input` を企業数分繰り返して明示指定できます。

## 確認

Pythonの取得処理は実APIを呼ばずに確認できます。

```bash
uv run python -m unittest discover -s tests -v
```

フロントエンドを確認する場合は次を実行します。

```bash
cd frontend
pnpm build
```

## 企業メタデータ形式

`data/COMPANIES.json`:

```json
{
  "1234.T": {
    "name": "サンプル上場会社",
    "tier": "1",
    "status": "direct",
    "edinet_code": "E00000",
    "avg_salary_man": 800,
    "note": "..."
  }
}
```

実データやAPIキーはコミットせず、公開可能な例だけを `data/companies.example.json` に保存します。
