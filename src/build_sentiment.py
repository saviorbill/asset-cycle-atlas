# -*- coding: utf-8 -*-
"""情绪框架 → web/sentiment.js

目标：用情绪指标判断未来 3–6 个月（60 / 120 个交易日）的表现。

情绪分（0–100，越高越热）由 5 个「贪婪/活跃」指标合成：
    成交额/总市值、换手率、上涨家数占比、两融余额/总市值、涨停家数
恐慌类指标（50ETF/300ETF 隐含波动率）单独列出，不混进合成分。

所有指标用**滚动 5 年分位**（只用当日及之前的数据），避免用到未来。
评估用沪深300 的未来 60 / 120 日收益，按情绪五分位分组，并给出独立片段数。
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import CACHE_DIR, INDEX_CSV, DATA_DIR  # noqa: E402

OUT = os.path.join(ROOT, "web", "sentiment.js")
HORIZONS = [60, 120]
WIN = 1250          # 滚动 5 年
MIN_PER = 250


def load_market():
    m = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    m["date"] = pd.to_datetime(m["date"])
    pre = os.path.join(CACHE_DIR, "market_daily_pre2016.parquet")
    if os.path.exists(pre):
        p = pd.read_parquet(pre)
        p["date"] = pd.to_datetime(p["date"])
        p["total_mv"] = pd.to_numeric(p["total_mv"], errors="coerce") / 1e4
        keep = [c for c in m.columns if c in p.columns]
        m = pd.concat([p[keep], m], ignore_index=True).drop_duplicates("date")
    return m.sort_values("date").set_index("date")


def build_indicators():
    m = load_market()
    out = pd.DataFrame(index=m.index)
    out["成交额/总市值"] = (m["amount"] / (m["total_mv"] * 1e4) * 100)
    out["换手率"] = m["turnover_median"]
    out["上涨占比"] = m["up_ratio"].rolling(20, min_periods=10).mean() * 100

    fp = os.path.join(CACHE_DIR, "margin_full.csv")
    if os.path.exists(fp):
        mg = pd.read_csv(fp, parse_dates=["trade_date"])
        rz = mg.groupby("trade_date")["rzye"].sum()
        out["两融/总市值"] = (rz / (m["total_mv"] * 1e4) * 100).reindex(out.index)

    fp = os.path.join(CACHE_DIR, "limit_daily.csv")
    if os.path.exists(fp):
        lm = pd.read_csv(fp, parse_dates=["trade_date"]).set_index("trade_date")
        out["涨停家数"] = lm["limit_up_n"].rolling(20, min_periods=10).mean().reindex(out.index)

    fp = os.path.join(CACHE_DIR, "iv_index.parquet")
    if os.path.exists(fp):
        iv = pd.read_parquet(fp)
        iv["date"] = pd.to_datetime(iv["date"])
        out["隐含波动率"] = iv.set_index("date")["iv_avg"].reindex(out.index)
    return out


def pct_rank(df):
    """滚动 5 年分位（0–1），只用当日及之前的数据。"""
    return df.rolling(WIN, min_periods=MIN_PER).rank(pct=True)


def fwd_ret(s, h):
    return s.shift(-h) / s - 1


def evaluate(score, px, h):
    d = pd.DataFrame({"score": score, "fwd": fwd_ret(px, h)}).dropna()
    if len(d) < 500:
        return None
    d["q"] = pd.qcut(d["score"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    rows = []
    for q, g in d.groupby("q", observed=True):
        # 独立片段：按 h 天切块，避免同一段行情被反复计数
        seg = len(set((g.index - d.index[0]).days // (h * 1.45)))
        rows.append(dict(q=int(q), n=len(g), seg=seg,
                         mean=round(float(g["fwd"].mean()) * 100, 2),
                         med=round(float(g["fwd"].median()) * 100, 2),
                         win=round(float((g["fwd"] > 0).mean()) * 100, 1)))
    ic = float(d["score"].rank().corr(d["fwd"].rank()))
    hi = d[d["score"] >= 80]
    lo = d[d["score"] <= 20]
    return dict(quintiles=rows, ic=round(ic, 3), n=int(len(d)),
                high=dict(n=len(hi), mean=round(float(hi["fwd"].mean()) * 100, 2),
                          win=round(float((hi["fwd"] > 0).mean()) * 100, 1)) if len(hi) else None,
                low=dict(n=len(lo), mean=round(float(lo["fwd"].mean()) * 100, 2),
                         win=round(float((lo["fwd"] > 0).mean()) * 100, 1)) if len(lo) else None)


def main():
    ind = build_indicators()
    print("指标：%s" % "、".join(ind.columns))
    print("有效区间：%s ~ %s" % (ind.dropna(how="all").index.min().date(),
                              ind.dropna(how="all").index.max().date()))

    greed_cols = [c for c in ["成交额/总市值", "换手率", "上涨占比", "两融/总市值", "涨停家数"]
                  if c in ind.columns]
    pr = pct_rank(ind[greed_cols])
    score = pr.mean(axis=1, skipna=True) * 100
    score = score[score.notna()]
    print("情绪分有效天数：%d（%s ~ %s）" % (len(score), score.index[0].date(), score.index[-1].date()))

    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date")["沪深300"].dropna()
    px = px[px > 0]

    ev = {}
    for h in HORIZONS:
        r = evaluate(score, px, h)
        ev[h] = r
        if not r:
            continue
        print("\n未来 %d 个交易日（IC %.3f，n=%d）" % (h, r["ic"], r["n"]))
        print("  情绪分位  n    平均     中位    胜率")
        for q in r["quintiles"]:
            print("  Q%d       %4d  %+6.2f%%  %+6.2f%%  %4.1f%%  (%d 段)" %
                  (q["q"], q["n"], q["mean"], q["med"], q["win"], q["seg"]))
        if r["high"]:
            print("  情绪≥80: 平均 %+6.2f%%  胜率 %.0f%%  n=%d" %
                  (r["high"]["mean"], r["high"]["win"], r["high"]["n"]))
        if r["low"]:
            print("  情绪≤20: 平均 %+6.2f%%  胜率 %.0f%%  n=%d" %
                  (r["low"]["mean"], r["low"]["win"], r["low"]["n"]))

    # 分时代看稳定性
    eras = [("2005–2015", "2005-01-01", "2015-12-31"), ("2016–2026", "2016-01-01", "2026-12-31")]
    era_stats = {}
    for name, a, b in eras:
        s = score[(score.index >= a) & (score.index <= b)]
        for h in HORIZONS:
            r = evaluate(s, px, h)
            era_stats["%s_%d" % (name, h)] = (dict(ic=r["ic"], n=r["n"],
                                                  high=r["high"], low=r["low"]) if r else None)
    print("\n分时代 IC：")
    for k, v in era_stats.items():
        if v:
            hi = v.get("high") or {}
            lo = v.get("low") or {}
            print("  %-14s IC %+.3f  n=%d | 高情绪 %s 低情绪 %s" % (
                k, v["ic"], v["n"],
                ("%+.1f%%/%.0f%%/n%d" % (hi.get("mean", 0), hi.get("win", 0), hi.get("n", 0))) if hi else "-",
                ("%+.1f%%/%.0f%%/n%d" % (lo.get("mean", 0), lo.get("win", 0), lo.get("n", 0))) if lo else "-"))

    cur = float(score.iloc[-1])
    hist = score[score <= cur]
    payload = dict(
        asof=score.index[-1].strftime("%Y-%m-%d"),
        dates=[d.strftime("%Y-%m-%d") for d in score.index],
        score=[round(float(x), 1) for x in score.values],
        components={c: [None if pd.isna(x) else round(float(x) * 100, 1) for x in pr[c].values]
                    for c in greed_cols},
        current=dict(score=round(cur, 1), pct=round(float(len(hist) / len(score) * 100), 1)),
        eval=ev,
        era=era_stats,
        horizons=HORIZONS,
        cols=greed_cols,
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_sentiment.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.sentiment=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print("\n当前情绪分 %.1f（历史 %.0f%% 分位）→ %s" %
          (cur, len(hist) / len(score) * 100, OUT))


if __name__ == "__main__":
    main()
