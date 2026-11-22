# -*- coding: utf-8 -*-
"""为「Where are we?」网站准备数据 web/data.js。

包含：主图指数(上证/沪深300/创业板, 2005起周线)、5轮牛熊周期分段+4阶段文案、
指标序列(融资/成交额/集中度/PE/换手/广度/涨停)、当前观察最近价格与历史相似度。
"""
import os, sys, json, glob
import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SRC)
sys.path.insert(0, SRC)
sys.path.insert(0, PROJ)
from config import (INDEX_CSV, INDEX_KLINE_DIR, CACHE_DIR, MARGIN_CSV,
                    LIMIT_CPT_CSV, LIMIT_DAILY_CSV, HK_HOLD_CSV, ADV_MACRO_PATH,
                    OVERSEAS_DIR, GOLD_BRENT_CSV, DATA_DIR)

WEB = os.path.join(PROJ, "web")
os.makedirs(WEB, exist_ok=True)


# ---------- 长周期指数估值/换手（2005 起） ----------
def load_index_history():
    fp = os.path.join(CACHE_DIR, "index_dailybasic.csv")
    if not os.path.exists(fp):
        return {}
    df = pd.read_csv(fp, parse_dates=["trade_date"])
    out = {}
    for name, g in df.groupby("name"):
        proj = g[g["source"].astype(str).str.startswith("ak")] \
            if "source" in g.columns else g.iloc[0:0]
        proj_start = (proj["trade_date"].min().strftime("%Y-%m-%d")
                      if len(proj) else None)
        d = (g.set_index("trade_date").sort_index()
             [["pe_ttm", "pb", "turnover_rate"]].dropna())
        if not len(d):
            continue
        last_d = d.index.max()
        w = d.resample("W-FRI").last().dropna()
        if not len(w):
            continue
        # 周频标签取周五，但最后一周可能只到周三：把它落回真实最后一日
        labels = [min(x, last_d) for x in w.index]
        out[name] = {
            "dates": [x.strftime("%Y-%m-%d") for x in labels],
            "pe": [round(float(v), 2) for v in w["pe_ttm"]],
            "pb": [round(float(v), 2) for v in w["pb"]],
            "turnover": [round(float(v), 3) for v in w["turnover_rate"]],
            "proj_start": proj_start,
        }
    return out



