# -*- coding: utf-8 -*-
"""历史统计打分 → web/hist_stats.js

三维并列，不合成单一总分：
  技术  —— 跌到哪一步（回撤 / MA250 偏离 / 60 日动量 / RSI）
  基本面 —— 贵不贵（PE / PB 历史分位）
  情绪   —— 冷清还是拥挤（换手 / 成交占比 / 两融变化）

所有维度统一朝向：**分数越高 = 历史上越极端（跌得越深 / 越便宜 / 越冷清）**。
另外给每个资产 5 / 20 / 60 日的"同档胜率"（回撤 ±7.5pp 的历史条件分布），
带无条件基准和独立片段数。

指数 8 个，申万一级 31 个，分两张表。
用法：python3 src/build_hist_stats.py
"""
import os
import sys
import glob
import json

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import INDEX_CSV, CACHE_DIR, DATA_DIR  # noqa: E402
try:
    from build_web_data import INDEX_CYCLES  # 与复盘页统一牛熊口径
except Exception:
    INDEX_CYCLES = {}

OUT = os.path.join(ROOT, "web", "hist_stats.js")
SW_DIR = os.path.join(DATA_DIR, "ml_data", "sw_daily")

IDX = ["上证指数", "深证成指", "沪深300", "中证500",
       "中证1000", "中证2000", "创业板指", "科创50"]
IDX_DESC = {
    "上证指数": "沪市全样本 · 大盘价值", "深证成指": "深市核心 · 成长",
    "沪深300": "大盘蓝筹 · 国家队主战场", "中证500": "中盘",
    "中证1000": "小盘 · 高波动", "中证2000": "微盘",
    "创业板指": "成长 · 高 beta", "科创50": "硬科技 · 高 beta",
}
BUCKET = 0.075          # 同档：回撤幅度 ±7.5pp
HORIZONS = [5, 20, 60]
MIN_HIST = 400          # 历史样本少于这么多天就不打分
THR = 0.20
MIN_BEAR = 60


# ---------------------------------------------------------------- 工具
def pct_of(s, v, min_n=None):
    s = s.dropna()
    if len(s) < (min_n or MIN_HIST) or v is None or not np.isfinite(v):
        return None
    return float((s < v).mean() * 100)


