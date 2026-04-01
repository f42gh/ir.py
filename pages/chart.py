"""売上・利益推移の時系列チャート."""

import os
import sys

import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import COMPANIES

st.set_page_config(page_title="時系列チャート", layout="wide")
st.title("📈 売上・利益推移チャート")

# 企業選択
options = {f"{m['name']} ({code})": code for code, m in COMPANIES.items()}
selected_label = st.selectbox("企業を選択", list(options.keys()))
ticker_code = options[selected_label]


@st.cache_data(ttl=3600)
def fetch_financials(code: str) -> dict:
    """年次の売上・営業利益・純利益を取得."""
    ticker = yf.Ticker(code)
    fin = ticker.financials  # 年次損益計算書
    if fin is None or fin.empty:
        return {}
    data = {}
    for col in fin.columns:
        year = col.strftime("%Y")
        revenue = fin.at["Total Revenue", col] if "Total Revenue" in fin.index else None
        op_income = (
            fin.at["Operating Income", col] if "Operating Income" in fin.index else None
        )
        net_income = fin.at["Net Income", col] if "Net Income" in fin.index else None
        data[year] = {
            "revenue": revenue,
            "operating_income": op_income,
            "net_income": net_income,
        }
    return data


with st.spinner("財務データを取得中..."):
    financials = fetch_financials(ticker_code)

if not financials:
    st.warning("この企業の財務データを取得できませんでした。")
    st.stop()

years = sorted(financials.keys())
revenue = [financials[y]["revenue"] for y in years]
op_income = [financials[y]["operating_income"] for y in years]
net_income = [financials[y]["net_income"] for y in years]

to_oku = lambda vals: [v / 1e8 if v is not None else None for v in vals]

fig = go.Figure()
fig.add_trace(
    go.Bar(x=years, y=to_oku(revenue), name="売上高（億円）", marker_color="#636EFA")
)
fig.add_trace(
    go.Bar(
        x=years, y=to_oku(op_income), name="営業利益（億円）", marker_color="#00CC96"
    )
)
fig.add_trace(
    go.Bar(x=years, y=to_oku(net_income), name="純利益（億円）", marker_color="#EF553B")
)

fig.update_layout(
    barmode="group",
    title=f"{COMPANIES[ticker_code]['name']} 年次業績推移",
    xaxis_title="年度",
    yaxis_title="億円",
    height=500,
)

st.plotly_chart(fig, use_container_width=True)

# 数値テーブルも表示
import pandas as pd

df = pd.DataFrame(
    {
        "年度": years,
        "売上高（億円）": to_oku(revenue),
        "営業利益（億円）": to_oku(op_income),
        "純利益（億円）": to_oku(net_income),
    }
).set_index("年度")
st.dataframe(df.style.format("{:,.0f}"), use_container_width=True)
