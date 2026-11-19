# -*- coding: utf-8 -*-
"""A 股版 VIX：用 50ETF / 300ETF 期权反解近月平值隐含波动率。

输出：应用数据/cache/iv_index.parquet
    date, iv50, iv300, iv_avg, realized20

口径：
  - 取剩余期限 ≥7 天的最近一个到期月。
  - 用看涨看跌平价 C-P = e^{-rT}(F-K) 反推远期 F，避免依赖 ETF 收盘价。
  - 在行权价最接近 F 的合约上，用 Black-76 对看涨看跌平均价反解 σ（二分法）。
  - 无风险利率固定 2%（对平值期权影响很小）。

已知局限：
  - 只有 50ETF/300ETF 两个标的，2015-02 起，覆盖不到小盘股的波动。
  - 近月合约在到期日前几天流动性差、价格噪声大，所以要求 ≥7 天。
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import DATA_DIR, CACHE_DIR  # noqa: E402

OUT = os.path.join(CACHE_DIR, "iv_index.parquet")
BASIC = os.path.join(DATA_DIR, "ml_data", "opt_basic", "opt_basic_all.parquet")
DAILY_DIR = os.path.join(DATA_DIR, "ml_data", "opt_daily")
UNDERLYINGS = {"OP510050.SH": "iv50", "OP510300.SH": "iv300"}
R = 0.02
MIN_DAYS = 7


import math


def norm_cdf(x):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(x, dtype=float) / np.sqrt(2)))


def black76(F, K, T, sigma):
    """折现前（forward）价格，返回看涨、看跌。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        call = F * norm_cdf(d1) - K * norm_cdf(d2)
        put = K * norm_cdf(-d2) - F * norm_cdf(-d1)
    return call, put


def implied_vol(price, F, K, T, is_call):
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        c, p = black76(F, K, T, mid)
        v = c if is_call else p
        if v > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def load_options():
    b = pd.read_parquet(BASIC)
    b = b[["ts_code", "opt_code", "call_put", "exercise_price", "maturity_date"]]
    b = b[b["opt_code"].isin(UNDERLYINGS)]
    b["maturity_date"] = pd.to_datetime(b["maturity_date"].astype(str), errors="coerce")
    fs = sorted(glob.glob(os.path.join(DAILY_DIR, "*.parquet")))
    frames = []
    for f in fs:
        frames.append(pd.read_parquet(f, columns=["ts_code", "trade_date", "close", "vol"]))
    d = pd.concat(frames, ignore_index=True)
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str), errors="coerce")
    d = d.merge(b, on="ts_code", how="inner")
    d = d[(d["close"] > 0) & (d["vol"] > 0)]
    return d


def main():
    d = load_options()
    print("合约日线 %d 行，%s ~ %s" % (len(d), d.trade_date.min().date(), d.trade_date.max().date()))
    rows = []
    T30 = 30 / 365.25
    for (date, ocode), g in d.groupby(["trade_date", "opt_code"]):
        days = (g["maturity_date"] - date).dt.days
        alive = g[days >= MIN_DAYS]
        if alive.empty:
            continue
        exps = sorted(alive["maturity_date"].unique())[:2]
        pts = []          # [(T, iv)]
        for expiry in exps:
            m = alive[alive["maturity_date"] == expiry]
            piv = m.pivot_table(index="exercise_price", columns="call_put",
                                values="close", aggfunc="last")
            if "C" not in piv.columns or "P" not in piv.columns:
                continue
            piv = piv.dropna()
            if len(piv) < 3:
                continue
            T = max((expiry - date).days, 1) / 365.25
            K = piv.index.values.astype(float)
            c, p = piv["C"].values.astype(float), piv["P"].values.astype(float)
            # 平价反推远期：F = K + e^{rT}(C - P)
            F = float(np.median(K + np.exp(R * T) * (c - p)))
            if not np.isfinite(F) or F <= 0:
                continue
            j = int(np.argmin(np.abs(K - F)))
            iv = implied_vol((c[j] + p[j]) / 2 * np.exp(R * T), F, K[j], T, True)
            if 0.01 < iv < 2.0:
                pts.append((T, iv))
        if not pts:
            continue
        if len(pts) == 1 or pts[0][0] >= T30:
            iv30 = pts[0][1]
        else:
            (T1, v1), (T2, v2) = pts[0], pts[1]
            if T2 <= T1:
                iv30 = v1
            else:
                w = min(max((T2 - T30) / (T2 - T1), 0.0), 1.0)
                var = w * v1 ** 2 * T1 + (1 - w) * v2 ** 2 * T2
                iv30 = float(np.sqrt(max(var, 1e-8) / T30))
        rows.append(dict(date=date, code=UNDERLYINGS[ocode], iv=iv30))

    iv = pd.DataFrame(rows)
    if iv.empty:
        print("没有算出 IV")
        return
    wide = iv.pivot_table(index="date", columns="code", values="iv", aggfunc="last")
    wide = wide.sort_index()
    wide["iv_avg"] = wide.mean(axis=1)
    # 20 日已实现波动（用 300ETF 期权标的的近似：这里留给下游自己算，先占位）
    wide["realized20"] = np.nan
    os.makedirs(CACHE_DIR, exist_ok=True)
    wide.reset_index().to_parquet(OUT, index=False)
    print("落盘 %d 个交易日 → %s" % (len(wide), OUT))
    last = wide.dropna(how="all").iloc[-1]
    print("最新：50ETF IV %.1f%% / 300ETF IV %.1f%%" %
          (last.get("iv50", np.nan) * 100, last.get("iv300", np.nan) * 100))
    print("分位：300ETF IV 全历史 %.0f%% 分位" %
          ((wide["iv300"].dropna() < last.get("iv300")).mean() * 100))


if __name__ == "__main__":
    main()
