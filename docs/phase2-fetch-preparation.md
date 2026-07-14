# Phase 2 取得準備

## ゴール

ZOZOの直近5会計年度の財務時系列をEDINET DB APIから取得し、加工前のレスポンスを `data/raw/` に保存して、主要値を取得元画面と照合できる状態にする。

Phase 2では分析値を計算しない。APIレスポンスの取得・保存・意味の確認に集中する。

## 確認済みのAPI契約

- ベースURL: `https://edinetdb.jp/v1`
- 認証: 財務時系列APIでは `X-API-Key` ヘッダーが必要
- 企業検索: `GET /search?q={query}&limit={件数}`。公開APIだが、CLIは財務取得前提で通信前にAPIキーを確認する
- 財務時系列: `GET /companies/{edinet_code}/financials?years=5&period=annual`
- 無料プラン: 1日100リクエスト
- 金額: APIでは円
- 比率: rawでは小数。例えば `roe_official` の `0.15` は15%を表す
- 欠損: 値がないフィールドはレスポンスから省略される場合がある

参照:

- [EDINET DB API仕様書](https://edinetdb.jp/docs/api)
- [EDINET DB開発者向けページ](https://edinetdb.jp/developers)

## 最初の対象企業

| 項目 | 値 |
|---|---|
| 企業名 | 株式会社ZOZO |
| ティッカー | `3092.T` |
| APIの証券コード | `30920` |
| EDINETコード | `E05725` |

2026年7月14日に公開検索API `GET /v1/search?q=3092` で確認した。部分一致検索では別企業も返るため、検索結果の `sec_code == "30920"` と企業名の両方を確認する。

## 環境変数

`.env.example` を `.env` へコピーし、次の値を設定する。

```text
EDINET_DB_API_KEY=取得したAPIキー
```

実装では環境変数 `EDINET_DB_API_KEY` から読み込む。キーをソースコード、ログ、例外メッセージ、rawレスポンスへ書き込まない。

`.env` はPythonが自動では読み込まないため、実行時に `uv` の `--env-file` を使用する。

```bash
uv run --env-file .env python src/fetch_edinet.py
```

## Python依存

HTTPクライアントとして `httpx` を使用する。`uv sync` でインストールされる。

Phase 2では、標準ライブラリの次の機能も使用する。

- `os`: APIキーの読み込み
- `json`: レスポンスの保存
- `datetime`: 取得日時とファイル名
- `pathlib`: 保存先パス

## 実装と実行の流れ

1. `src/fetch_edinet.py` がAPIキーを確認する
2. `/search?q=3092&limit=5` を呼び、`sec_code == "30920"` で候補を絞る
3. 全角英数字をNFKC正規化した企業名が `株式会社ZOZO`、EDINETコードが `E05725` であることを確認する
4. `/companies/E05725/financials?years=5&period=annual` を呼ぶ
5. 両レスポンスが正常なJSONで、財務レスポンスが重複のない5年度分であることを確認する
6. レスポンス本文の元バイト列を加工せず `data/raw/` に保存する
7. 保存済み財務JSONを読み直し、年度順、会計基準、欠損、ゼロ、出典情報を表示する
8. 主要値をEDINET DBのWeb画面と照合し、結果を `phase2-validation.md` に記録する

財務レスポンスで確認するPhase 1対応フィールドは次のとおり。

| Phase 1の意味 | EDINET DB rawフィールド | raw単位 |
|---|---|---|
| 売上高 | `revenue` | 円 |
| 営業利益 | `operating_income` | 円 |
| 純利益 | `net_income` | 円 |
| 総資産 | `total_assets` | 円 |
| 自己資本 | `shareholders_equity` | 円 |
| 営業キャッシュフロー | `cf_operating` | 円 |
| 投資キャッシュフロー | `cf_investing` | 円 |
| ROE | `roe_official` | 小数 |

出典追跡には各年度の `doc_id`、`submit_date`、`edinet_filing_url` を使用する。

## rawファイル規約

APIレスポンスは上書きせず、UTCの取得日時を含む名前で保存する。

```text
data/raw/
  zozo__search__20260714T120000Z.json
  zozo__financials__20260714T120005Z.json
```

保存対象はレスポンス本文だけとする。APIキーを含むリクエストヘッダーは保存しない。HTTPステータス、取得URL、取得日時は別途ログへ出せるが、キーは出さない。

## 通信時の確認事項

- タイムアウトを明示する
- 両APIが `2xx` かつ有効なJSONで、企業同定と5年度検査が成功するまでrawを保存しない
- `401` と `403` はAPIキーを確認する
- `429` は利用上限として扱い、連続再試行しない
- JSONとして解釈できないレスポンスを既存rawファイルへ上書きしない
- 失敗時にも認証ヘッダーを表示しない

## オフラインテスト

`httpx.MockTransport` を使うため、次のテストはAPI利用回数を消費しない。

```bash
uv run python -m unittest discover -s tests -v
```

## Phase 2完了条件

- ZOZOの検索レスポンスと財務時系列レスポンスがraw保存されている
- EDINETコードの選択理由を説明できる
- 保存ファイルにAPIキーが含まれていない
- 保存済みレスポンスだけで次の加工処理を試せる
- 直近5年度の主要指標を取得元画面と照合できる
- 欠損とゼロを区別して確認できる
- `docs/phase2-validation.md` に取得とWeb画面照合の結果が記録されている
