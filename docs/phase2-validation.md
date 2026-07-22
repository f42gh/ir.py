# Phase 2 取得・照合記録

## 状態

直接取得対象について、EDINET DB APIから直近5年度の年次データを取得し、保存済みJSONを読み直せることを確認した。

実行コマンドは次のとおり。APIキーはこの文書、CLI出力、rawファイルのいずれにも記録しない。

```bash
uv run --env-file .env python src/fetch_direct_companies.py
```

## 取得時の検証

各企業について、保存前に次を確認する。

- `data/COMPANIES.json` の `status` が `direct` である
- EDINETコードが `E` と5桁の数字で構成される
- rawの `meta.edinet_code` が企業メタデータと一致する
- `meta.period` が `annual` である
- `data` が重複のない5年度分で、年度昇順になっている
- レスポンス本文を加工せず、UTCの取得日時付きファイルへ保存している
- APIキーや認証ヘッダーが保存ファイルに含まれない

rawファイルは次の形式で保存する。

```text
data/raw/{ticker_slug}__financials__YYYYMMDDTHHMMSSZ.json
```

## Web画面との照合

取得対象ごとにEDINET DBの企業画面と照合する。画面の金額表示が百万円単位の場合は、rawの円を1,000,000で割って比較する。

照合対象は次のとおり。

| 分類 | rawフィールド | 確認内容 |
|---|---|---|
| 損益 | `revenue` | 売上高または売上収益 |
| 損益 | `operating_income` | 営業利益。損失は負値 |
| 損益 | `net_income` | 親会社帰属の当期利益 |
| 財政状態 | `total_assets` | 総資産 |
| 財政状態 | `shareholders_equity` | 自己資本。`net_assets` と混同しない |
| キャッシュフロー | `cf_operating` | 営業活動によるキャッシュフロー |
| キャッシュフロー | `cf_investing` | 投資活動によるキャッシュフロー |
| 比率 | `roe_official` | rawの小数を100倍した値が画面のパーセント表示と一致する |
| 出典 | `doc_id` / `submit_date` / `edinet_filing_url` | 文書ID、提出日、EDINET原本リンク |

欠損フィールドはゼロへ補完せず、欠損と実際のゼロを別々に記録する。企業や年度によって会計基準や開示項目が異なるため、値が存在しないこと自体を異常とはしない。

## 完了判定

- [x] 直接取得対象の財務レスポンスをraw保存した
- [x] 各社5年度であることを検証した
- [x] 金額が円単位であることを確認した
- [x] `roe_official` の表示単位との対応を確認した
- [x] 欠損とゼロを区別して記録した
- [x] 各年度の出典情報を確認した
- [x] APIキーを保存していないことを確認した
