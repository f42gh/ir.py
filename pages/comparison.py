"""セクター別比較ビュー."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import COMPANIES, fetch_company_data

st.set_page_config(page_title="セクター別比較", layout="wide")
st.title("🏢 セクター別比較")


@st.cache_data(ttl=3600)
def fetch_all_for_comparison() -> pd.DataFrame:
    """全企業データを取得してDataFrame化."""
    rows = []
    codes = list(COMPANIES.keys())
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_code = {executor.submit(fetch_company_data, c): c for c in codes}
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            meta = COMPANIES[code]
            yf_data = future.result()
            if yf_data is None:
                continue
            rows.append(
                {
                    "企業名": meta["name"],
                    "ティア": meta["tier"],
                    "セクター": yf_data.get("sector", "N/A"),
                    "時価総額（億円）": (yf_data.get("marketCap") or 0) / 1e8,
                    "売上高（億円）": (yf_data.get("totalRevenue") or 0) / 1e8,
                    "営業利益率（%）": (yf_data.get("operatingMargins") or 0) * 100,
                    "平均年収（万円）": meta["avg_salary_man"],
                    "従業員数": yf_data.get("fullTimeEmployees") or 0,
                    "PER": yf_data.get("trailingPE") or 0,
                    "ROE（%）": (yf_data.get("returnOnEquity") or 0) * 100,
                }
            )
    return pd.DataFrame(rows)


with st.spinner("全企業データを取得中..."):
    df = fetch_all_for_comparison()

if df.empty:
    st.warning("データを取得できませんでした。")
    st.stop()

# セクター別集計
st.subheader("セクター別 平均指標")
sector_agg = (
    df.groupby("セクター")
    .agg(
        {
            "時価総額（億円）": "mean",
            "営業利益率（%）": "mean",
            "平均年収（万円）": "mean",
            "企業名": "count",
        }
    )
    .rename(columns={"企業名": "企業数"})
    .round(1)
)
st.dataframe(sector_agg, use_container_width=True)

# バブルチャート: 売上 vs 営業利益率 (サイズ=時価総額)
st.subheader("売上高 × 営業利益率（バブルサイズ＝時価総額）")
fig = px.scatter(
    df,
    x="売上高（億円）",
    y="営業利益率（%）",
    size="時価総額（億円）",
    color="ティア",
    hover_name="企業名",
    size_max=60,
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

# 年収比較バーチャート
st.subheader("平均年収ランキング")
df_salary = df.sort_values("平均年収（万円）", ascending=True)
fig2 = px.bar(
    df_salary,
    x="平均年収（万円）",
    y="企業名",
    color="ティア",
    orientation="h",
    height=max(400, len(df_salary) * 40),
)
fig2.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig2, use_container_width=True)