# ---------- 首页 Hero：多资产走势 ----------
def _episodes(v, thr=0.20):
    segs, trend = [], None
    ext_px, ext_i, last_i = v[0], 0, 0
    for i in range(1, len(v)):
        p = v[i]
        if trend is None:
            if p > ext_px * (1 + thr):
                trend = "bull"; segs.append(("bull", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
            elif p < ext_px * (1 - thr):
                trend = "bear"; segs.append(("bear", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
            elif p > ext_px:
                ext_px, ext_i = p, i
            continue
        if trend == "bull":
            if p > ext_px:
                ext_px, ext_i = p, i
            elif p <= ext_px * (1 - thr):
                segs.append(("bull", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i; trend = "bear"
        else:
            if p < ext_px:
                ext_px, ext_i = p, i
            elif p >= ext_px * (1 + thr):
                segs.append(("bear", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i; trend = "bull"
    segs.append((trend or "bull", last_i, len(v) - 1))
    return segs


def _monthly(s):
    """取每月最后一个交易日的收盘价，压缩体积。"""
    m = s.resample("ME").last().dropna()
    return m.index, m.values


def _hero_asset(key, name, s):
    s = s.dropna()
    if len(s) < 200:
        return None
    segs = _episodes(s.values)
    dts, vals = _monthly(s)
    return dict(
        key=key, name=name,
        dates=[d.strftime("%Y-%m-%d") for d in dts],
        vals=[round(float(v), 2) for v in vals],
        segs=[[k, s.index[a].strftime("%Y-%m-%d"), s.index[b].strftime("%Y-%m-%d")]
              for k, a, b in segs],
    )



def _cycle_pairs(s, max_cycles=None):
    """把 20% 分段配对成「牛市起点 → 熊市终点」，每轮从 0 起算。"""
    v = s.values
    eps = _episodes(v)
    pairs, i = [], 0
    while i < len(eps):
        k, i0, i1 = eps[i]
        if k == "bull":
            if i + 1 < len(eps) and eps[i + 1][0] == "bear":
                end = eps[i + 1][2]
                i += 2
            else:
                end = i1
                i += 1
            pairs.append((i0, end))
        else:
            i += 1
    if max_cycles:
        pairs = pairs[-max_cycles:]
    out = []
    for n, (i0, i1) in enumerate(pairs):
        seg = v[i0:i1 + 1]
        if len(seg) < 30:
            continue
        base = seg[0]
        out.append(dict(
            label="%s–%s" % (s.index[i0].strftime("%y"), s.index[i1].strftime("%y")),
            start=s.index[i0].strftime("%Y-%m-%d"),
            end=s.index[i1].strftime("%Y-%m-%d"),
            vals=[round(float(x / base - 1) * 100, 1) for x in seg],
            days=int(len(seg)),
            current=bool(i1 >= len(v) - 5),
        ))
    return out



# 业内标准熊市区间（20% 回撤口径，Yardeni / S&P DJI 口径），(峰, 谷)
US_BEARS = [
    ("1929-09-16", "1932-06-01"), ("1937-03-06", "1938-03-31"),
    ("1938-11-12", "1942-04-28"), ("1946-05-29", "1949-06-13"),
    ("1956-08-06", "1957-10-22"), ("1961-12-12", "1962-06-26"),
    ("1966-02-09", "1966-10-07"), ("1968-11-29", "1970-05-26"),
    ("1973-01-11", "1974-10-03"), ("1976-09-22", "1978-03-01"),
    ("1980-11-28", "1982-08-12"), ("1987-08-25", "1987-12-04"),
    ("1990-07-16", "1990-10-11"), ("2000-03-24", "2002-10-09"),
    ("2007-10-09", "2009-03-09"), ("2020-02-19", "2020-03-23"),
    ("2022-01-03", "2022-10-12"),
]
N225_BEARS = [
    ("1989-12-29", "1992-08-18"), ("1996-06-26", "1998-10-09"),
    ("2000-04-12", "2003-04-28"), ("2007-02-26", "2009-03-10"),
    ("2015-06-24", "2016-06-24"), ("2018-10-02", "2018-12-25"),
    ("2020-01-20", "2020-03-19"), ("2021-09-14", "2022-10-20"),
    ("2024-07-11", "2024-08-05"),
]
# 黄金：世界黄金协会口径（1970 年以来 6 牛 5 熊），只取谷底定周期边界
GOLD_BEARS = [
    ("1975-01-06", "1976-09-30"), ("1980-02-01", "1985-03-29"),
    ("1987-12-14", "1993-03-31"), ("1996-02-02", "1999-09-30"),
    ("2011-09-06", "2015-12-17"), ("2020-08-06", "2022-09-30"),
]


def _standard_cycles(s, bears, max_cycles=8):
    """按业内熊市区间切：每轮 = 上一个谷 → 本个谷（含牛熊两段）。"""
    s = s.dropna()
    if not len(s):
        return []
    first = s.index[0]
    # 第一轮从第一段熊市的峰值起算；否则日经会从 1949 一路连到 1992
    prev = max(first, pd.Timestamp(bears[0][0])) if bears else first
    out = []
    for pk, tr in bears:
        t_pk = pd.Timestamp(pk)
        t_tr = pd.Timestamp(tr)
        if t_tr < first or t_tr > s.index[-1]:
            continue
        start = max(prev, first)
        seg = s[(s.index >= start) & (s.index <= t_tr)]
        if len(seg) < 30:
            prev = t_tr
            continue
        base = float(seg.iloc[0])
        out.append(dict(
            label="%s–%s" % (pd.Timestamp(start).strftime("%y"), t_tr.strftime("%y")),
            start=pd.Timestamp(start).strftime("%Y-%m-%d"),
            end=t_tr.strftime("%Y-%m-%d"),
            vals=[round(float(x / base - 1) * 100, 1) for x in seg.values],
            days=int(len(seg)),
            current=(t_tr == max(pd.Timestamp(x[1]) for x in bears if pd.Timestamp(x[1]) <= s.index[-1])),
        ))
        prev = t_tr
    # 最后一段未走完的牛市也画出来，标为本轮
    if prev < s.index[-1]:
        seg = s[s.index >= prev]
        if len(seg) >= 30:
            base = float(seg.iloc[0])
            out.append(dict(
                label="%s–至今" % pd.Timestamp(prev).strftime("%y"),
                start=pd.Timestamp(prev).strftime("%Y-%m-%d"),
                end=s.index[-1].strftime("%Y-%m-%d"),
                vals=[round(float(x / base - 1) * 100, 1) for x in seg.values],
                days=int(len(seg)), current=True))
            for c in out[:-1]:
                c["current"] = False
    return out[-max_cycles:] if max_cycles else out


def _cycle_stats(cycles):
    if not cycles:
        return None
    yrs = [c["days"] / 244 for c in cycles]
    peaks = [max(c["vals"]) for c in cycles]
    ends = [c["vals"][-1] for c in cycles]
    return dict(n=len(cycles), med_yrs=round(float(np.median(yrs)), 1),
                max_yrs=round(float(max(yrs)), 1),
                med_peak=round(float(np.median(peaks))),
                med_end=round(float(np.median(ends))), max_days=max(c["days"] for c in cycles))


def _canon_cycles(s):
    """A股用规范五轮；指数成立晚于阶段起点的自动跳过。"""
    out, last = [], s.index[-1]
    for cy in CYCLES:
        t0 = pd.Timestamp(cy["start"])
        t1 = pd.Timestamp(cy["end"]) if cy.get("end") else last
        seg = s[(s.index >= t0) & (s.index <= t1)]
        if len(seg) < 30:
            continue
        base = float(seg.iloc[0])
        out.append(dict(
            label=cy["name"], start=t0.strftime("%Y-%m-%d"), end=t1.strftime("%Y-%m-%d"),
            vals=[round(float(x / base - 1) * 100, 1) for x in seg.values],
            days=int(len(seg)), current=(cy.get("id") == "c24now"),
        ))
    return out


def _read_xlsx_index(code):
    fp = os.path.join(OVERSEAS_DIR, "K线导出_%s_日线数据.xlsx" % code)
    if not os.path.exists(fp):
        return None
    d = pd.read_excel(fp)
    dt = pd.to_datetime(d["交易时间"], errors="coerce")
    v = pd.to_numeric(d["收盘价"], errors="coerce")
    s = pd.DataFrame({"d": dt, "v": v}).dropna().sort_values("d").set_index("d")["v"]
    return s


def _read_global(code, start="2009-01-01"):
    fs = sorted(glob.glob(os.path.join(DATA_DIR, "ml_data", "index_global", "*.parquet")))
    if not fs:
        return None
    d = pd.concat([pd.read_parquet(f, columns=["ts_code", "trade_date", "close"]) for f in fs],
                  ignore_index=True)
    d = d[d.ts_code == code]
    if not len(d):
        return None
    d["d"] = pd.to_datetime(d["trade_date"].astype(str))
    s = d.sort_values("d").set_index("d")["close"].astype(float)
    return s[s.index >= start]


def build_cycle_overlay():
    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    out = {}

    a_items = []
    for name in ["沪深300", "中证500", "中证1000", "创业板指"]:
        if name not in px.columns:
            continue
        s = px[name].replace(0.0, np.nan).dropna()
        cyc = _canon_cycles(s)
        if cyc:
            a_items.append(dict(key=name, name=name, cycles=cyc))
    if a_items:
        out["a"] = dict(name="A股", items=a_items)

    us_items = []
    for code, name in [("SPX", "标普500"), ("IXIC", "纳斯达克"), ("DJIA", "道琼斯")]:
        s = _read_xlsx_index(code)
        if s is None:
            continue
        if code == "IXIC":
            s = s[s.index >= "1971-01-01"]
        us_items.append(dict(key=code, name=name, cycles=_standard_cycles(s, US_BEARS)))
    if us_items:
        out["us"] = dict(name="美股", items=us_items)

    # 优先用「指数/」下的日经 K 线（可放长历史），没有再用 index_global（2009 起）
    s = _read_xlsx_index("N225")
    if s is None:
        s = _read_global("N225")
    if s is not None and len(s) > 500:
        out["jp"] = dict(name="日股", items=[dict(key="N225", name="日经225",
                                                  cycles=_standard_cycles(s, N225_BEARS, max_cycles=None))])

    if os.path.exists(GOLD_BRENT_CSV):
        g = pd.read_csv(GOLD_BRENT_CSV, parse_dates=["date"]).set_index("date").sort_index()
        if "gold" in g.columns:
            s = g["gold"].dropna()
            out["cmdty"] = dict(name="商品", items=[dict(key="gold", name="COMEX 黄金",
                                                          cycles=_standard_cycles(s, GOLD_BEARS, max_cycles=None))])
    for cat in out.values():
        for it in cat.get("items", []):
            it["stats"] = _cycle_stats(it.get("cycles"))
    return out


def build_hero():
    out = []
    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    if "沪深300" in px.columns:
        a = _hero_asset("hs300", "沪深300", px["沪深300"].replace(0.0, np.nan))
        if a:
            out.append(a)
    fp = os.path.join(OVERSEAS_DIR, "K线导出_SPX_日线数据.xlsx")
    if os.path.exists(fp):
        d = pd.read_excel(fp)
        dt = pd.to_datetime(d["交易时间"], errors="coerce")
        v = pd.to_numeric(d["收盘价"], errors="coerce")
        s = pd.DataFrame({"d": dt, "v": v}).dropna().sort_values("d").set_index("d")["v"]
        s = s[s.index >= (s.index.max() - pd.DateOffset(years=30))]
        a = _hero_asset("spx", "标普500", s)
        if a:
            out.append(a)
    if os.path.exists(GOLD_BRENT_CSV):
        g = pd.read_csv(GOLD_BRENT_CSV, parse_dates=["date"]).set_index("date").sort_index()
        if "gold" in g.columns:
            a = _hero_asset("gold", "COMEX 黄金", g["gold"].dropna())
            if a:
                out.append(a)
        if "brent" in g.columns:
            a = _hero_asset("brent", "布伦特原油", g["brent"].dropna())
            if a:
                out.append(a)
    return out


# ---------- 指标序列 ----------
def load_indicators():
    m = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    m["date"] = pd.to_datetime(m["date"])
    # 2005–2015 由「前复权」逐股 CSV 重建（build_market_agg_pre2016.py）
    pre_fp = os.path.join(CACHE_DIR, "market_daily_pre2016.parquet")
    if os.path.exists(pre_fp):
        p = pd.read_parquet(pre_fp)
        p["date"] = pd.to_datetime(p["date"])
        p["total_mv"] = pd.to_numeric(p["total_mv"], errors="coerce") / 1e4   # 元 → 万元
        keep = [c for c in m.columns if c in p.columns]
        m = pd.concat([p[keep], m], ignore_index=True)
        m = m.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        print("  并入 2005–2015：%d 天" % len(p))
    else:
        print("  未找到 2005–2015 重建文件，指标仍从 2016 起")
    m = m.sort_values("date").reset_index(drop=True)

    from margin_quality import filter_complete_margin
    mg = pd.read_csv(MARGIN_CSV, usecols=["trade_date", "exchange_id", "rzye"])
    # 上游可能先发布单交易所记录；残缺的日期不能合计成全市场融资余额。
    mg = filter_complete_margin(mg)
    mg["trade_date"] = pd.to_datetime(mg["trade_date"].astype(str).str.replace("-", "", regex=False).str.slice(0, 8), format="%Y%m%d")
    mg = mg.groupby("trade_date")["rzye"].sum().reset_index()  # 元
    mg["rzye_yi"] = mg["rzye"] / 1e8
    mgm = mg.merge(m[["date", "total_mv"]], left_on="trade_date", right_on="date", how="inner")
    mgm["margin_ratio"] = mgm["rzye"] / (mgm["total_mv"] * 1e4) * 100  # 融资余额/总市值 %（total_mv为万元）

    if os.path.exists(LIMIT_DAILY_CSV):
        lim = pd.read_csv(LIMIT_DAILY_CSV, usecols=["trade_date", "limit_up_n"])
        lim["trade_date"] = pd.to_datetime(lim["trade_date"].astype(str), errors="coerce")
        lim = lim.dropna(subset=["trade_date"])
    else:
        # 兼容旧缓存：概念板块上榜数相加（会重复计算，仅作兜底）
        lim = pd.read_csv(LIMIT_CPT_CSV, usecols=["trade_date", "up_nums"])
        lim["trade_date"] = pd.to_datetime(lim["trade_date"].astype(str), format="%Y%m%d")
        lim = lim.groupby("trade_date")["up_nums"].sum().reset_index()
        lim = lim.rename(columns={"up_nums": "limit_up_n"})

    # 港股通持股：只取 HK（南向）。SH/SZ（陆股通/北向）2025 年后只有季度披露，
    # 混在一起会让日序列在季末出现假跳升。
    hk = pd.read_csv(HK_HOLD_CSV, usecols=["trade_date", "ts_code", "vol", "exchange"])
    hk = hk[hk["exchange"].astype(str).str.upper() == "HK"]
    hk["trade_date"] = pd.to_datetime(hk["trade_date"].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce")
    hk = hk.dropna(subset=["trade_date"])
    hk["vol"] = pd.to_numeric(hk["vol"], errors="coerce")
    # 接口某些日期只返回部分股票，直接按日求和会出现假跳水。
    # 改为“每只股票每周取最后一条，再按周求和”，对单日缺失更稳健。
    hk = hk.sort_values(["trade_date", "ts_code"])
    hk["_w"] = hk["trade_date"].dt.to_period("W")
    hk = hk.groupby(["_w", "ts_code"], as_index=False).tail(1)
    hk = (hk.groupby("_w")
            .agg(trade_date=("trade_date", "max"), vol=("vol", "sum"))
            .reset_index(drop=True))
    hk["vol_yi"] = hk["vol"] / 1e8

    def weekly(df, date_col, cols):
        d = df.sort_values(date_col).copy()
        d["_w"] = d[date_col].dt.to_period("W")
        last_idx = d.groupby("_w")[date_col].idxmax()
        g = d.loc[last_idx].reset_index(drop=True)
        return g

    out = {}
    mk = weekly(m, "date", ["pe_median", "pb_median", "turnover_median", "amount", "up_ratio", "concentration_top5", "total_mv"])
    # 成交额/总市值：amount 为元，total_mv 为万元 → 换成同一量纲后取百分比
    mk["amount_ratio"] = mk["amount"] / (mk["total_mv"] * 1e4) * 100
    out["mkt"] = mk
    out["margin"] = weekly(mg, "trade_date", ["rzye_yi"])
    out["margin_ratio"] = weekly(mgm, "trade_date", ["margin_ratio"])
    out["limit"] = weekly(lim, "trade_date", ["limit_up_n"])
    out["hk"] = weekly(hk, "trade_date", ["vol_yi"])
    return out



# K线（OHLC 日线）数据文件（A股数据/应用数据/index_kline/）
KLINE_DIR = INDEX_KLINE_DIR
KLINE_FILES = {
    "上证指数": os.path.join(KLINE_DIR, "K线导出_000001_日线数据.xlsx"),
    "沪深300": os.path.join(KLINE_DIR, "K线导出_000300_日线数据 23.22.12.xlsx"),
    "创业板指": os.path.join(KLINE_DIR, "K线导出_399006_日线数据.xlsx"),
    "中证500": os.path.join(KLINE_DIR, "K线导出_399905_日线数据.xlsx"),
    "中证1000": os.path.join(KLINE_DIR, "K线导出_399852_日线数据.xlsx"),
    "中证2000": os.path.join(KLINE_DIR, "K线导出_932000_日线数据.xlsx"),
    "科创50": os.path.join(KLINE_DIR, "K线导出_000688_日线数据.xlsx"),
}

TENCENT_CODES = {
    "上证指数": "sh000001", "沪深300": "sh000300", "创业板指": "sz399006",
    "中证500": "sh000905", "中证1000": "sh000852", "科创50": "sh000688",
}
EASTMONEY_SECIDS = {
    "上证指数": "1.000001", "沪深300": "1.000300", "创业板指": "0.399006",
    "中证500": "1.000905", "中证1000": "1.000852", "中证2000": "2.932000", "科创50": "1.000688",
}


def _fetch_eastmoney_tail(name, days=8):
    """东方财富行情兜底（腾讯没有的指数，如中证2000），含真实成交额。"""
    import requests, time
    secid = EASTMONEY_SECIDS.get(name)
    if not secid:
        return []
    import datetime as _dt
    _beg = (_dt.datetime.now() - _dt.timedelta(days=days * 4 + 20)).strftime("%Y%m%d")
    _end = _dt.datetime.now().strftime("%Y%m%d")
    for _ in range(3):
        try:
            r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                             params={"secid": secid, "fields1": "f1",
                                     "fields2": "f51,f52,f53,f54,f55,f56,f57",
                                     "klt": "101", "fqt": "1", "beg": _beg, "end": _end}, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
            d = r.json().get("data")
            if d and d.get("klines"):
                out = []
                for line in d["klines"][-days:]:
                    p = line.split(",")
                    out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                                "high": float(p[3]), "low": float(p[4]),
                                "vol": float(p[5]) * 100, "amt": float(p[6]) if len(p) > 6 else None})
                return out
        except Exception:
            time.sleep(1.5)
    return []


def _fetch_tencent_tail(name, days=8):
    """从腾讯行情补最新日线（OHLC+成交量，单位为手）；腾讯无该指数时用东方财富兜底。"""
    import requests, time
    code = TENCENT_CODES.get(name)
    if code:
        for _ in range(3):
            try:
                r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                                 params={"param": f"{code},day,,,{days},qfq"}, timeout=12,
                                 headers={"User-Agent": "Mozilla/5.0"})
                d = r.json().get("data", {}).get(code, {})
                kl = d.get("qfqday") or d.get("day") or []
                out = []
                for p in kl:
                    out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                                "high": float(p[3]), "low": float(p[4]), "vol": float(p[5]) * 100})
                if out:
                    return out
            except Exception:
                time.sleep(1.5)
    return _fetch_eastmoney_tail(name, days)


def load_kline():
    """读取 K 线 Excel（全历史 OHLC）；并用腾讯接口补最新日线。缺文件时用收盘价兜底。"""
    import openpyxl as _xl
    out = {}
    close_map = {}
    if os.path.exists(INDEX_CSV):
        try:
            cdf = pd.read_csv(INDEX_CSV)
            cdf["date"] = cdf["date"].astype(str)
            for _n in KLINE_FILES.keys():
                if _n in cdf.columns:
                    sub = cdf[["date", _n]].dropna()
                    sub = sub[sub[_n] > 0]
                    close_map[_n] = dict(zip(sub["date"], sub[_n].astype(float)))
        except Exception as _e:
            print("收盘价兜底加载失败", _e)

    def _num(x):
        try:
            _f2 = float(x)
            return round(_f2, 2) if _f2 == _f2 else None
        except Exception:
            return None

    for _name, _f in KLINE_FILES.items():
        try:
            if not os.path.exists(_f):
                print("K线文件缺失，用收盘价兜底:", _name)
                if _name in close_map:
                    _d = sorted(close_map[_name].keys())
                    _c = [round(close_map[_name][x], 2) for x in _d]
                    out[_name] = {"dates": _d, "open": list(_c), "high": list(_c), "low": list(_c),
                                  "close": _c, "vol": [None] * len(_d), "amt": [None] * len(_d)}
                continue
            _wb = _xl.load_workbook(_f, read_only=True, data_only=True)
            _ws = _wb.active
            _rows = list(_ws.iter_rows(values_only=True))
            _head = {_h: _i for _i, _h in enumerate(_rows[0])}
            _dates, _o, _h, _l, _c, _v, _a = [], [], [], [], [], [], []
            for _r in _rows[1:]:
                _dt = _r[_head.get("交易时间")]
                if _dt is None:
                    continue
                _dates.append(_dt.strftime("%Y-%m-%d"))
                _o.append(_num(_r[_head["开盘价"]])); _h.append(_num(_r[_head["最高价"]]))
                _l.append(_num(_r[_head["最低价"]])); _c.append(_num(_r[_head["收盘价"]]))
                _v.append(_num(_r[_head["成交量"]])); _a.append(_num(_r[_head["成交额"]]))
            _wb.close()
            # 腾讯补最新（Excel 未更新到的日期，如 11-13）
            try:
                _tail = _fetch_tencent_tail(_name)
                if _tail:
                    _last = _dates[-1] if _dates else ""
                    _pv = _v[-1] if _v and _v[-1] else None
                    _pa = _a[-1] if _a and _a[-1] else None
                    for _b in _tail:
                        if _b["date"] > _last:
                            _est = (_pa * (_b["vol"] / _pv)) if (_pa and _pv and _b["vol"]) else None
                            _dates.append(_b["date"]); _o.append(round(_b["open"], 2)); _h.append(round(_b["high"], 2))
                            _l.append(round(_b["low"], 2)); _c.append(round(_b["close"], 2))
                            _v.append(_b["vol"]); _a.append(round(_b["amt"], 0) if _b.get("amt") else (round(_est, 0) if _est else None))
                            if _b["vol"]: _pv = _b["vol"]
                            if _est: _pa = _est
            except Exception as _e:
                print("腾讯补数失败", _name, _e)
            out[_name] = {"dates": _dates, "open": _o, "high": _h, "low": _l, "close": _c, "vol": _v, "amt": _a}
        except Exception as _e:
            print("K线加载失败", _name, _e)
    return out


def _extend_index_daily(idx, kl):
    """用 K 线数据补齐 index_daily.csv 未更新到的尾部（只追加 CSV 末日之后的日期）。

    这样首页 hero、相似度、事件点位都能用上 K 线（含腾讯补数）的最新收盘，
    同时不修改原始 CSV 文件。
    """
    if not kl:
        return idx
    last_d = idx["date"].max()
    rows = {}
    for name, k in kl.items():
        if name not in idx.columns:
            continue
        for d, c in zip(k.get("dates", []), k.get("close", [])):
            if c is None:
                continue
            if pd.Timestamp(d) > last_d:
                rows.setdefault(d, {})[name] = c
    if not rows:
        return idx
    add = pd.DataFrame([{"date": pd.Timestamp(d), **vals} for d, vals in sorted(rows.items())])
    for col in idx.columns:
        if col not in add.columns:
            add[col] = np.nan
    add = add[idx.columns]
    out = pd.concat([idx, add], ignore_index=True).sort_values("date").reset_index(drop=True)
    print("指数日线用K线补齐:", last_d.date(), "->", out["date"].iloc[-1].date(), "| 新增", len(add), "行")
    return out


def series(df, date_col, val_col, scale=1.0):
    d = df[df[val_col].notna()]
    return {"dates": d[date_col].dt.strftime("%Y-%m-%d").tolist(),
            "values": [round(float(v) * scale, 2) for v in d[val_col]]}



# 各指数自身的牛熊分段（数据拐点；牛市中的回调仍算牛，熊市中的反弹仍算熊）
INDEX_CYCLES = {
    "上证指数": [
        ("bull","2005-06-06","2007-10-16"),("bear","2007-10-16","2008-10-28"),
        ("bull","2008-10-28","2009-08-04"),("bear","2009-08-04","2012-12-04"),
        ("bull","2012-12-04","2015-06-12"),("bear","2015-06-12","2016-01-27"),
        ("bull","2016-01-27","2018-01-24"),("bear","2018-01-24","2019-01-03"),
        ("bull","2019-01-03","2021-02-18"),("bear","2021-02-18","2024-02-05"),
        ("bull","2024-02-05","2026-05-13"),("bear","2026-05-13","2026-11-10"),
    ],
    "沪深300": [
        ("bull","2005-06-06","2007-10-16"),("bear","2007-10-16","2008-11-04"),
        ("bull","2008-11-04","2009-08-03"),("bear","2009-08-03","2012-12-03"),
        ("bull","2012-12-03","2015-06-08"),("bear","2015-06-08","2016-01-28"),
        ("bull","2016-01-28","2018-01-24"),("bear","2018-01-24","2019-01-03"),
        ("bull","2019-01-03","2021-02-10"),("bear","2021-02-10","2024-02-05"),
        ("bull","2024-02-05","2026-05-13"),("bear","2026-05-13","2026-11-10"),
    ],
    "创业板指": [
        ("bear","2010-12-17","2012-12-03"),
        ("bull","2012-12-03","2015-06-03"),("bear","2015-06-03","2018-10-18"),
        ("bull","2018-10-18","2021-08-04"),("bear","2021-08-04","2024-02-05"),
        ("bull","2024-02-05","2026-06-25"),("bear","2026-06-25","2026-11-10"),
    ],
}

def _clean(v):
    """0 或负数/缺失 视为无数据（创业板 2010 前为 0，不画）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if (f == f and f > 0) else None

# ---------- 周期定义（5组） ----------
CYCLES = [
    {
        "id": "c0508", "name": "2005–2008", "type": "全面牛", "theme": "周期+大金融",
        "start": "2005-06-06", "peak": "2007-10-16", "end": "2008-10-28",
        "segments": [
            {"type": "bull", "start": "2005-06-06", "end": "2007-10-16"},
            {"type": "bear", "start": "2007-10-16", "end": "2008-10-28"},
        ],
        "ret_bull": "+513%", "ret_bear": "-73%",
        "analysis": {
            "bottom": "<b>宏观</b>：股权分置改革（2005）解决同股不同权，人民币汇改升值；<b>中观</b>：重工业化（“五朵金花”）；<b>微观</b>：大宗商品超级周期。<b>金融市场</b>：成交地量、公募刚起步、无融资融券。",
            "bull": "<b>初期</b>流动性+估值修复；<b>中期</b>盈利爆发（宝钢2007Q1净利+168%）；<b>后期</b>估值泡沫。<b>叙事</b>：人民币升值+重工业化+“黄金十年”；<b>产业趋势</b>：全球大宗超级周期；<b>全球共振</b>：是（全球需求）；<b>主线</b>：有色/钢铁/煤炭/金融。",
            "peak": "<b>走势</b>：主线加速冲顶；<b>估值</b>：全A PE(TTM)达 56–57 倍（历史唯一明确锚点）；<b>舆情/政策</b>：2007 加息+2008 次贷危机；<b>减持/融资</b>：高位减持与定增放量。",
            "bear": "<b>出清</b>：快速杀跌，-73%/12个月（史上最剧烈）；<b>融资</b>：当时无两融，靠公募/居民赎回；<b>托底</b>：2008/9 降印花税、汇金增持；<b>反弹后新低</b>：2008/4 印花税反弹后再创新低。",
        },
    },
    {
        "id": "c1315", "name": "2013–2015", "type": "全面牛", "theme": "移动互联网/TMT",
        "start": "2012-12-04", "peak": "2015-06-12", "end": "2016-01-27",
        "segments": [
            {"type": "bull", "start": "2012-12-04", "end": "2015-06-12"},
            {"type": "bear", "start": "2015-06-12", "end": "2016-01-27"},
        ],
        "ret_bull": "+180%", "ret_bear": "-45%",
        "analysis": {
            "bottom": "<b>宏观</b>：2012/11/29 参观“复兴之路”，改革预期；货币宽松。<b>中观</b>：移动互联网、4G；<b>微观</b>：智能手机普及、双创。<b>金融市场</b>：两融扩容、杠杆资金入场。",
            "bull": "<b>初期</b>改革牛；<b>中期</b>两融+杠杆，TMT；<b>后期</b>“互联网+”泡沫。<b>叙事</b>：移动互联网+并购重组+互联网+；<b>产业趋势</b>：4G/智能手机；<b>全球共振</b>：部分（美股科技）；<b>主线</b>：TMT（计算机/传媒）。",
            "peak": "<b>走势</b>：创业板加速冲顶（PE 160倍）；<b>舆情/政策</b>：2015/6 清理场外配资；<b>减持/融资</b>：两融2.2万亿、高管减持激增。",
            "bear": "<b>出清</b>：快速去杠杆，-45%（创业板-56%）；<b>融资</b>：两融从2.2万亿骤降至1万亿；<b>爆仓</b>：配资爆仓、千股跌停；<b>托底</b>：2015/7 证金入场；<b>反弹后新低</b>：2015/7 反弹后 8/26 再创新低。",
        },
    },
    {
        "id": "c1618", "name": "2016–2018", "type": "结构性", "theme": "价值/消费龙头",
        "start": "2016-01-27", "peak": "2018-01-26", "end": "2019-01-04",
        "segments": [
            {"type": "bull", "start": "2016-01-27", "end": "2018-01-26"},
            {"type": "bear", "start": "2018-01-26", "end": "2019-01-04"},
        ],
        "ret_bull": "+36%", "ret_bear": "-32%",
        "analysis": {
            "bottom": "<b>宏观</b>：供给侧改革（2016/1）、降准降首付；<b>中观</b>：去产能、龙头集中；<b>微观</b>：消费升级、白酒。<b>金融市场</b>：北向资金近3000亿流入。",
            "bull": "<b>初期</b>价值修复；<b>中期</b>消费/白马龙头；<b>后期</b>“漂亮50”。<b>叙事</b>：核心资产+消费升级；<b>产业趋势</b>：供给侧出清；<b>全球共振</b>：部分（外资）；<b>主线</b>：食品饮料/家电/有色。",
            "peak": "<b>走势</b>：白马龙头加速；<b>估值</b>：不算极端；<b>舆情/政策</b>：2018 资管新规；<b>减持/融资</b>：高位减持。",
            "bear": "<b>出清</b>：慢跌-32%/11个月（慢熊阴跌）；<b>融资</b>：两融回落；<b>托底</b>：2018/10 高层发声；<b>反弹后新低</b>：2018/10 反弹后 2019/1 新低。",
        },
    },
    {
        "id": "c1921", "name": "2019–2021", "type": "结构性", "theme": "新能源+核心资产",
        "start": "2019-01-04", "peak": "2021-02-18", "end": "2022-04-27",
        "segments": [
            {"type": "bull", "start": "2019-01-04", "end": "2021-02-18"},
            {"type": "bear", "start": "2021-02-18", "end": "2022-04-27"},
        ],
        "ret_bull": "+53%", "ret_bear": "-20%",
        "analysis": {
            "bottom": "<b>宏观</b>：2019/1 全面降准1pct；中美流动性共振；<b>中观</b>：新能源产业趋势；<b>微观</b>：特斯拉/光伏。<b>金融市场</b>：偏股基金4.6万亿份、北向流入。",
            "bull": "<b>初期</b>核心资产；<b>中期</b>新能源；<b>后期</b>宁组合。<b>叙事</b>：核心资产+新能源革命；<b>产业趋势</b>：电动车渗透率1%→10%；<b>全球共振</b>：是（全球双碳）；<b>主线</b>：电力设备（+284%）/食品饮料/医药。",
            "peak": "<b>走势</b>：新能源2021/10加速冲顶；<b>估值</b>：茅指数PE 70倍、宁德PE 200倍；<b>舆情/政策</b>：2021 反垄断/教育双减；<b>减持/融资</b>：高位定增、减持。",
            "bear": "<b>出清</b>：-20%+/5个月；<b>融资</b>：两融回落；<b>托底</b>：2022/3 金融委会议；<b>反弹后新低</b>：2022/4/27 首底 → 2022/10/31 二次探底。",
        },
    },
    {
        "id": "c24now", "name": "2024–至今", "type": "本轮", "theme": "AI/算力",
        "start": "2024-02-05", "peak": "2026-05-13", "end": None,
        "segments": [
            {"type": "bull", "start": "2024-02-05", "end": "2026-05-13"},
            {"type": "bear", "start": "2026-05-13", "end": "2026-11-10"},
        ],
        "ret_bull": "+58%", "ret_bear": "-13.5%",
        "analysis": {
            "bottom": "<b>宏观</b>：2024/2 上证2635见底、2024/9/24 大幅宽松（降准降息+资本市场支持）；<b>中观</b>：AI/算力产业政策；<b>微观</b>：大模型爆发。<b>金融市场</b>：924后成交放量、融资余额回升。",
            "bull": "<b>初期</b>（924急涨）；<b>中期</b>AI算力主线（半导体/光模块/PCB）；<b>后期</b>资源/红利接力。<b>叙事</b>：AI算力革命+国产替代；<b>产业趋势</b>：全球AI资本开支；<b>全球共振</b>：是（全球算力）；<b>主线</b>：半导体/光模块（250日超额领先）。",
            "peak": "<b>走势</b>：2026/5/13 上证4242 见顶（待确认）；<b>估值</b>：全A PE 中位数约43（72%分位）；<b>舆情/政策</b>：待跟踪；<b>减持/融资</b>：融资余额2.6万亿（95%分位，高位）。",
            "bear": "<b>出清</b>：2026/5-11 回撤-13.5%（进行中，未破-20%）；<b>融资</b>：近20日-12.3%（去杠杆中）；<b>集中度</b>：94%分位（主线高度拥挤）；<b>托底</b>：待观察。",
        },
    },
]



from cycle_events import CYCLE_EVENTS, CYCLE_PHASES, POLICY_EVENTS

# ---------- 相似度 ----------
def similarity(main, window_days, col="上证指数", top_k=3):
    """用最近 window_days 的「归一化价格走势」与历史同长度窗口做相关性，找最相似 top_k。"""
    sh = main[["date", col]].dropna().reset_index(drop=True)
    sh = sh[sh[col] > 0].reset_index(drop=True)
    closes = sh[col].values.astype(float)
    dates = sh["date"].values
    n = len(closes)
    if n < window_days + 10:
        return []

    def norm_seg(i):
        seg = closes[i - window_days:i]
        base = seg[0]
        return seg / base

    target = norm_seg(n)
    t = target - target.mean()
    tn = float(np.linalg.norm(t))
    if tn == 0:
        return []
    results = []
    for i in range(window_days, n - window_days):
        win = norm_seg(i)
        if np.isnan(win).any():
            continue
        w = win - win.mean()
        wn = float(np.linalg.norm(w))
        if wn == 0:
            continue
        corr = float(np.dot(w, t) / (wn * tn))
        fut = closes[i:i + min(60, n - i)]
        fut_cum = float(fut[-1] / fut[0] - 1) * 100 if len(fut) > 1 else None
        results.append({"date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"), "corr": round(corr, 3),
                        "fut60": round(fut_cum, 2) if fut_cum is not None else None})
    results.sort(key=lambda x: -x["corr"])
    picked = []
    for r in results:
        if all(abs((pd.Timestamp(r["date"]) - pd.Timestamp(p["date"])).days) > window_days for p in picked):
            picked.append(r)
        if len(picked) >= top_k:
            break
    return picked


def load_adv_macro():
    """从 ADV 的 china-macro.js 读取中国宏观数据，裁剪到 2004 年后。"""
    import re as _re, json as _json
    try:
        txt = open(ADV_MACRO_PATH, encoding="utf-8").read()
        m = _re.search(r"window\.CHINA_MACRO\s*=\s*(\{.*\});?\s*$", txt, _re.S)
        if not m:
            return None
        d = _json.loads(m.group(1))
        cutoff = "2004-01-01"
        out = {"updated": d.get("updated"), "sections": []}
        for sec in d.get("sections", []):
            items = []
            for it in sec.get("items", []):
                labels = it.get("labels", [])
                series = it.get("series", [])
                keep = [i for i, dt in enumerate(labels) if str(dt) >= cutoff]
                if not keep:
                    continue
                new_series = []
                for sr in series:
                    vals = sr.get("values", [])
                    new_series.append({"name": sr.get("name", ""), "values": [vals[i] for i in keep]})
                items.append({"title": it.get("title"), "unit": it.get("unit"), "type": it.get("type"),
                              "labels": [labels[i] for i in keep], "series": new_series})
            if items:
                out["sections"].append({"name": sec.get("name"), "items": items})
        return out
    except Exception as e:
        print("macro load error:", e)
        return None

def main():
    from cycle_narratives import CYCLE_NARRATIVES
    for _cy in CYCLES:
        if _cy["id"] in CYCLE_NARRATIVES:
            _cy["analysis"] = CYCLE_NARRATIVES[_cy["id"]]
    idx = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    idx = idx[idx["date"] >= "2005-01-01"].copy()

    # K 线（OHLC，Excel + 腾讯补最新）；先用它补齐指数日线的尾部
    _kl = load_kline()
    idx = _extend_index_daily(idx, _kl)
    # 全局最新日期（用 K 线，覆盖 Excel 补数后的日期）
    _asof = idx["date"].iloc[-1]
    for _n, _k in _kl.items():
        if _k["dates"]:
            _d = pd.Timestamp(_k["dates"][-1])
            if _d > _asof:
                _asof = _d

    # 主图：日线（2005起，用于日/周/月切换）
    daily = idx.dropna(subset=["上证指数"]).copy()
    main_daily = {
        "dates": daily["date"].dt.strftime("%Y-%m-%d").tolist(),
        "上证指数": [_clean(v) for v in daily["上证指数"]],
        "沪深300": [_clean(v) for v in daily["沪深300"]],
        "创业板指": [_clean(v) for v in daily["创业板指"]],
    }
    # 周线
    idx["w"] = idx["date"].dt.to_period("W").astype(str)
    wk = idx.groupby("w").last().reset_index()
    wk = wk.dropna(subset=["上证指数"])
    main_series = {
        "dates": wk["date"].dt.strftime("%Y-%m-%d").tolist(),
        "上证指数": [_clean(v) for v in wk["上证指数"]],
        "沪深300": [_clean(v) for v in wk["沪深300"]],
        "创业板指": [_clean(v) for v in wk["创业板指"]],
    }

    # 当前观察：最近130个交易日日线
    recent = idx.tail(130)
    recent_series = {
        "dates": recent["date"].dt.strftime("%Y-%m-%d").tolist(),
        "上证指数": [_clean(v) for v in recent["上证指数"]],
        "沪深300": [_clean(v) for v in recent["沪深300"]],
        "创业板指": [_clean(v) for v in recent["创业板指"]],
    }

    ind = load_indicators()
    indicators = {
        "margin": series(ind["margin_ratio"], "trade_date", "margin_ratio", 1.0),
        "amount": series(ind["mkt"], "date", "amount", 1 / 1e8),
        "amount_ratio": series(ind["mkt"], "date", "amount_ratio", 1.0),
        "concentration": series(ind["mkt"], "date", "concentration_top5", 100.0),
        "pe": series(ind["mkt"], "date", "pe_median", 1.0),
        "pb": series(ind["mkt"], "date", "pb_median", 1.0),
        "turnover": series(ind["mkt"], "date", "turnover_median", 1.0),
        "breadth": series(ind["mkt"], "date", "up_ratio", 100.0),
        "limit": series(ind["limit"], "trade_date", "limit_up_n", 1.0),
        "above200": series(ind["mkt"], "date", "above200_ratio", 100.0),
        "newhigh": series(ind["mkt"], "date", "new_high_n", 1.0),
        "newlow": series(ind["mkt"], "date", "new_low_n", 1.0),
        "total_mv": series(ind["mkt"], "date", "total_mv", 1 / 1e8),
        "hk": series(ind["hk"], "trade_date", "vol_yi", 1.0),
    }

    sim = {}
    for wd in (20, 60, 120):
        sim[str(wd)] = {"上证指数": similarity(idx, wd, "上证指数"),
                        "沪深300": similarity(idx, wd, "沪深300"),
                        "创业板指": similarity(idx, wd, "创业板指")}

    # 计算各轮细分阶段的涨跌幅（上证口径）
    idf = idx.set_index("date")
    _asof_str = _asof.strftime("%Y-%m-%d")
    _cur_cid = CYCLES[-1]["id"]
    phases_ret = {}
    for _iname in list(INDEX_CYCLES.keys()):
        def v_at(ds, _iname=_iname):
            try:
                return float(idf.loc[:ds, _iname].dropna().iloc[-1])
            except Exception:
                return None
        phases_ret[_iname] = {}
        for cid, phases in CYCLE_PHASES.items():
            lst = []
            for _i, ph in enumerate(phases):
                # 进行中的最后一轮：把最后阶段终点延到最新交易日，与 K 线色带一致
                _end = ph["end"]
                if cid == _cur_cid and _i == len(phases) - 1 and _end < _asof_str:
                    _end = _asof_str
                sv = v_at(ph["start"]); ev = v_at(_end)
                ret = (ev / sv - 1) * 100 if (sv and ev) else None
                lst.append({"name": ph["name"], "start": ph["start"], "end": _end,
                            "stage": ph["stage"], "ret": round(ret, 1) if ret is not None else None,
                            "start_val": round(sv, 0) if sv else None, "end_val": round(ev, 0) if ev else None})
            phases_ret[_iname][cid] = lst

    # 新增指数：沿用上证牛熊周期，按各指数数据起点裁剪
    for _n in ["中证500", "中证1000", "中证2000", "科创50"]:
        if _n in _kl and _kl[_n]["dates"]:
            _d0 = _kl[_n]["dates"][0]
            INDEX_CYCLES[_n] = [sg for sg in INDEX_CYCLES["上证指数"] if sg[2] >= _d0]
        else:
            INDEX_CYCLES[_n] = list(INDEX_CYCLES["上证指数"])
    # 本轮（最后一轮）周期的终点延到最新日期
    _lastcy = CYCLES[-1]
    if _lastcy.get("segments"):
        _lastcy["segments"][-1]["end"] = _asof.strftime("%Y-%m-%d")
    # 最后一轮周期终点延到各指数最新 K 线日期
    for _n in list(INDEX_CYCLES.keys()):
        if _n in _kl and _kl[_n]["dates"]:
            _last = _kl[_n]["dates"][-1]
            _segs = INDEX_CYCLES[_n]
            if _segs and _segs[-1][2] < _last:
                _segs[-1] = (_segs[-1][0], _segs[-1][1], _last)

    # 每指数独立事件：本指数拐点（点位）+ 共享政策事件
    def v_of(ind_name, ds):
        """取 ds 当日（或之前最近交易日）的收盘；K 线优先于 CSV，避免尾部点位滞后。"""
        ds = pd.Timestamp(ds)
        best_d, best_v = None, None
        try:
            k = _kl.get(ind_name)
            if k and k.get("dates"):
                cand = [(d, c) for d, c in zip(k["dates"], k["close"]) if d <= ds and c is not None]
                if cand:
                    best_d, best_v = pd.Timestamp(cand[-1][0]), float(cand[-1][1])
        except Exception:
            pass
        try:
            if ind_name in idx.columns:
                sub = idx.loc[idx["date"] <= ds, ["date", ind_name]].dropna()
                if len(sub):
                    d0, v0 = sub.iloc[-1]
                    d0 = pd.Timestamp(d0)
                    if best_d is None or d0 > best_d:
                        best_d, best_v = d0, float(v0)
        except Exception:
            pass
        return best_v

    index_events = {}
    for _iname in list(INDEX_CYCLES.keys()):
        _segs = INDEX_CYCLES[_iname]
        _evs = []
        for _typ, _st, _en in _segs:
            _v = v_of(_iname, _st)
            if _v:
                _evs.append({"date": _st, "label": ("底 " if _typ == "bull" else "顶 ") + str(int(_v)),
                             "type": ("bottom" if _typ == "bull" else "top"), "kind": "tp"})
        _last = _segs[-1][2]
        _v = v_of(_iname, _last)
        if _v:
            pass  # 「今」与图表「最新」重复，不生成
        # 该指数的数据起点
        if _iname in idx.columns:
            _col = idx[_iname].dropna()
            _col = _col[_col > 0]
            _d0 = idx.loc[_col.index[0], "date"] if len(_col) else pd.Timestamp("1990-01-01")
        elif _iname in _kl and _kl[_iname]["dates"]:
            _d0 = pd.Timestamp(_kl[_iname]["dates"][0])
        else:
            _d0 = pd.Timestamp("1990-01-01")
        for _e in POLICY_EVENTS:
            if pd.Timestamp(_e["date"]) >= _d0:
                _evs.append({"date": _e["date"], "label": _e["label"], "type": _e["type"], "kind": "policy"})
        _evs.sort(key=lambda x: x["date"])
        index_events[_iname] = _evs

    # 宏观-牛熊相关性（由 macro_analysis.py 生成）
    macro_corr = None
    _mcp = os.path.join(PROJ, "docs", "macro_corr.json")
    if os.path.exists(_mcp):
        with open(_mcp, encoding="utf-8") as _f:
            macro_corr = json.load(_f)

    # 补充数据：IPO / 股东减持（由 fetch_api_data.py 生成，可选）
    extra = {}
    for key, fname, col in [('ipo', 'ipo_monthly.parquet', 'ipo_count'),
                            ('holder', 'holder_monthly.parquet', 'net_reduce_yi')]:
        fp = os.path.join(CACHE_DIR, fname)
        if os.path.exists(fp):
            df = pd.read_parquet(fp)
            # 当月尚未结束，月度累计值会被当成整月数据，造成“断崖式下降”
            df = df[df['month'] < _asof.strftime('%Y-%m')]
            df['date'] = df['month'] + '-01'
            df = df[df[col].notna()]
            extra[key] = {"dates": df['date'].tolist(),
                          "values": [round(float(v), 2) for v in df[col]]}

    payload = {
        "asof": _asof.strftime("%Y-%m-%d"),
        "main": main_series,
        "main_daily": main_daily,
        "recent": recent_series,
        "cycles": CYCLES,
        "index_cycles": INDEX_CYCLES,
        "cycle_events": CYCLE_EVENTS,
        "index_events": index_events,
        "macro": load_adv_macro(),
        "macro_corr": macro_corr,
        "cycle_phases": phases_ret,
        "indicators": indicators,
        "index_history": load_index_history(),
        "extra": extra,
        "similarity": sim,
        "kline": _kl,
        "hero": build_hero(),
        "cycle_overlay": build_cycle_overlay(),
    }
    # 按视图拆分数据：首屏只加载核心；K线/指标/宏观/复盘覆盖按需懒加载
    def _take(keys):
        return {k: payload.pop(k) for k in keys if k in payload}
    kline = payload.pop("kline", {})
    chunks = {
        "data-cur.js": _take(("indicators", "index_history")),
        "data-overlay.js": _take(("cycle_overlay",)),
        "data-hist.js": _take(("main_daily", "index_events")),
        "data-macro.js": _take(("macro",)),
    }
    out = os.path.join(WEB, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.WAW=" + json.dumps(payload, ensure_ascii=False) + ";")
    print("已生成:", out, "| 大小:", round(os.path.getsize(out) / 1024, 0), "KB")
    out_k = os.path.join(WEB, "data-kline.js")
    with open(out_k, "w", encoding="utf-8") as f:
        f.write("window.WAW_KLINE=" + json.dumps(kline, ensure_ascii=False) + ";")
    print("已生成:", out_k, "| 大小:", round(os.path.getsize(out_k) / 1024, 0), "KB")
    for fn, d in chunks.items():
        fp = os.path.join(WEB, fn)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("window.WAW=Object.assign(window.WAW||{}," + json.dumps(d, ensure_ascii=False) + ");")
        print("已生成:", fp, "| 大小:", round(os.path.getsize(fp) / 1024, 0), "KB")
    print("周期数:", len(CYCLES), "| 主图周数:", len(main_series["dates"]))
    print("相似度(20日):", sim["20"])


if __name__ == "__main__":
    main()
