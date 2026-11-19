# -*- coding: utf-8 -*-
"""用「前复权」逐股 CSV 重建 2005–2015 的全A 日度结构指标。

输出：应用数据/cache/market_daily_pre2016.parquet（列与 market_daily 对齐）

为什么单独做：现有 market_daily 来自 panel_csi_all_full（2016 起）。要往前推，
唯一现成的全市场数据是 A股数据/前复权/ 下 5,836 只个股 CSV（2000 年起）。

口径说明（与 2016 版不完全一致，交界处可能有小台阶）：
  - above200_ratio：收盘价 > 200 日均线；不足 120 个交易日不计。
  - new_high_n / new_low_n：收盘价创 250 日新高/新低（同样要求 ≥120 日历史）。
  - weighted_pe：Σ总市值 / Σ(总市值/滚动市盈率)，亏损股不参与。
  - concentration_top5：成交额前 5 名占全市场成交额比重。

用法：python3 src/build_market_agg_pre2016.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import DATA_DIR, CACHE_DIR  # noqa: E402

SRC = os.path.join(DATA_DIR, "前复权")
OUT = os.path.join(CACHE_DIR, "market_daily_pre2016.parquet")
START, END = "2005-01-01", "2015-12-31"

COLS = ["日期", "收盘价", "成交额（元）", "换手率", "涨幅%", "是否涨停",
        "总市值（元）", "滚动市盈率", "市净率"]
RENAME = {"日期": "date", "收盘价": "close", "成交额（元）": "amount",
          "换手率": "turnover", "涨幅%": "pct", "是否涨停": "limit_up",
          "总市值（元）": "mv", "滚动市盈率": "pe", "市净率": "pb"}


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.csv")))
    print("个股文件 %d 个" % len(files))
    frames = []
    for i, f in enumerate(files, 1):
        try:
            d = pd.read_csv(f, usecols=COLS, dtype={"是否涨停": str})
        except Exception:
            continue
        d = d.rename(columns=RENAME)
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date"])
        d = d[(d["date"] >= START) & (d["date"] <= END)]
        if d.empty:
            continue
        d = d.sort_values("date")
        close = pd.to_numeric(d["close"], errors="coerce")
        d["ma200"] = close.rolling(200, min_periods=120).mean()
        d["hi250"] = close.rolling(250, min_periods=120).max()
        d["lo250"] = close.rolling(250, min_periods=120).min()
        d["above200"] = (close > d["ma200"]).astype(float)
        d["new_high"] = (close >= d["hi250"]).astype(float)
        d["new_low"] = (close <= d["lo250"]).astype(float)
        d["is_up"] = (pd.to_numeric(d["pct"], errors="coerce") > 0).astype(float)
        d["earn"] = pd.to_numeric(d["mv"], errors="coerce") / pd.to_numeric(d["pe"], errors="coerce").replace(0, np.nan)
        frames.append(d[["date", "amount", "mv", "turnover", "pct", "pe", "pb",
                         "above200", "new_high", "new_low", "is_up", "earn"]])
        if i % 500 == 0:
            print("  已读 %d/%d" % (i, len(files)))

    allrows = pd.concat(frames, ignore_index=True)
    print("合计 %d 行，开始按日聚合" % len(allrows))

    g = allrows.groupby("date")
    out = pd.DataFrame({
        "count": g.size(),
        "total_mv": g["mv"].sum(),
        "pe_median": g["pe"].median(),
        "pb_median": g["pb"].median(),
        "turnover_median": g["turnover"].median(),
        "amount": g["amount"].sum(),
        "up_ratio": g["is_up"].mean(),
        "median_pct": g["pct"].median() / 100.0,
        "above200_ratio": g["above200"].mean(),
        "new_high_n": g["new_high"].sum(),
        "new_low_n": g["new_low"].sum(),
    })
    # 成交额前 5 占比
    top5 = (allrows.sort_values("amount", ascending=False)
            .groupby("date").head(5).groupby("date")["amount"].sum())
    out["concentration_top5"] = (top5 / out["amount"]).fillna(0)
    wpe = (g["mv"].sum() / g["earn"].sum()).replace([np.inf, -np.inf], np.nan)
    out["weighted_pe"] = wpe
    out = out.reset_index().sort_values("date")
    out = out[out["count"] >= 50]

    os.makedirs(CACHE_DIR, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print("落盘 %d 天 → %s" % (len(out), OUT))
    print(out.tail(2).to_string(index=False))


if __name__ == "__main__":
    main()
