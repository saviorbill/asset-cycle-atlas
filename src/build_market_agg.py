# -*- coding: utf-8 -*-
"""全A市场每日聚合指标：从 panel_csi_all_full.parquet 计算。

输出 cache/market_daily.parquet，列：
date, count, total_mv, pe_median, pb_median, turnover_median, amount,
weighted_pe, up_ratio, median_pct, concentration_top5
"""
import os, sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PANEL_PARQUET, CACHE_DIR

os.makedirs(CACHE_DIR, exist_ok=True)
OUT = os.path.join(CACHE_DIR, "market_daily.parquet")

COLS = ["date", "ticker", "close", "close_raw", "total_mv", "turnover_rate", "pe", "pb", "vwap", "volume", "amount"]

def main():
    print("读取面板...")
    tbl = pq.read_table(PANEL_PARQUET, columns=COLS)
    df = tbl.to_pandas()
    print(f"读取完成: {len(df)} 行")

    df["date"] = pd.to_datetime(df["date"])
    # 成交额优先用面板里的实际成交额（元）；旧面板没有该列时退回 vwap*volume。
    # 注意 vwap 是前复权价，乘以原始成交量会低估历史成交额。
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        fallback = df["vwap"] * df["volume"]
        df["amount"] = df["amount"].where(df["amount"].notna(), fallback)
    else:
        df["amount"] = df["vwap"] * df["volume"]
    # 排序以便计算 pct_change
    print("排序中...")
    df = df.sort_values(["ticker", "date"])
    # 部分日期面板的复权收盘价缺失（未复权价完整）。用最近有效复权因子补齐，
    # 避免 ffill 把整段行情当成平盘，也避免 200/252 日窗口被 NaN 截断。
    print("补齐缺失的复权收盘价 ...")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["close_raw"] = pd.to_numeric(df["close_raw"], errors="coerce")
    ratio = df["close"] / df["close_raw"]
    ratio = ratio.groupby(df["ticker"], sort=False).ffill()
    ratio = ratio.groupby(df["ticker"], sort=False).bfill()
    filled = df["close_raw"] * ratio
    df["close"] = df["close"].where(df["close"].notna(), filled)
    # 修复面板覆盖缺口：按股票前向填充 total_mv / close（部分日期仅有半数股票有市值）
    print("前向填充 total_mv / close ...")
    df["total_mv"] = df.groupby("ticker")["total_mv"].ffill()
    df["close"] = df.groupby("ticker")["close"].ffill()
    print("计算涨跌幅...")
    df["pct"] = df.groupby("ticker")["close"].pct_change()
    # 停牌/无成交日不参与涨跌家数统计（否则会被当成平盘）
    df.loc[pd.to_numeric(df["volume"], errors="coerce").fillna(0) <= 0, "pct"] = np.nan

    # 广度：200日均线上方占比 + 52周新高/新低。
    # 必须等窗口满 200/252 日才计入，否则次新股会被误判为“在均线下方/创新低”。
    print("计算均线广度（200MA / 52周新高新低）...")
    _gs = df.groupby("ticker", sort=False)
    df["ma200"] = _gs["close"].rolling(200, min_periods=200).mean().reset_index(level=0, drop=True)
    df["hi252"] = _gs["close"].rolling(252, min_periods=252).max().reset_index(level=0, drop=True)
    df["lo252"] = _gs["close"].rolling(252, min_periods=252).min().reset_index(level=0, drop=True)
    df["above200"] = np.where(df["ma200"].notna(),
                              (df["close"] > df["ma200"]).astype(float), np.nan)
    df["new_high"] = np.where(df["hi252"].notna(),
                              (df["close"] >= df["hi252"]).astype(float), np.nan)
    df["new_low"] = np.where(df["lo252"].notna(),
                             (df["close"] <= df["lo252"]).astype(float), np.nan)

    # 过滤无效
    pe = df["pe"].where(df["pe"] > 0)
    pb = df["pb"].where(df["pb"] > 0)
    df["pe"] = pe
    df["pb"] = pb

    print("按日期聚合...")
    g = df.groupby("date")

    def top5_concentration(a):
        a = a[a > 0].dropna()
        if len(a) == 0:
            return np.nan
        a = a.sort_values(ascending=False)
        k = max(1, int(np.ceil(len(a) * 0.05)))
        total = a.sum()
        return float(a.iloc[:k].sum() / total) if total > 0 else np.nan

    agg = pd.DataFrame({
        "count": g["ticker"].count(),
        "total_mv": g["total_mv"].sum(),
        "pe_median": g["pe"].median(),
        "pb_median": g["pb"].median(),
        "turnover_median": g["turnover_rate"].median(),
        "amount": g["amount"].sum(),
        "up_ratio": g["pct"].apply(lambda s: float((s > 0).sum() / s.notna().sum()) if s.notna().any() else np.nan),
        "median_pct": g["pct"].median(),
        "concentration_top5": g["amount"].apply(top5_concentration),
        "above200_ratio": g["above200"].mean(),
        "new_high_n": g["new_high"].sum(),
        "new_low_n": g["new_low"].sum(),
    })
    # 加权PE(整体法) = sum(mv) / sum(mv/pe)
    df["mv_over_pe"] = np.where(df["pe"] > 0, df["total_mv"] / df["pe"], np.nan)
    agg["weighted_pe"] = g["total_mv"].sum() / g["mv_over_pe"].sum()

    agg = agg.reset_index()

    # 面板只到某个日期时，保留 update_indicators.py 已增量更新的尾部，避免重跑回滚数据
    if os.path.exists(OUT):
        try:
            old = pd.read_parquet(OUT)
            old["date"] = pd.to_datetime(old["date"])
            _maxd = agg["date"].max()
            tail = old[old["date"] > _maxd]
            if len(tail):
                tail = tail.reindex(columns=agg.columns)
                agg = pd.concat([agg, tail], ignore_index=True).sort_values("date").reset_index(drop=True)
                print("保留面板之后的已有增量数据:", len(tail), "行 |",
                      tail["date"].min().date(), "~", tail["date"].max().date())
        except Exception as e:
            print("保留增量数据失败（继续覆盖）:", e)

    agg.to_parquet(OUT, index=False)
    print("已保存:", OUT)
    print("日期范围:", agg["date"].min().date(), "~", agg["date"].max().date(), "| 行数:", len(agg))
    print(agg.tail(3).to_string())


if __name__ == "__main__":
    main()
