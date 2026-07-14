# Phase 3 分析用JSON生成準備

## 最初の実装単位

Phase 2で保存したZOZOの財務rawを入力し、`frontend/data/financials.json` を生成する。最初はZOZOの1社だけで変換・計算・追跡性を固め、同じ処理を残り4社へ広げる。

Phase 3の変換処理はEDINET DB APIを呼ばない。入力ファイルを明示指定し、同じrawから常に同じJSONを生成する。

実装は `src/build_financials.py`、自動テストは `tests/test_build_financials.py` に置く。

想定する実行形式:

```bash
uv run python src/build_financials.py \
  --input data/raw/zozo__financials__20260714T050058Z.json \
  --output frontend/data/financials.json
```

`latest` の自動選択は行わない。どのrawから生成したかをコマンドと出力JSONから追跡できるようにする。

## 入出力契約

トップレベルと期間別の形式は `phase1-financial-data-spec.md` の `schema_version: "1.0"` に従う。

- `generated_at`: rawファイル名のUTC時刻をISO 8601へ変換した値。実行時刻を使わず、再生成結果を決定的にする
- `companies`: Phase 1の取得順。最初の実装ではZOZOだけ
- `ticker`: `3092.T`
- `name`: `ZOZO`
- `edinet_code`: rawの `meta.edinet_code`。`E05725` と一致しなければ失敗
- `currency`: `JPY`
- `periods`: `fiscal_year` の昇順
- `fetched_at`: 各期間とも入力rawファイル名のUTC時刻

### 年度・会計基準

| 出力 | raw | 変換 |
|---|---|---|
| `fiscal_year` | `fiscal_year` | 整数のまま |
| `fiscal_year_end` | 該当フィールドなし | `null`。決算月から推測しない |
| `accounting_standard` | `accounting_standard` | `JP` / `JP_GAAP` → `JGAAP`、`IFRS` → `IFRS`、`US` / `US_GAAP` → `USGAAP`、その他・欠損 → `UNKNOWN` |
| `consolidated` | 年次財務APIの取得契約 | ZOZOのPhase 3入力では `true` |

`meta.latest_shares_snapshot.fiscal_year_end` は四半期決算短信の最新スナップショットに属し、年次 `data[]` と直接対応しないため使用しない。

### 取得指標

| 出力 `metrics` | raw | 変換 |
|---|---|---|
| `revenue` | `revenue` | 整数の円 |
| `operating_income` | `operating_income` | 整数の円 |
| `net_income` | `net_income` | 整数の円 |
| `total_assets` | `total_assets` | 整数の円 |
| `equity` | `shareholders_equity` | 整数の円。`net_assets` は使わない |
| `operating_cash_flow` | `cf_operating` | 整数の円 |
| `investing_cash_flow` | `cf_investing` | 符号を変えず整数の円 |
| `roe_pct` | `roe_official` | rawの小数を100倍し、小数第4位までに丸める |

金額は、欠損または `null` なら出力も `null` とする。整数または小数部がゼロのJSON numberだけを受け付けて整数へ変換し、小数円や文字列は異常データとして失敗させる。ゼロと負値はそのまま保持する。

### 計算指標

計算式と `null` 条件はPhase 1仕様をそのまま使用する。

- `revenue_yoy_pct`: 前年度比。最初の年度は `null`
- `operating_margin_pct`: 営業利益 ÷ 売上高 × 100
- `free_cash_flow`: 営業CF + 投資CF。投資CFの符号は反転しない
- `revenue_cagr_3y_pct`: 当年度と3期間前を使用。ZOZOの5年度入力では2025年と2026年だけ計算可能

割合は計算途中で丸めず、JSONへ格納するときだけ小数第4位へ丸める。

### 出典

| 出力 `source_document` | raw | 変換 |
|---|---|---|
| `document_id` | `doc_id` | 文字列または `null` |
| `document_type` | — | `annual_securities_report` 固定 |
| `filed_at` | `submit_date` | `YYYY-MM-DD HH:MM` の日付部分を `YYYY-MM-DD` として保存。解釈できなければ `null` |
| `url` | `edinet_filing_url` | URL文字列または `null` |

## 安全性と検証

- rawトップレベルが `data` 配列と `meta` オブジェクトを持つことを確認する
- `meta.period == "annual"`、EDINETコード、5年度、年度重複なしを確認する
- rawの年度行は入力順に依存せず、重複確認後に `fiscal_year` 昇順へ並べる
- 入力rawは一切変更しない
- 全期間の変換と計算が成功してから一時ファイルへ書き、最後に出力を置き換える。失敗時は既存の `financials.json` を壊さない
- JSONはUTF-8、インデント2、末尾改行ありで保存する
- 生成後に同じ入力でもう一度生成し、ファイル内容が完全一致することを確認する

## テスト準備

最初の実装では標準ライブラリの `unittest` を継続使用し、最低限次を確認する。

1. ZOZOの実rawから5年度を昇順で生成できる
2. 金額の `.0` を整数円へ変換でき、小数円を拒否する
3. 欠損とゼロ、負の営業利益・投資CFを区別する
4. 前年比、営業利益率、FCF、3年CAGRの正常系と `null` 条件
5. `roe_official` の小数からパーセントポイントへの変換
6. `JP` から `JGAAP` への変換と未知の会計基準の `UNKNOWN` 化
7. `doc_id`、提出日、URL、取得日時を追跡できる
8. シャッフルされた年度を昇順化し、重複年度、異なるEDINETコード、不正JSONでは既存出力を変更しない
9. 同じ入力から生成した2ファイルが完全一致する

## 実装前の確認結果

- ZOZO rawは2022〜2026年度の5件で、主要8指標と出典3項目に欠損・ゼロはない
- 金額は円だが、実レスポンスでは `166199000000.0` のようなJSON numberで返る
- `roe_official` は `0.625` のような小数で、画面の62.5%に対応する
- `shareholders_equity` と `net_assets` は年度によって異なるため、Phase 1の `equity` には前者だけを使う
- 現行APIには各年次行の `fiscal_year_end` がないため、Phase 3では `null` を保持する