def rsi14(close):
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    au = up.ewm(alpha=1 / 14, adjust=False).mean()
    ad = dn.ewm(alpha=1 / 14, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def episodes(v, thr=THR):
    segs, trend = [], None
    ext_px, ext_i, last_i = v[0], 0, 0
    for i in range(1, len(v)):
        p = v[i]
        if trend is None:
            if p > ext_px * (1 + thr):
                trend = "bull"; segs.append(("bull", last_i, ext_i))
                last_i, ext_px, ext_i = ext_i, p, i
            elif p < ext_px * (1 - thr):
                trend = "bear"; segs.append(("bear", last_i, ext_i))
                last_i, ext_px, ext_i = ext_i, p, i
            elif p > ext_px:
                ext_px, ext_i = p, i
            continue
        if trend == "bull":
            if p > ext_px:
                ext_px, ext_i = p, i
            elif p <= ext_px * (1 - thr):
                segs.append(("bull", last_i, ext_i))
                last_i, ext_px, ext_i = ext_i, p, i
                trend = "bear"
        else:
            if p < ext_px:
                ext_px, ext_i = p, i
            elif p >= ext_px * (1 + thr):
                segs.append(("bear", last_i, ext_i))
                last_i, ext_px, ext_i = ext_i, p, i
                trend = "bull"
    segs.append((trend or "bull", last_i, len(v) - 1))
    return segs


def feat_matrix(s, amount=None):
    """9 个特征，各自转成自身历史的百分位，用于算相似度。"""
    sr = s.astype(float)
    lr = np.log(sr).diff()
    ma60 = sr.rolling(60, min_periods=20).mean()
    ma250 = sr.rolling(250, min_periods=60).mean()
    roll_max = sr.rolling(250, min_periods=60).max()
    roll_min = sr.rolling(250, min_periods=60).min()
    f = pd.DataFrame(index=sr.index)
    f["mom20"] = sr / sr.shift(20) - 1
    f["mom60"] = sr / sr.shift(60) - 1
    f["mom120"] = sr / sr.shift(120) - 1
    f["ma60"] = sr / ma60 - 1
    f["ma250"] = sr / ma250 - 1
    f["dd250"] = sr / roll_max - 1
    f["pos250"] = (sr - roll_min) / (roll_max - roll_min)
    f["vol20"] = lr.rolling(20).std() * np.sqrt(244)
    f["rsi"] = rsi14(sr)
    if amount is not None:
        a = amount.astype(float)
        f["vr20"] = a / a.rolling(20).mean()
    # 滚动 5 年分位（0-100）：只用当日及之前的数据，避免用到未来
    r = f.rolling(750, min_periods=250).rank(pct=True) * 100
    return r


def similar_bucket(s, feats, h):
    """按多特征分位欧氏距离找最多 30 个相似日，彼此隔离 max(20,h) 个交易日。"""
    v = s.values
    X = feats.copy()
    X["y"] = v
    X = X.dropna()
    if len(X) < MIN_HIST:
        return None
    cur = X.iloc[-1]
    cols = [c for c in X.columns if c != "y"]
    dist = ((X[cols] - cur[cols]) ** 2).mean(axis=1) ** 0.5
    pos = np.arange(len(X))
    order = np.argsort(dist.values)
    gap = max(20, h)
    picked = []
    for i in order:
        if i >= len(X) - h:          # 没有完整前瞻
            continue
        if picked and min(abs(pos[i] - j) for j in picked) < gap:
            continue
        picked.append(int(i))
        if len(picked) >= 30:
            break
    if len(picked) < 10:
        return {"ok": False, "n": len(picked)}
    yv = X["y"].values
    fwd = np.array([yv[i + h] / yv[i] - 1 for i in picked])
    allfwd = np.array([yv[i + h] / yv[i] - 1 for i in range(len(X) - h)])
    eps = episodes(v)
    # 相似日落在第几段 20% 熊市里（用于数独立片段）
    segs = set()
    for i in picked:
        sid = "x%d" % (i // gap)
        for k, (kind, a, b) in enumerate(eps):
            if a <= i <= b:
                sid = k
                break
        segs.add(sid)
    return dict(ok=True, n=int(len(fwd)), seg=int(len(segs)),
                win=round(float((fwd > 0).mean() * 100), 1),
                base=round(float((allfwd > 0).mean() * 100), 1),
                med=round(float(np.median(fwd) * 100), 1),
                p25=round(float(np.percentile(fwd, 25) * 100), 1),
                p75=round(float(np.percentile(fwd, 75) * 100), 1))


def score_of(items):
    """items: [(名字, 原始值, 分位, 方向, 单位)]。

    orient='low'  → 分位越低越极端，得分 = 100 - 分位（回撤、估值、换手）
    orient='high' → 分位越高越好，得分 = 分位（ROE、增速）
    detail 里同时保留原始值，供展开时显示。
    """
    vals, detail = [], {}
    for name, raw, p, orient, unit in items:
        if p is None:
            detail[name] = dict(s=None, v=None if raw is None else round(float(raw), 2), u=unit)
            continue
        sc = (100 - p) if orient == "low" else p
        detail[name] = dict(s=round(sc), v=None if raw is None else round(float(raw), 2), u=unit)
        vals.append(sc)
    if not vals:
        return None, detail
    return round(float(np.mean(vals))), detail


def tendency(tech, fund, w60):
    if tech is None:
        return "—"
    if (tech >= 60 and (fund is None or fund >= 50) and w60 and w60.get("ok")
            and w60["win"] >= 55 and w60.get("seg", 0) >= 10):
        return "偏买入"
    if tech <= 35 and (fund is None or fund <= 35):
        return "偏减仓"
    return "观察"


def load_fund():
    """build_fundamentals.py 产出的季度/月度基本面。"""
    fp = os.path.join(CACHE_DIR, "fund_panel.parquet")
    if not os.path.exists(fp):
        return {}, {}
    d = pd.read_parquet(fp)
    idx = {n: g.sort_values("end_date") for n, g in d[d["asset_type"] == "index"].groupby("name")}
    sec = {c: g.sort_values("end_date") for c, g in d[d["asset_type"] == "sector"].groupby("code")}
    return idx, sec


FUND_IDX, FUND_SEC = load_fund()


def fund_items_of(f):
    """估值看 PE/PB，质量看 ROE/毛利率/现金流，收益看增速/股息率。"""
    out = []
    if f is None or len(f) < 12:
        return out
    spec = [
        ("roe", "ROE", "high", "%"),
        ("or_yoy", "营收增速", "high", "%"),
        ("grossprofit_margin", "毛利率", "high", "%"),
        ("debt_to_assets", "负债率", "low", "%"),
        ("ocfps", "每股现金流", "high", ""),
        ("dv", "股息率", "high", "%"),
    ]
    for col, key, orient, unit in spec:
        if col not in f.columns:
            continue
        ss = pd.to_numeric(f[col], errors="coerce").dropna()
        if len(ss) <= 12:
            continue
        v = ss.iloc[-1]
        out.append((key, v, pct_of(ss, v, min_n=20), orient, unit))
    return out


def load_market_sent():
    """全市场情绪序列：融资买入占比、涨跌停净家数、ETF 份额 20 日变化。"""
    out = {}
    fp = os.path.join(CACHE_DIR, "margin_full.csv")
    mk = os.path.join(CACHE_DIR, "market_daily.parquet")
    if os.path.exists(fp) and os.path.exists(mk):
        m = pd.read_csv(fp, parse_dates=["trade_date"])
        rz = m.groupby("trade_date")["rzmre"].sum()
        bal = m.groupby("trade_date")["rzye"].sum().sort_index()
        out["两融20日"] = bal.pct_change(20) * 100
        md = pd.read_parquet(mk, columns=["date", "amount"])
        md["date"] = pd.to_datetime(md["date"])
        amt = md.set_index("date")["amount"]
        out["融资买入占比"] = ((rz / amt.reindex(rz.index)).replace([np.inf, -np.inf], np.nan) * 100)
    fp = os.path.join(CACHE_DIR, "limit_daily.csv")
    if os.path.exists(fp):
        l = pd.read_csv(fp, parse_dates=["trade_date"]).set_index("trade_date")
        out["涨跌停净"] = (l["limit_up_n"] - l["limit_down_n"]).astype(float)
    fp = os.path.join(CACHE_DIR, "nsf_flow.csv")
    if os.path.exists(fp):
        n = pd.read_csv(fp, parse_dates=["trade_date"]).set_index("trade_date")
        out["国家队20日"] = pd.to_numeric(n["pct_aum"], errors="coerce")
    return out


MSENT = load_market_sent()
MSENT_UNIT = {"融资买入占比": "%", "涨跌停净": "家", "国家队20日": "%", "两融20日": "%"}
# 国家队越买越偏多（high），其余越高越拥挤（low）
MSENT_ORIENT = {"国家队20日": "high"}


def tech_items_of(s, vol):
    """技术面 9 项：趋势、位置、量价、动量。方向统一为「越低越极端 = 分越高」。"""
    sr = s.astype(float)
    lr = np.log(sr).diff()
    roll_max = sr.rolling(250, min_periods=60).max()
    roll_min = sr.rolling(250, min_periods=60).min()
    ma250 = sr / sr.rolling(250, min_periods=60).mean() - 1
    dd250 = sr / roll_max - 1
    low_d = sr / roll_min - 1
    pos = (sr - roll_min) / (roll_max - roll_min) * 100
    mom60 = sr / sr.shift(60) - 1
    rsi = rsi14(sr)
    v = vol.reindex(sr.index).astype(float)
    vr = v / v.rolling(20).mean()
    vpc = lr.rolling(20).corr(v.pct_change())
    ema12 = sr.ewm(span=12, adjust=False).mean()
    ema26 = sr.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) / sr * 100
    spec = [
        ("回撤", dd250, 100, "%"), ("距低点", low_d, 100, "%"),
        ("250日位置", pos, 1, "%"), ("MA250偏离", ma250, 100, "%"),
        ("60日动量", mom60, 100, "%"), ("RSI", rsi, 1, ""),
        ("量比20", vr, 1, ""), ("量价相关", vpc, 1, ""), ("MACD柱", macd, 1, ""),
    ]
    out = []
    for key, ser, scale, unit in spec:
        ss = ser.dropna()
        if not len(ss):
            out.append((key, None, None, "low", unit))
            continue
        val = float(ss.iloc[-1]) * scale
        out.append((key, val, pct_of(ss, ss.iloc[-1]), "low", unit))
    return out


def build_indices():
    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    val = None
    fp = os.path.join(CACHE_DIR, "index_dailybasic.csv")
    if os.path.exists(fp):
        val = pd.read_csv(fp, parse_dates=["trade_date"])

    rows = []
    for name in IDX:
        if name not in px.columns:
            continue
        s = px[name].replace(0.0, np.nan).dropna()
        if len(s) < MIN_HIST:
            continue
        v = s.values
        eps = episodes(v)
        k, i0, i1 = eps[-1]
        # 与复盘页统一：用官方 INDEX_CYCLES 的当前段覆盖 ZigZag（避免同一指数在一处显示"牛"、另一处"熊"）
        _oc = INDEX_CYCLES.get(name)
        if _oc:
            _t, _a, _b = _oc[-1][:3]
            if _t in ("bull", "bear") and _a:
                _pos = int(s.index.searchsorted(pd.Timestamp(_a)))
                if 0 <= _pos < len(s) - 1:
                    k, i0, i1 = _t, _pos, len(s) - 1
        cur_days = i1 - i0
        chg = v[i1] / v[i0] - 1

        dd250 = s / s.rolling(250, min_periods=60).max() - 1
        g = val[val["name"] == name].sort_values("trade_date") if val is not None else None
        turn = None
        if g is not None and len(g) and "turnover_rate" in g.columns:
            turn = pd.to_numeric(g["turnover_rate"], errors="coerce")
            turn.index = pd.to_datetime(g["trade_date"])
            turn = turn.reindex(s.index).ffill()

        tech_items = tech_items_of(s, turn if turn is not None else pd.Series(1.0, index=s.index))

        # 基本面：估值 2 项 + 财务 6 项
        fund_items = []
        if g is not None and len(g):
            last = g.iloc[-1]
            for col, key in (("pe_ttm", "PE"), ("pb", "PB")):
                if col in g.columns and pd.notna(last.get(col)):
                    fund_items.append((key, last[col], pct_of(g[col], last[col]), "low", ""))
        fund_items = fund_items + fund_items_of(FUND_IDX.get(name))

        # 情绪：换手 + 全市场 4 项
        sent_items = []
        if turn is not None and turn.notna().any():
            tv = turn.dropna().iloc[-1]
            sent_items.append(("换手", tv, pct_of(turn, tv), "low", "%"))
        for key, ser in MSENT.items():
            ss = ser.dropna()
            if len(ss) > 60:
                sv = ss.iloc[-1]
                sent_items.append((key, sv, pct_of(ss, sv),
                                   MSENT_ORIENT.get(key, "low"), MSENT_UNIT.get(key, "")))

        tech, tech_d = score_of(tech_items)
        fund, fund_d = score_of(fund_items)
        sent, sent_d = score_of(sent_items)

        feats = feat_matrix(s)
        win = {("d%d" % h): similar_bucket(s, feats, h) for h in HORIZONS}
        w60 = win.get("d60")

        rows.append(dict(
            name=name, desc=IDX_DESC.get(name, ""), kind=k,
            price=round(float(v[i1]), 1),
            days=int(cur_days), chg=round(float(chg) * 100, 1),
            dd250=round(float(dd250.iloc[-1]) * 100, 1),
            tech=tech, fund=fund, sent=sent,
            tech_items=tech_d, fund_items=fund_d, sent_items=sent_d,
            win=win, tendency=tendency(tech, fund, w60),
        ))
    return rows



    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    val = None
    fp = os.path.join(CACHE_DIR, "index_dailybasic.csv")
    if os.path.exists(fp):
        val = pd.read_csv(fp, parse_dates=["trade_date"])
    margin = None
    fp = os.path.join(CACHE_DIR, "margin_full.csv")
    if os.path.exists(fp):
        m = pd.read_csv(fp, parse_dates=["trade_date"])
        margin = m.groupby("trade_date")["rzye"].sum().sort_index().pct_change(20) * 100

    rows = []
    for name in IDX:
        if name not in px.columns:
            continue
        s = px[name].replace(0.0, np.nan).dropna()
        if len(s) < MIN_HIST:
            continue
        v = s.values
        eps = episodes(v)
        k, i0, i1 = eps[-1]
        # 与复盘页统一：用官方 INDEX_CYCLES 的当前段覆盖 ZigZag（避免同一指数在一处显示"牛"、另一处"熊"）
        _oc = INDEX_CYCLES.get(name)
        if _oc:
            _t, _a, _b = _oc[-1][:3]
            if _t in ("bull", "bear") and _a:
                _pos = int(s.index.searchsorted(pd.Timestamp(_a)))
                if 0 <= _pos < len(s) - 1:
                    k, i0, i1 = _t, _pos, len(s) - 1
        cur_days = i1 - i0
        chg = v[i1] / v[i0] - 1

        dd250 = s / s.rolling(250, min_periods=60).max() - 1
        ma250 = s / s.rolling(250, min_periods=60).mean() - 1
        mom60 = s / s.shift(60) - 1
        rsi = rsi14(s)

        # 技术
        tech_items = tech_items_of(s, amt)
        # 基本面
        fund_items = []
        if val is not None:
            g = val[val["name"] == name].sort_values("trade_date")
            if len(g):
                last = g.iloc[-1]
                for col, key in (("pe_ttm", "PE"), ("pb", "PB")):
                    if col in g.columns and pd.notna(last.get(col)):
                        fund_items.append((key, last[col], pct_of(g[col], last[col]), "low", ""))
        fund_items = fund_items + fund_items_of(FUND_IDX.get(name))
        # 情绪
        sent_items = []
        if val is not None:
            g = val[val["name"] == name].sort_values("trade_date")
            if len(g) and "turnover_rate" in g.columns and pd.notna(g["turnover_rate"].iloc[-1]):
                tv = g["turnover_rate"].iloc[-1]
                sent_items.append(("换手", tv, pct_of(g["turnover_rate"], tv), "low", "%"))
        if margin is not None and len(margin.dropna()):
            mv = margin.iloc[-1]
            sent_items.append(("两融20日", mv, pct_of(margin, mv), "low", "%"))

        tech, tech_d = score_of(tech_items)
        fund, fund_d = score_of(fund_items)
        sent, sent_d = score_of(sent_items)

        feats = feat_matrix(s)
        win = {("d%d" % h): similar_bucket(s, feats, h) for h in HORIZONS}
        w60 = win.get("d60")

        rows.append(dict(
            name=name, desc=IDX_DESC.get(name, ""), kind=k,
            price=round(float(v[i1]), 1),
            days=int(cur_days), chg=round(float(chg) * 100, 1),
            dd250=round(float(dd250.iloc[-1]) * 100, 1),
            tech=tech, fund=fund, sent=sent,
            tech_items=tech_d, fund_items=fund_d, sent_items=sent_d,
            win=win, tendency=tendency(tech, fund, w60),
        ))
    return rows


# ---------------------------------------------------------------- 板块
def load_sectors():
    fs = sorted(__import__("glob").glob(os.path.join(SW_DIR, "*.parquet")))
    frames = []
    for f in fs:
        try:
            frames.append(pd.read_parquet(f, columns=[
                "ts_code", "trade_date", "name", "close", "pe", "pb", "amount", "total_mv"]))
        except Exception:
            continue
    if not frames:
        return {}
    d = pd.concat(frames, ignore_index=True)
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str))
    d = d.drop_duplicates(["ts_code", "trade_date"]).sort_values(["ts_code", "trade_date"])
    # 801020 采掘 2021 年已废止，换成 801950 煤炭
    out = {}
    for code, g in d.groupby("ts_code"):
        if g["trade_date"].max() < pd.Timestamp("2026-06-01"):
            continue
        out[code] = g
    # 成交占比：每个行业占全部 31 个行业成交额的比例
    amt = {}
    for code, g in out.items():
        a = pd.to_numeric(g["amount"], errors="coerce")
        a.index = g["trade_date"].values
        amt[code] = a
    adf = pd.DataFrame(amt)
    tot = adf.sum(axis=1, min_count=1)
    shares = adf.div(tot.replace(0, np.nan), axis=0)
    return out, shares


