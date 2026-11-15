# -*- coding: utf-8 -*-
"""构建主题板块(20) + 行业(110) 每日聚合：等权/市值加权收益、成交额、PE、换手率。

输出:
  cache/theme_daily.parquet    (date, theme, ret_equal, ret_mv, amount, pe_median, turnover_median, count)
  cache/industry_daily.parquet (date, industry, ret_equal, amount, pe_median, count)
"""
import os, sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PANEL_PARQUET, CACHE_DIR, STOCK_BASIC_CSV
from theme_map import industry_to_theme

os.makedirs(CACHE_DIR, exist_ok=True)
COLS = ["date", "ticker", "close", "total_mv", "pe", "turnover_rate", "vwap", "volume"]


def main():
    print("读取股票基础信息...")
    sb = pd.read_csv(STOCK_BASIC_CSV, usecols=["ts_code", "industry"])
    sb["theme"] = sb["industry"].map(industry_to_theme)

    print("读取面板...")
    tbl = pq.read_table(PANEL_PARQUET, columns=COLS)
    df = tbl.to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    print(f"面板 {len(df)} 行")

    # 映射行业/主题
    df = df.merge(sb, left_on="ticker", right_on="ts_code", how="left")
    df["theme"] = df["theme"].fillna("其他")
    df["industry"] = df["industry"].fillna("其他")

    print("排序 + 计算涨跌幅/前市值...")
    df = df.sort_values(["ticker", "date"])
    df["pct"] = df.groupby("ticker")["close"].pct_change()
    df["prev_mv"] = df.groupby("ticker")["total_mv"].shift(1)
    df["amount"] = df["vwap"] * df["volume"]
    df["pe_pos"] = df["pe"].where(df["pe"] > 0)
    df["pct_x_mv"] = df["pct"] * df["prev_mv"]

    print("按主题聚合...")
    gt = df.groupby(["date", "theme"])
    theme = pd.DataFrame({
        "ret_equal": gt["pct"].mean(),
        "ret_mv": gt["pct_x_mv"].sum() / gt["prev_mv"].sum(),
        "amount": gt["amount"].sum(),
        "pe_median": gt["pe_pos"].median(),
        "turnover_median": gt["turnover_rate"].median(),
        "count": gt["ticker"].count(),
    }).reset_index()
    theme.to_parquet(os.path.join(CACHE_DIR, "theme_daily.parquet"), index=False)

    print("按行业聚合...")
    gi = df.groupby(["date", "industry"])
    ind = pd.DataFrame({
        "ret_equal": gi["pct"].mean(),
        "amount": gi["amount"].sum(),
        "pe_median": gi["pe_pos"].median(),
        "count": gi["ticker"].count(),
    }).reset_index()
    ind.to_parquet(os.path.join(CACHE_DIR, "industry_daily.parquet"), index=False)

    print("完成。主题数:", theme["theme"].nunique(), "| 行业数:", ind["industry"].nunique(),
          "| 日期:", theme["date"].min().date(), "~", theme["date"].max().date())


if __name__ == "__main__":
    main()
