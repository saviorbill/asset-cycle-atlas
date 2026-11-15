# -*- coding: utf-8 -*-
"""叙事经济学引擎：主题板块 vs 沪深300 相对走势（重合/偏离判据） + 主线识别。

核心判据（华源叙事经济学）："板块 vs 沪深300 走势是否重合"——
  重合 = 叙事变化告一段落（兑现/垃圾时间）；偏离 = 正在发生叙事变化（起涨/见顶回落）。

实现：
  - 每主题滚动超额收益（60/120/250 日累计超额 vs 沪深300）
  - 主线识别：250日累计收益排名
  - 叙事状态：起涨 / 加速 / 兑现 / 回落 / 垃圾时间（基于超额收益的方向与加速度）
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import INDEX_CSV, CACHE_DIR


def load_theme():
    t = pd.read_parquet(os.path.join(CACHE_DIR, "theme_daily.parquet"))
    t["date"] = pd.to_datetime(t["date"])
    return t


def load_hs300_ret():
    idx = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date")
    idx["hs300_ret"] = idx["沪深300"].pct_change()
    return idx[["date", "沪深300", "hs300_ret"]]


def compute_excess(theme=None, hs300=None):
    """返回长表：date, theme, ret_equal, hs300_ret, excess(日), cum_excess(累计)。"""
    if theme is None:
        theme = load_theme()
    if hs300 is None:
        hs300 = load_hs300_ret()
    df = theme.merge(hs300[["date", "hs300_ret"]], on="date", how="left")
    df["excess"] = df["ret_equal"] - df["hs300_ret"]
    df = df.sort_values(["theme", "date"])
    df["cum_excess"] = df.groupby("theme")["excess"].transform(
        lambda s: s.cumsum())
    return df


def rolling_excess(df, windows=(60, 120, 250)):
    """每主题滚动累计超额收益（未来 N 日？不，过去 N 日）。"""
    out = df.copy()
    for w in windows:
        out[f"excess_{w}d"] = out.groupby("theme")["excess"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())
    return out


def narrative_state(row):
    """基于 60d 与 120d 超额收益的方向/加速度判定叙事状态。"""
    e60 = row.get("excess_60d", 0)
    e120 = row.get("excess_120d", 0)
    # 超额收益的"近期动能" = 60d 与 120d 之差（近似 60d 加速度）
    accel = e60 - (e120 - e60) if (e120 is not None and e60 is not None) else 0
    if e60 is None or e120 is None:
        return "—"
    if abs(e60) < 0.03 and abs(e120) < 0.05:
        return "垃圾时间"
    if e60 > 0 and accel > 0.02:
        return "加速"
    if e60 > 0 and accel <= 0.02:
        return "兑现"
    if e60 < 0:
        return "回落"
    return "起涨"


def snapshot(theme=None, hs300=None):
    """最新一期：每主题的近期超额收益 + 叙事状态 + 主线排名。"""
    df = compute_excess(theme, hs300)
    df = rolling_excess(df)
    last_date = df["date"].max()
    snap = df[df["date"] == last_date].copy()
    # 主线排名：250日累计超额（正=跑赢）
    snap = snap.sort_values("excess_250d", ascending=False)
    rows = []
    for rank, (i, r) in enumerate(snap.iterrows(), start=1):
        rows.append({
            "theme": r["theme"],
            "rank": rank,
            "excess_60d": round(float(r["excess_60d"]) * 100, 1) if pd.notna(r["excess_60d"]) else None,
            "excess_120d": round(float(r["excess_120d"]) * 100, 1) if pd.notna(r["excess_120d"]) else None,
            "excess_250d": round(float(r["excess_250d"]) * 100, 1) if pd.notna(r["excess_250d"]) else None,
            "state": narrative_state(r),
        })
    return {"asof": last_date.strftime("%Y-%m-%d"), "themes": rows}


if __name__ == "__main__":
    snap = snapshot()
    print("叙事快照 asof:", snap["asof"])
    print(f"{'排名':<4}{'主题':<12}{'60日超额%':>10}{'120日超额%':>11}{'250日超额%':>11}{'状态':>8}")
    for r in snap["themes"]:
        print(f"{r['rank']:<4}{r['theme']:<12}{r['excess_60d']:>10}{r['excess_120d']:>11}{r['excess_250d']:>11}{r['state']:>8}")