def build_sectors():
    loaded = load_sectors()
    if not loaded:
        return []
    secs, shares = loaded
    rows = []
    for code, g in sorted(secs.items()):
        s = pd.to_numeric(g["close"], errors="coerce")
        s.index = g["trade_date"].values
        s = s.dropna()
        if len(s) < MIN_HIST:
            continue
        v = s.values
        eps = episodes(v)
        k, i0, i1 = eps[-1]
        chg = v[i1] / v[i0] - 1

        dd250 = s / s.rolling(250, min_periods=60).max() - 1
        ma250 = s / s.rolling(250, min_periods=60).mean() - 1
        mom60 = s / s.shift(60) - 1
        rsi = rsi14(s)

        pe = pd.to_numeric(g["pe"], errors="coerce"); pe.index = s.index
        pb = pd.to_numeric(g["pb"], errors="coerce"); pb.index = s.index
        amt = pd.to_numeric(g["amount"], errors="coerce"); amt.index = s.index
        mv = pd.to_numeric(g["total_mv"], errors="coerce"); mv.index = s.index
        turn = (amt / mv).replace([np.inf, -np.inf], np.nan)

        tech_items = tech_items_of(s, amt)
        fund_items = [
            ("PE", pe.iloc[-1] if pe.notna().any() else None,
             pct_of(pe, pe.iloc[-1]) if pe.notna().any() else None, "low", ""),
            ("PB", pb.iloc[-1] if pb.notna().any() else None,
             pct_of(pb, pb.iloc[-1]) if pb.notna().any() else None, "low", ""),
        ]
        fund_items += fund_items_of(FUND_SEC.get(code))
        sent_items = [("换手", turn.iloc[-1] * 100 if turn.notna().any() else None,
                       pct_of(turn, turn.iloc[-1]) if turn.notna().any() else None, "low", "%")]
        # 成交额占全部板块的比重（拥挤度）及其 20 日变化
        if code in shares.columns:
            sh = shares[code].dropna()
            if len(sh) > MIN_HIST:
                sent_items.append(("成交占比", sh.iloc[-1] * 100, pct_of(sh, sh.iloc[-1]), "low", "%"))
                dsh = (sh / sh.rolling(20).mean() - 1).dropna()
                if len(dsh) > 60:
                    sent_items.append(("成交占比20日", dsh.iloc[-1] * 100,
                                       pct_of(dsh, dsh.iloc[-1]), "low", "%"))

        tech, tech_d = score_of(tech_items)
        fund, fund_d = score_of(fund_items)
        sent, sent_d = score_of(sent_items)
        feats = feat_matrix(s, amount=amt)
        win = {("d%d" % h): similar_bucket(s, feats, h) for h in HORIZONS}
        w60 = win.get("d60")

        rows.append(dict(
            name=str(g["name"].iloc[-1]), code=code, kind=k,
            days=int(i1 - i0), chg=round(float(chg) * 100, 1),
            dd250=round(float(dd250.iloc[-1]) * 100, 1),
            tech=tech, fund=fund, sent=sent,
            tech_items=tech_d, fund_items=fund_d, sent_items=sent_d,
            win=win, tendency=tendency(tech, fund, w60),
        ))
    rows.sort(key=lambda r: -(r["tech"] if r["tech"] is not None else -1))
    return rows


def main():
    idx = build_indices()
    sec = build_sectors()
    asof = pd.read_csv(INDEX_CSV, usecols=["date"])["date"].max()
    payload = dict(
        asof=str(asof)[:10],
        indices=idx, sectors=sec,
        meta=dict(bucket=BUCKET, horizons=HORIZONS, min_hist=MIN_HIST),
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_hist_stats.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.hist_stats=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print("指数 %d 个 / 板块 %d 个 → %s" % (len(idx), len(sec), OUT))
    for r in idx:
        print("  %-6s 阶段%-3s 技术%4s 基本面%4s 情绪%4s 60日%s %s" % (
            r["name"], "熊" if r["kind"] == "bear" else "牛",
            r["tech"], r["fund"], r["sent"],
            ("%.0f%%" % r["win"]["d60"]["win"]) if r["win"]["d60"] and r["win"]["d60"].get("ok") else "—",
            r["tendency"]))


if __name__ == "__main__":
    main()
