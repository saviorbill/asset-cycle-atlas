# -*- coding: utf-8 -*-
"""核对融资余额 / A股总市值的最新跳变及交易所完整性。"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"

margin = pd.read_csv(CACHE / "margin_full.csv", dtype={"trade_date": str})
margin["date"] = pd.to_datetime(margin["trade_date"], errors="coerce")
margin["rzye"] = pd.to_numeric(margin["rzye"], errors="coerce")
recent = margin.dropna(subset=["date", "rzye"])
recent = recent[recent["date"] >= recent["date"].max() - pd.Timedelta(days=35)]
print("融资余额分交易所（亿元）")
pivot = recent.pivot_table(index="date", columns="exchange_id", values="rzye", aggfunc="sum") / 1e8
pivot["合计"] = pivot.sum(axis=1)
pivot["交易所数"] = recent.groupby("date")["exchange_id"].nunique()
print(pivot.tail(12).round(2).to_string())

market = pd.read_parquet(CACHE / "market_daily.parquet", columns=["date", "total_mv"])
market["date"] = pd.to_datetime(market["date"])
market["total_mv"] = pd.to_numeric(market["total_mv"], errors="coerce")
total = margin.groupby("date", as_index=False)["rzye"].sum()
merged = total.merge(market, on="date", how="inner").sort_values("date")
merged["ratio"] = merged["rzye"] / (merged["total_mv"] * 1e4) * 100
merged["ratio_change"] = merged["ratio"].pct_change() * 100
print("\n比率与总市值（总市值：万亿元）")
latest = merged.tail(12).copy()
latest["total_mv"] = latest["total_mv"] / 1e8
print(latest[["date", "rzye", "total_mv", "ratio", "ratio_change"]].round(3).to_string(index=False))

print("\n最新日期交易所记录")
print(margin[margin["date"] == margin["date"].max()][["trade_date", "exchange_id", "rzye"]].to_string(index=False))
