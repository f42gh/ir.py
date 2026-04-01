import json
from concurrent.futures.thread import ThreadPoolExecutor

# import concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st
import yfinance as yf

# from _plotly_utils_colors_diverging import Fall

with open("COMPANIES.json") as f:
    COMPANIES = json.load(f)


@st.cache_data(ttl=3600)
def fetch_company_data(ticker_code):
    try:
        ticker = yf.Ticker(ticker_code)
        info = ticker.info
        if not info or "shortName" not in info:
            return None
        return info
    except Exception as e:
        return None


def fetch_all_companies() -> dict:
    """並行取得"""
    results = {}
    progress = st.progress(0, text="データを取得中...")
    codes = list(COMPANIES.keys())
    completed = 0

    with ThreadPoolExecutor(max_workers=5) as executors:
        future_to_code = {
            executor.submit(fetch_company_data, code): code for code in codes
        }
