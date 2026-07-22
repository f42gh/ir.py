# IR Dashboard

EDINET由来の財務情報を取得・分析し、Next.jsで表示するための学習用リポジトリです。

```text
EDINET DB API
  → data/raw/（取得レスポンスを不変保存）
  → src/build_financials.py（検証・標準化・指標計算）
  → frontend/data/financials.json（画面用データマート）
  → Next.js（企業一覧・5年度グラフ・2社比較・出典表示）
```

raw、変換処理、表示用データを分離し、APIへ再アクセスせず分析ロジックと画面を再生成できる構成です。

開発順序とMVPの範囲は [`docs/edinet-mvp-roadmap.md`](docs/edinet-mvp-roadmap.md) を参照してください。
Phase 2の取得手順は [`docs/phase2-fetch-preparation.md`](docs/phase2-fetch-preparation.md) にまとめています。
取得後の確認記録は [`docs/phase2-validation.md`](docs/phase2-validation.md) に残します。
Phase 3の変換方針は [`docs/phase3-json-preparation.md`](docs/phase3-json-preparation.md) にまとめています。

## ディレクトリ構成

- `frontend/`: Next.jsによる表示画面
- `frontend/data/`: Phase 3で生成する画面用JSONの保存先
- `data/COMPANIES.json`: ローカルで使用する企業メタデータ（Git管理外）
- `data/raw/`: EDINET DBの未加工レスポンス（Git管理外）
- `data/companies.example.json`: 企業メタデータのサンプル
- `docs/`: 設計資料とロードマップ
- `pyproject.toml`: Phase 2以降で使うPython環境の定義
- `src/fetch_direct_companies.py`: 直接取得企業の財務データ一括取得CLI
- `src/build_financials.py`: rawレスポンスの検証・標準化・指標計算CLI
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

`http://localhost:3000` で企業一覧を確認できます。直接取得できる19社は詳細画面で5年度の主要指標・グラフ・出典を表示でき、任意の2社を比較できます。子会社・未上場など直接取得できない対象は、参照先を明示してグレー表示します。

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

## Phase 3分析用JSON生成

保存済みrawを企業メタデータの並び順で統合し、画面用JSONへ変換します。この処理はEDINET DB APIを呼びません。

```bash
uv run python src/build_financials.py \
  --input-dir data/raw \
  --companies data/COMPANIES.json \
  --output frontend/data/financials.json
```

同じrawからは同じJSONが生成されます。入力ファイルは変更せず、変換に失敗した場合も既存の画面用JSONを壊しません。

企業ごとに最新のrawを選び、`data/COMPANIES.json` の並び順で統合します。ファイル名と企業メタデータのEDINETコードが一致しない場合は失敗し、既存の出力を保持します。

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
