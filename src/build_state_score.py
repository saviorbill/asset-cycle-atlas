# -*- coding: utf-8 -*-
"""状态打分 —— 9 个维度并列分位 + 历史同档分布（30 / 60 日）。

设计原则（来自实证检验，见 README 讨论）：
  1. 不合成总分。5 轮完整熊市撑不起任何一组"权重"，合成即过拟合。
  2. 分布必须带样本量 n 和独立片段数 seg。n=2800 天但只有 3 段，就是 3 个样本。
  3. 条件必须用「当日可观察」的量（回撤 / 估值 / 宽度），不能用「事后低点」。
  4. 估值维度 PB 与 PE 并列，不取平均 —— 盈利下滑时两者会给出相反结论。

输出：web/state_score.js  →  window.WAW.state_score
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import CACHE_DIR, CYQ_CSV, EVENTS_CSV, INDEX_CSV  # noqa: E402

OUT_JS = os.path.join(ROOT, "web", "state_score.js")

IDX = ["上证指数", "深证成指", "沪深300", "中证500",
       "中证1000", "中证2000", "创业板指", "科创50"]
# 板块主导指数：给前端标注"这个指数主要代表谁"
IDX_DESC = {
    "上证指数": "沪市全样本 · 大盘价值", "深证成指": "深市核心 · 成长",
    "沪深300": "大盘蓝筹 · 国家队主战场", "中证500": "中盘",
    "中证1000": "小盘 · 高波动", "中证2000": "微盘",
    "创业板指": "成长 · 高 beta", "科创50": "硬科技 · 高 beta",
}
BUCKET = 0.075          # 同档回撤宽度 ±7.5pp
MIN_N = 100             # 同档少于 100 天不出分布


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def pct_of(hist, v):
    """v 在 hist 中的分位（0~100）"""
    h = pd.Series(hist).dropna()
    if not len(h) or not np.isfinite(v):
        return None
    return float((h < v).mean() * 100)


# ---------------------------------------------------------------- 价格
def load_prices():
    d = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    for c in d.columns:
        d[c] = d[c].where(d[c] > 0)
    return d[[c for c in IDX if c in d.columns]]


# ---------------------------------------------------------------- 估值
def load_valuation():
    p = os.path.join(CACHE_DIR, "index_dailybasic.csv")
    if not os.path.exists(p):
        return {}
    b = pd.read_csv(p)
    b["trade_date"] = pd.to_datetime(b["trade_date"])
    b = b.sort_values("trade_date")
    out = {}
    for name, g in b.groupby("name"):
        last = g.iloc[-1]
        rec = {"date": last["trade_date"].strftime("%Y-%m-%d")}
        for col, key in (("pb", "pb"), ("pe_ttm", "pe"), ("pe", "pe_raw")):
            if col not in g.columns:
                continue
            v = last[col]
            if pd.notna(v):
                rec[key] = r(v, 2)
                rec[key + "_pct"] = r(pct_of(g[col], v), 0)
        out[name] = rec
    return out


# ---------------------------------------------------------------- 全市场维度
def load_market():
    """返回 (当前值 dict, 每个维度的历史序列 dict)"""
    cur, hist = {}, {}

    p = os.path.join(CACHE_DIR, "market_daily.parquet")
    if os.path.exists(p):
        m = pd.read_parquet(p)
        m["date"] = pd.to_datetime(m["date"])
        m = m.sort_values("date").set_index("date")
        if "above200_ratio" in m:
            cur["breadth"] = float(m["above200_ratio"].iloc[-1]) * 100
            hist["breadth"] = m["above200_ratio"] * 100
        if "amount" in m:
            amt = np.log(m["amount"].where(m["amount"] > 0))
            ratio = (amt - amt.rolling(60).mean()).apply(lambda x: (np.exp(x) - 1) * 100)
            cur["amount_z"] = float(ratio.iloc[-1]) if pd.notna(ratio.iloc[-1]) else None
            hist["amount_z"] = ratio
        if "new_high_n" in m and "new_low_n" in m:
            nl = m["new_high_n"] - m["new_low_n"]
            cur["newhl"] = float(nl.iloc[-1])
            hist["newhl"] = nl

    p = os.path.join(CACHE_DIR, "limit_daily.csv")
    if os.path.exists(p):
        l = pd.read_csv(p, parse_dates=["trade_date"]).sort_values("trade_date").set_index("trade_date")
        if "limit_down_n" in l:
            cur["limit_down"] = float(l["limit_down_n"].iloc[-1])
            hist["limit_down"] = l["limit_down_n"]
        if "limit_up_n" in l:
            cur["limit_up"] = float(l["limit_up_n"].iloc[-1])

    p = os.path.join(CACHE_DIR, "margin_full.csv")
    if os.path.exists(p):
        g = pd.read_csv(p, parse_dates=["trade_date"])
        s = g.groupby("trade_date")["rzye"].sum().sort_index()
        chg = s.pct_change(20) * 100
        cur["margin_chg20"] = float(chg.iloc[-1]) if pd.notna(chg.iloc[-1]) else None
        hist["margin_chg20"] = chg

    # 国家队 ETF 净申购（build_nsf.py 产出）
    p = os.path.join(CACHE_DIR, "nsf_flow.csv")
    if os.path.exists(p):
        n = pd.read_csv(p, parse_dates=["trade_date"]).sort_values("trade_date")
        n = n.set_index("trade_date")
        cur["nsf"] = float(n["pct_aum"].iloc[-1])
        cur["nsf_amt"] = float(n["f20"].iloc[-1] / 1e4)
        cur["nsf_date"] = n.index[-1].strftime("%Y-%m-%d")
        hist["nsf"] = n["pct_aum"]
        hist["nsf_amt"] = n["f20"] / 1e4          # 亿元

    # 获利比例（cyq_perf）—— 若桌面数据可用
    cyq = CYQ_CSV
    if os.path.exists(cyq):
        try:
            c = pd.read_csv(cyq, usecols=["trade_date", "winner_rate"])
            c["trade_date"] = pd.to_datetime(c["trade_date"], format="%Y%m%d")
            c = c[(c.winner_rate >= 0) & (c.winner_rate <= 100)]
            w = c.groupby("trade_date")["winner_rate"].median().sort_index()
            cur["winner"] = float(w.iloc[-1])
            cur["winner_date"] = w.index[-1].strftime("%Y-%m-%d")
            hist["winner"] = w
        except Exception as e:                       # noqa: BLE001
            print("  ! cyq_perf 读取失败：%s" % e)
    return cur, hist


# ---------------------------------------------------------------- 同档分布
def episode_count(mask, gap):
    """独立片段数。

    同一轮熊市里，回撤会在档位边界反复进出，直接数连续 True 段会得到几百段，
    让独立性看起来远高于实际。这里把间隔小于持有期 gap 的片段合并 ——
    它们的未来收益窗口本来就互相重叠，算一个样本。
    """
    v = np.asarray(mask.fillna(False).values, dtype=bool)
    runs, start = [], None
    for i, x in enumerate(v):
        if x and start is None:
            start = i
        elif not x and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(v) - 1))
    if not runs:
        return 0
    merged = [list(runs[0])]
    for s, e in runs[1:]:
        if s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return len(merged)


def bucket_dist(px, dd, cur_dd, h):
    """同一回撤档（±BUCKET）下，未来 h 日的收益分布"""
    fwd = px.shift(-h) / px - 1
    mask = (dd > cur_dd - BUCKET) & (dd <= cur_dd + BUCKET)
    x = fwd[mask].dropna()
    if len(x) < MIN_N:
        return {"n": int(len(x)), "ok": False}
    return {
        "ok": True, "n": int(len(x)),
        "seg": episode_count(mask, h),
        "win": r((x > 0).mean() * 100, 1),
        "med": r(x.median() * 100, 1),
        "mean": r(x.mean() * 100, 1),
        "q10": r(x.quantile(.10) * 100, 1),
        "q25": r(x.quantile(.25) * 100, 1),
        "q75": r(x.quantile(.75) * 100, 1),
        "q90": r(x.quantile(.90) * 100, 1),
    }


def phase_len(px, dd):
    """当前下行段已历交易日数，及其在历史下行段中的分位"""
    peak = px.rolling(250, min_periods=120).max()
    # 每个位置：距离最近的 250 日高点多少交易日
    since = []
    cnt = 0
    for i in range(len(px)):
        if pd.notna(peak.iloc[i]) and abs(px.iloc[i] - peak.iloc[i]) < 1e-9:
            cnt = 0
        else:
            cnt += 1
        since.append(cnt)
    since = pd.Series(since, index=px.index)
    # 只在「确实处于回撤 >10%」的日子里统计这个历时，代表真实下行段
    hist = since[(dd < -0.10)]
    cur = int(since.iloc[-1])
    return {
        "days": cur,
        "pct": r(pct_of(hist, cur), 0),
        "hist_med": r(hist.median(), 0) if len(hist) else None,
        "hist_max": r(hist.max(), 0) if len(hist) else None,
    }


# ---------------------------------------------------------------- 事件
def load_events(prices):
    """事件表 = 项目既有 POLICY_EVENTS（底座）+ 应用数据/policy_events.csv（人工细化）。

    不再维护两套：cycle_events.py 覆盖 2005–2026 的全量事件，
    policy_events.csv 只补它没有的"动作类"细节（国家队 / 执法 / 高层定调），
    同日期以 CSV 的描述为准。
    """
    merged = {}
    try:
        from cycle_events import POLICY_EVENTS
        tmap = {"policy": "政策", "risk": "冲击", "top": "顶部",
                "bottom": "底部", "up": "节点", "now": "当前"}
        for e in POLICY_EVENTS:
            t = tmap.get(e.get("type"), "事件")
            if t == "当前":
                continue
            merged[e["date"]] = {"date": e["date"], "type": t,
                                 "title": e.get("label", ""), "note": ""}
    except Exception as ex:                                  # noqa: BLE001
        print("  ! cycle_events 读取失败：%s" % ex)

    if os.path.exists(EVENTS_CSV):
        e = pd.read_csv(EVENTS_CSV, parse_dates=["date"]).sort_values("date")
        for _, ev in e.iterrows():
            d = ev["date"].strftime("%Y-%m-%d")
            note = ev.get("note")
            merged[d] = {"date": d, "type": ev["type"], "title": ev["title"],
                         "note": "" if pd.isna(note) else str(note)}

    base = prices["沪深300"].dropna() if "沪深300" in prices else None
    rows = []
    for d in sorted(merged):
        rec = dict(merged[d])
        if base is not None and len(base):
            idx = base.index.searchsorted(pd.Timestamp(d))
            if idx < len(base):
                for h in (30, 60):
                    j = idx + h
                    rec["f%d" % h] = (r((base.iloc[j] / base.iloc[idx] - 1) * 100, 1)
                                      if j < len(base) else None)
        rows.append(rec)
    return rows


# ---------------------------------------------------------------- 结论
def build_verdict(market, indices, mcur):
    """把各维度压成一句人话的结论。

    这是**规则**，不是模型：只数"几个维度在极端区 + 资金在不在"，
    没有任何拟合参数，所以不会随样本漂移，也不会给出虚假的精确概率。
    """
    dims = [m for m in market if m.get("pct") is not None]
    ext = [m for m in dims if m["pct"] <= 5 or m["pct"] >= 95]
    get = lambda k: next((m["pct"] for m in dims if m["key"] == k), None)  # noqa: E731

    nsf_pct = get("nsf")
    nsf_amt = mcur.get("nsf_amt") or 0
    sh = next((i for i in indices if i["name"] == "上证指数"), None)
    hs = next((i for i in indices if i["name"] == "沪深300"), None)
    cy = next((i for i in indices if i["name"] == "创业板指"), None)
    if not sh:
        return None

    # ---- 立场：只看两件事 —— 有多少维度在极端区、国家队在不在买
    if nsf_pct is not None and nsf_pct >= 80 and len(ext) >= 4:
        stance, tone = "可分批买入", "buy"
        do = "分 3–5 批，跌了加，涨了不追；单日大涨不加仓。"
    elif len(ext) >= 4:
        stance, tone = "底部区域，资金未确认", "watch"
        do = "先别加，等国家队净申购连续两周为正。"
    elif len(ext) <= 1:
        stance, tone = "不在极端区", "neutral"
        do = "没有明显的赔率优势，按原计划执行。"
    else:
        stance, tone = "偏冷，但未到极端", "watch"
        do = "小仓位试探，不加杠杆。"

    # ---- 四条事实（每条都能在下方表里查到）
    facts = [
        ("位置", "%d/%d 个维度在历史极端区（≤5%% 或 ≥95%%）" % (len(ext), len(dims))),
        ("资金", "国家队 20 日净申购 %+.0f 亿元，历史 %s 分位"
                 % (nsf_amt, "—" if nsf_pct is None else "%.0f" % nsf_pct)),
        ("估值", "沪深300 PB %s 分位 · 创业板 PE %s 分位" % (
            "—" if not hs or hs["score"]["pb_pct"] is None else "%.0f" % hs["score"]["pb_pct"],
            "—" if not cy or cy["score"]["pe_pct"] is None else "%.0f" % cy["score"]["pe_pct"])),
        ("幅度", "上证 %s%% · 创业板 %s%%，下行已 %d 个交易日" % (
            ("%+.1f" % sh["cur"]["dd250"]).replace("-", "−"),
            ("%+.1f" % (cy["cur"]["dd250"] if cy else 0)).replace("-", "−"),
            sh["phase"]["days"])),
    ]

    wins = [i["d30"]["win"] for i in indices if i["d30"].get("ok")]
    risk = ("同档历史 30 日胜率 %d–%d%%，不是 100%%——这是赔率占优，不是确定性。"
            % (min(wins), max(wins))) if wins else \
           "样本不足，不给胜率。"

    return {"stance": stance, "tone": tone, "facts": facts, "do": do, "risk": risk}


# ---------------------------------------------------------------- 主流程
def main():
    px = load_prices()
    val = load_valuation()
    mcur, mhist = load_market()
    events = load_events(px)
    asof = px.index[-1]

    # ---- 全市场维度
    market = []
    spec = [
        ("nsf", "国家队净申购 · 20日", "%", "份额口径，越正＝买得越多", False),
        ("breadth", "200日均线上方占比", "%", "越低＝越接近底部", False),
        ("winner", "全市场获利比例", "%", "越低＝套牢越重", False),
        ("amount_z", "成交额 vs 60日均", "%", "放量＝情绪释放", False),
        ("newhl", "新高 − 新低 家数", "家", "为负＝仍在恶化", False),
        ("limit_down", "跌停家数", "家", "恐慌的直接读数", False),
        ("margin_chg20", "两融余额 · 20日", "%", "快降＝被动去杠杆", False),
    ]
    for key, name, unit, desc, _ in spec:
        v = mcur.get(key)
        if v is None:
            continue
        h = mhist.get(key)
        dim = {
            "key": key, "name": name, "value": r(v, 2), "unit": unit, "desc": desc,
            "pct": r(pct_of(h, v), 0) if h is not None else None,
            "hist_med": r(h.median(), 2) if h is not None else None,
            "hist_min": r(h.min(), 2) if h is not None else None,
            "hist_max": r(h.max(), 2) if h is not None else None,
        }
        # 数据自身的截止日期：过期太久必须标出来，否则 88% 分位是假的
        if key == "nsf":
            dim["sub"] = "20日净申购 %+.0f 亿元" % mcur.get("nsf_amt", 0)
            ds = mcur.get("nsf_date")
            if ds:
                dim["data_asof"] = ds
                dim["stale"] = (asof - pd.Timestamp(ds)).days > 10
        if key == "winner":
            ds = mcur.get("winner_date")
            if ds:
                dim["data_asof"] = ds
                dim["stale"] = (asof - pd.Timestamp(ds)).days > 15
        market.append(dim)

    # ---- 各指数
    indices = []
    for name in px.columns:
        s = px[name].dropna()
        if len(s) < 300:
            continue
        dd = s / s.rolling(250, min_periods=120).max() - 1
        cur_dd = float(dd.iloc[-1])
        price = float(s.iloc[-1])
        v = val.get(name, {})

        rec = {
            "name": name, "desc": IDX_DESC.get(name, ""),
            "cur": {
                "price": r(price, 1),
                "dd250": r(cur_dd * 100, 1),
                "ddall": r((price / s.max() - 1) * 100, 1),
                "ma200": r((price / s.iloc[-200:].mean() - 1) * 100, 1),
                "range250": r((s.iloc[-250:] < price).mean() * 100, 0),
            },
            "score": {
                "dd": r(pct_of(dd, cur_dd), 0),
                "pb": v.get("pb"), "pb_pct": v.get("pb_pct"),
                "pe": v.get("pe"), "pe_pct": v.get("pe_pct"),
                "val_date": v.get("date"),
            },
            "phase": phase_len(s, dd),
            "d30": bucket_dist(s, dd, cur_dd, 30),
            "d60": bucket_dist(s, dd, cur_dd, 60),
        }
        indices.append(rec)

    # ---- 事件：最近的 8 条 + 近 60/120 日计数
    recent = sorted(events, key=lambda x: x["date"])[-8:]
    for e in recent:
        e["days_ago"] = int((asof - pd.Timestamp(e["date"])).days)
    n60 = sum(1 for e in events if (asof - pd.Timestamp(e["date"])).days <= 60)
    n120 = sum(1 for e in events if (asof - pd.Timestamp(e["date"])).days <= 120)

    # ---- 国家队时序（给前端画双栏图：上指数、下净申购）
    nsf_series = None
    ns, na = mhist.get("nsf"), mhist.get("nsf_amt")
    if ns is not None and len(ns):
        nsf_series = {
            "dates": [d.strftime("%Y-%m-%d") for d in ns.index],
            "pct": [r(v, 1) for v in ns.values],
            "amt": [r(v, 0) for v in na.reindex(ns.index).values] if na is not None else [],
        }
    # 多指数国家队流（build_nsf.py 的宽表）
    nsf_all = None
    fp = os.path.join(CACHE_DIR, "nsf_flow.csv")
    if os.path.exists(fp):
        n = pd.read_csv(fp, parse_dates=["trade_date"]).sort_values("trade_date").set_index("trade_date")
        nsf_all = {}
        for name in ["沪深300", "中证500", "中证1000", "创业板指", "科创50"]:
            pc, am = "pct_" + name, "amt_" + name
            if pc not in n.columns:
                continue
            sub = n[[pc, am]].dropna(subset=[pc]) if am in n.columns else n[[pc]].assign(**{am: None}).dropna(subset=[pc])
            nsf_all[name] = {
                "dates": [d.strftime("%Y-%m-%d") for d in sub.index],
                "pct": [r(v, 1) for v in sub[pc].values],
                "amt": [None if pd.isna(v) else r(v, 0) for v in sub[am].values],
            }

    payload = {
        "asof": asof.strftime("%Y-%m-%d"),
        "verdict": build_verdict(market, indices, mcur),
        "market": market,
        "indices": indices,
        "nsf": nsf_series,
        "nsf_all": nsf_all,
        "meta": {
            "bucket": BUCKET, "min_n": MIN_N,
            "note": "分布为同一回撤档（±7.5pp）下的历史收益，样本重叠，seg 为独立片段数。",
        },
    }
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_state_score.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.state_score=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")

    # ---- 控制台摘要
    print("asof %s  →  %s" % (payload["asof"], OUT_JS))
    print("\n全市场维度：")
    for m in market:
        print("  %-22s %10.2f %-3s  分位 %s%%" %
              (m["name"], m["value"], m["unit"],
               "—" if m["pct"] is None else "%.0f" % m["pct"]))
    print("\n各指数：")
    print("  %-8s %8s %8s %6s %6s %6s   %-22s %-22s" %
          ("指数", "现价", "回撤250", "回撤分位", "PB分位", "PE分位", "30日同档", "60日同档"))
    for i in indices:
        c, d30, d60 = i["cur"], i["d30"], i["d60"]
        def fmt(d):
            if not d.get("ok"):
                return "n=%d 不足" % d.get("n", 0)
            return "胜%s%% 中位%+.1f%% n=%d" % (d["win"], d["med"], d["n"])
        print("  %-8s %8.1f %7.1f%% %5s%% %5s%% %5s%%   %-24s %-24s" %
              (i["name"], c["price"], c["dd250"],
               "—" if i["score"]["dd"] is None else "%.0f" % i["score"]["dd"],
               "—" if i["score"]["pb_pct"] is None else "%.0f" % i["score"]["pb_pct"],
               "—" if i["score"]["pe_pct"] is None else "%.0f" % i["score"]["pe_pct"],
               fmt(d30), fmt(d60)))
    print("\n事件表 %d 条，近 60 日 %d 条 / 近 120 日 %d 条；最近一条 %s"
          % (len(events), n60, n120, recent[-1]["date"] if recent else "—"))


if __name__ == "__main__":
    main()
