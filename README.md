# IR Dashboard

EDINET由来の財務情報を取得・分析し、Next.jsで表示するための学習用リポジトリです。

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
- `src/fetch_edinet.py`: ZOZOの検索・財務データ取得CLI
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

`http://localhost:3000` でTierごとの企業一覧を確認できます。

`.env` の `EDINET_DB_API_KEY` に自分のAPIキーを設定してください。`.env` はGitの追跡対象外です。

## Phase 2データ取得

`.env` を読み込ませて、ZOZOの検索結果と直近5年度の年次財務レスポンスを取得します。

```bash
uv run --env-file .env python src/fetch_edinet.py
```

成功すると、次の未加工JSONがUTCの取得日時付きで `data/raw/` に保存されます。既存ファイルは上書きしません。

```text
data/raw/zozo__search__YYYYMMDDTHHMMSSZ.json
data/raw/zozo__financials__YYYYMMDDTHHMMSSZ.json
```

Phase 2では分析指標やフロントエンド用JSONは生成しません。

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
  "2432.T": {
    "name": "DeNA",
    "tier": "1",
    "avg_salary_man": 850,
    "note": "..."
  }
}
```

実データやAPIキーはコミットせず、公開可能な例だけを `data/companies.example.json` に保存します。
