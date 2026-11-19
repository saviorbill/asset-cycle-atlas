# -*- coding: utf-8 -*-
"""国家队 ETF 净申购 —— 唯一能按日观察的"谁在买"指标。

原理
----
汇金等国家队入场几乎全部通过宽基 ETF 完成，而 ETF 的**份额**只会在申赎时变化，
价格涨跌不改变份额。所以：

    当日净申购金额 ≈ Δ份额 × 当日收盘价（未复权）

把沪深300 的几只主力 ETF 加总，再做 20 日累计，就是国家队的净买入额。
用**占篮子规模的比例**而不是绝对金额，是为了剔除 ETF 规模的长期增长
（2016 年 574 亿 → 2026 年 5,021 亿），否则近年的读数永远在高位。

校验：2024-02-06 汇金公告扩大增持当日，20 日累计净申购 +1,647 亿元
（占规模 44%），与公开报道量级一致 —— 说明口径是对的。

输出：cache/nsf_flow.csv  →  trade_date, flow, aum, f20, pct_aum
"""
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR, ETF_DAILY_CSV, FUND_SHARE_DIR  # noqa: E402

OUT = os.path.join(CACHE_DIR, "nsf_flow.csv")

# 各指数的主力 ETF 篮子。只保留有对应指数收盘价的（上证50 暂缺价格序列）。
BASKETS = {
    "沪深300": ["510300.SH", "510310.SH", "510330.SH", "510350.SH", "159919.SZ"],
    "中证500": ["510500.SH", "159922.SZ"],
    "中证1000": ["512100.SH", "159845.SZ"],
    "创业板指": ["159915.SZ"],
    "科创50": ["588000.SH", "588080.SH"],
}
WINDOW = 20


def basket_series(fs, px, basket):
    m = fs[fs.ts_code.isin(basket)].merge(
        px[px.ts_code.isin(basket)], on=["ts_code", "trade_date"], how="left")
    m = m.sort_values(["ts_code", "trade_date"])
    m["close"] = m.groupby("ts_code")["close"].ffill()
    m = m[m.close.notna()]
    m["aum"] = m.fd_share * m.close
    m["flow"] = m.groupby("ts_code")["fd_share"].diff() * m.close
    d = (m.groupby("trade_date").agg(flow=("flow", "sum"), aum=("aum", "sum")).sort_index())
    d["f20"] = d["flow"].rolling(WINDOW).sum()
    d["pct_aum"] = d["f20"] / d["aum"] * 100
    return d.dropna(subset=["pct_aum"])


def main():
    if not os.path.isdir(FUND_SHARE_DIR):
        print("找不到 %s（先跑 fetch_ml_extra.py 的 fund_share 部分）" % FUND_SHARE_DIR)
        return
    files = sorted(glob.glob(os.path.join(FUND_SHARE_DIR, "*.parquet")))
    if not files:
        print("fund_share 无文件")
        return

    fs = pd.concat([pd.read_parquet(f, columns=["ts_code", "trade_date", "fd_share"])
                    for f in files], ignore_index=True)
    fs["trade_date"] = pd.to_datetime(fs["trade_date"].astype(str), format="%Y%m%d",
                                      errors="coerce")
    fs = fs.dropna(subset=["trade_date"])

    codes = sorted({c for v in BASKETS.values() for c in v})
    px = pd.read_csv(ETF_DAILY_CSV, usecols=["ts_code", "trade_date", "close"],
                     parse_dates=["trade_date"])
    px = px[px.ts_code.isin(codes) & (px.close > 0)]

    out = None
    for name, basket in BASKETS.items():
        d = basket_series(fs, px, basket)
        if d.empty:
            continue
        part = pd.DataFrame({
            "trade_date": d.index,
            "pct_" + name: d["pct_aum"].values,
            "amt_" + name: (d["f20"] / 1e4).values,      # 亿元
            "flow_" + name: (d["flow"] / 1e4).values,
            "aum_" + name: (d["aum"] / 1e4).values,
        })
        out = part if out is None else out.merge(part, on="trade_date", how="outer")
        if name == "沪深300":   # 兼容旧字段
            out["flow"] = part["flow_沪深300"]
            out["aum"] = part["aum_沪深300"]
            out["f20"] = part["amt_沪深300"] * 1e4
            out["pct_aum"] = part["pct_沪深300"]
    out = out.sort_values("trade_date").reset_index(drop=True)

    os.makedirs(CACHE_DIR, exist_ok=True)
    out.to_csv(OUT, index=False)

    print("asof %s  →  %s（%d 天，%d 个指数）"
          % (out.trade_date.iloc[-1].date(), OUT, len(out), len(BASKETS)))
    for name in BASKETS:
        col = "pct_" + name
        if col in out.columns:
            x = out[col].dropna()
            if len(x):
                print("  %-6s 20日净申购 %+6.1f%%  历史分位 %3.0f%%  (%d 天)"
                      % (name, x.iloc[-1], (x < x.iloc[-1]).mean() * 100, len(x)))


if __name__ == "__main__":
    main()
