# -*- coding: utf-8 -*-
"""ETF 起涨信号引擎：股票型ETF按主题分组，计算相对沪深300的超额收益与叙事状态。

输出:
  - 主题级：每主题的中位超额收益 + 起涨/兑现状态
  - 个券级：主线ETF榜 + 正在"起涨"的ETF榜（近60日超额转正加速）
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ETF_DAILY_CSV, ETF_BASIC_CSV, INDEX_CSV
from etf_map import classify_etf, THEME_KEYWORDS
from narrative import narrative_state


def load_etf_ret():
    """股票型ETF日收益 + 主题映射。"""
    b = pd.read_csv(ETF_BASIC_CSV)
    b = b[b["fund_type"] == "股票型"].copy()
    b["theme"] = b.apply(lambda r: classify_etf(r["name"], r.get("benchmark", "")), axis=1)
    b = b[b["theme"] != "宽基"]  # 剔除宽基
    codes = set(b["ts_code"])

    d = pd.read_csv(ETF_DAILY_CSV, usecols=["ts_code", "trade_date", "close"])
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str), format="%Y%m%d")
    d = d[d["ts_code"].isin(codes)]
    d = d.sort_values(["ts_code", "trade_date"])
    d["ret"] = d.groupby("ts_code")["close"].pct_change()
    d = d.merge(b[["ts_code", "name", "theme"]], on="ts_code", how="left")
    return d


def compute_excess():
    idx = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date")
    idx["hs300_ret"] = idx["沪深300"].pct_change()
    hs = idx[["date", "hs300_ret"]]

    d = load_etf_ret()
    d = d.merge(hs, left_on="trade_date", right_on="date", how="left")
    d["excess"] = d["ret"] - d["hs300_ret"]
    d = d.sort_values(["ts_code", "trade_date"])
    for w in (60, 120, 250):
        d[f"excess_{w}d"] = d.groupby("ts_code")["excess"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())
    return d


def snapshot():
    d = compute_excess()
    last = d["trade_date"].max()
    snap = d[d["trade_date"] == last].dropna(subset=["excess_250d"]).copy()
    snap["state"] = snap.apply(narrative_state, axis=1)

    # 主题级聚合（中位数）
    theme_rows = []
    for theme, g in snap.groupby("theme"):
        if len(g) < 2:
            continue
        theme_rows.append({
            "theme": theme,
            "n": len(g),
            "excess_60d": round(float(g["excess_60d"].median()) * 100, 1),
            "excess_120d": round(float(g["excess_120d"].median()) * 100, 1),
            "excess_250d": round(float(g["excess_250d"].median()) * 100, 1),
            "up_ratio": round(float((g["excess_60d"] > 0).mean()) * 100, 0),
        })
    theme_df = pd.DataFrame(theme_rows).sort_values("excess_250d", ascending=False)

    # 个券主线榜（250日超额 top）
    top_etf = snap.sort_values("excess_250d", ascending=False).head(15)

    # 起涨榜：近60日超额>5% 且 250日超额<15%（近期启动、此前未大涨）
    rising = snap[(snap["excess_60d"] > 0.05) & (snap["excess_250d"] < 0.15)].sort_values(
        "excess_60d", ascending=False).head(15)

    def fmt(df):
        return [{"name": r["name"], "theme": r["theme"],
                 "excess_60d": round(float(r["excess_60d"]) * 100, 1),
                 "excess_250d": round(float(r["excess_250d"]) * 100, 1),
                 "state": r["state"]} for _, r in df.iterrows()]

    return {
        "asof": last.strftime("%Y-%m-%d"),
        "themes": theme_df.to_dict("records"),
        "top_etf": fmt(top_etf),
        "rising_etf": fmt(rising),
    }


if __name__ == "__main__":
    import json
    s = snapshot()
    print("ETF叙事快照 asof:", s["asof"])
    print("\n=== 主题级（中位超额%）===")
    for r in s["themes"]:
        print(f"{r['theme']:<10} n={r['n']:<4} 60d={r['excess_60d']:>6}% 120d={r['excess_120d']:>6}% 250d={r['excess_250d']:>6}% 上涨占比={r['up_ratio']}%")
    print("\n=== 主线ETF榜（250日超额 top10）===")
    for r in s["top_etf"][:10]:
        print(f"  {r['name']:<26} {r['theme']:<8} 60d={r['excess_60d']:>6}% 250d={r['excess_250d']:>6}% {r['state']}")
    print("\n=== 正在起涨ETF榜（60d>5%且250d<15%）===")
    for r in s["rising_etf"][:10]:
        print(f"  {r['name']:<26} {r['theme']:<8} 60d={r['excess_60d']:>6}% 250d={r['excess_250d']:>6}% {r['state']}")
