import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import yfinance as yf
from _plotly_utils.colors.diverging import Fall, Fall_r

with open("COMPANIES.json") as f:
    COMPANIES = json.load(f)


@st.cache_data(ttl=3600)  # 1時間キャッシュ
def fetch_company_data(ticker_code: str) -> dict | None:
    try:
        ticker = yf.Ticker(ticker_code)
        info = ticker.info
        if not info or "shortName" not in info:
            return None
        return info
    except Exception as e:
        return None


def fetch_all_companies() -> dict:
    """全企業のデータを並列取得"""
    results = {}
    progress = st.progress(0, text="企業データを取得中...")

    codes = list(COMPANIES.keys())
    completed = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_code = {
            executor.submit(fetch_company_data, code): code for code in codes
        }
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            results[code] = future.result()
            completed += 1
            progress.progress(
                completed / len(codes), text=f"取得中... {completed}/{len(codes)}"
            )

    progress.empty()
    return results


def format_oku(value: float | None) -> str:
    """数値を億円単位に変換して表示"""
    if value is None:
        return "N/A"
    oku = value / 1e8
    if oku >= 1000:
        return f"{oku / 1000:.1f}兆円"
    return f"{oku:.0f}億円"


def format_percent(value: float | None) -> str:
    """小数を%表示"""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def render_company_card(code: str, yf_data: dict | None, meta: dict):
    """1社分の企業カードを描画"""
    with st.container(border=True):
        # ヘッダー: 企業名 + ティア
        col_name, col_tier = st.columns([3, 1])
        with col_name:
            st.subheader(meta["name"])
        with col_tier:
            tier = meta["tier"]
            if "Tier 1" in tier:
                st.markdown(f"**:red[{tier}]**")
            elif "Tier 2.5" in tier:
                st.markdown(f"**:orange[{tier}]**")
            elif "Tier 2" in tier:
                st.markdown(f"**:blue[{tier}]**")
            else:
                st.markdown(f"**{tier}**")

        if yf_data is None:
            st.warning(f"⚠️ {code} のデータ取得に失敗しました")
            st.caption(f"📝 {meta['note']}")
            return

        # メトリクス行
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("時価総額", format_oku(yf_data.get("marketCap")))
        with c2:
            st.metric("売上高", format_oku(yf_data.get("totalRevenue")))
        with c3:
            st.metric("営業利益率", format_percent(yf_data.get("operatingMargins")))
        with c4:
            st.metric("平均年収（有報）", f"{meta['avg_salary_man']}万円")

        # サブメトリクス
        c5, c6, c7, c8 = st.columns(4)
        with c5:
            employees = yf_data.get("fullTimeEmployees")
            st.metric("従業員数", f"{employees:,}人" if employees else "N/A")
        with c6:
            st.metric(
                "PER",
                f"{yf_data.get('trailingPE', 'N/A'):.1f}倍"
                if yf_data.get("trailingPE")
                else "N/A",
            )
        with c7:
            st.metric("ROE", format_percent(yf_data.get("returnOnEquity")))
        with c8:
            price = yf_data.get("currentPrice")
            st.metric("株価", f"¥{price:,.0f}" if price else "N/A")

        # メモ
        st.caption(f"📝 {meta['note']}")

        # 企業サイトリンク
        website = yf_data.get("website")
        if website:
            st.caption(f"🔗 [{website}]({website})")


def main():
    st.set_page_config(
        page_title="IRダッシュボード",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊IRダッシュボード")
    st.caption("")

    # ---- サイドバー: フィルタ ----
    with st.sidebar:
        st.header("フィルタ")
        # ソート
        sort_by = st.selectbox(
            "並び替え",
            options=[
                "時価総額（大→小）",
                "平均年収（高→低）",
                "営業利益率（高→低）",
            ],
        )

        st.divider()
        st.caption("💡 データは1時間キャッシュされます")
        if st.button("🔄 データを再取得"):
            st.cache_data.clear()
            st.rerun()

    # ---- データ取得 ----
    all_data = fetch_all_companies()

    selected_tiers = st.multiselect("tier filter", ["1", "2", "3", "4", "5"])
    # ---- フィルタ適用 ----
    filtered_codes = [
        code for code, meta in COMPANIES.items() if meta["tier"] in selected_tiers
    ]

    # ---- ソート ----
    def sort_key(code):
        meta = COMPANIES[code]
        yf_data = all_data.get(code) or {}
        if sort_by == "時価総額（大→小）":
            return -(yf_data.get("marketCap") or 0)
        elif sort_by == "平均年収（高→低）":
            return -meta["avg_salary_man"]
        elif sort_by == "営業利益率（高→低）":
            return -(yf_data.get("operatingMargins") or 0)
        return 0

    filtered_codes.sort(key=sort_key)

    # ---- 描画 ----
    st.markdown(f"**{len(filtered_codes)}社** を表示中")

    for code in filtered_codes:
        render_company_card(code, all_data.get(code), COMPANIES[code])

    # ---- フッター ----
    st.divider()
    st.caption(
        "⚠️ 財務データは Yahoo Finance 経由の参考値です。"
        "正確な情報は各社IRページ・有価証券報告書を確認してください。"
    )
    st.caption("Built with Streamlit + yfinance")


if __name__ == "__main__":
    main()
