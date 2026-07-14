# IR Dashboard

EDINET由来の財務情報を取得・分析し、Next.jsで表示するための学習用リポジトリです。

開発順序とMVPの範囲は [`docs/edinet-mvp-roadmap.md`](docs/edinet-mvp-roadmap.md) を参照してください。
Phase 2の取得手順は [`docs/phase2-fetch-preparation.md`](docs/phase2-fetch-preparation.md) にまとめています。

## ディレクトリ構成

- `frontend/`: Next.jsによる表示画面
- `data/COMPANIES.json`: ローカルで使用する企業メタデータ（Git管理外）
- `data/companies.example.json`: 企業メタデータのサンプル
- `docs/`: 設計資料とロードマップ
- `pyproject.toml`: Phase 2以降で使うPython環境の定義

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

## 確認

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
