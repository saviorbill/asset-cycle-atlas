# -*- coding: utf-8 -*-
"""当前结论 → web/conclusion.js

回答四个问题（都不依赖预测模型，全部是可复算的历史统计）：
  1) 现在牛还是熊        —— 各指数 20% 反转的实时分段
  2) 到了熊市哪一段      —— 时间（已经跌了多久）与空间（已经跌了多深）两个分位
  3) 布局胜率 / 推荐谁   —— 读 build_state_score.py 的同档 30/60 日分布
  4) 跌最深的会不会反弹最强 —— 历史 7 轮熊市里各指数跌幅与见底后 60 日反弹的排名
另附：熊市反弹的幅度/时间定义（业内惯例 + 本地数据实测分布）
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import INDEX_CSV  # noqa: E402

DAILY = INDEX_CSV
STATE = os.path.join(ROOT, "web", "state_score.js")
OUT = os.path.join(ROOT, "web", "conclusion.js")

THR = 0.20          # 牛熊反转阈值：从极值回撤/反弹 20%
MIN_BEAR = 60       # 只把 ≥60 个自然日的熊市段计入历史样本
RALLY = 0.05        # 熊市段内 ≥5% 才算一次像样的反弹


# ---------------------------------------------------------------- 分段
def episodes(s, thr=THR):
    """实时 20% 反转分段（无未来函数）。返回 [(kind, i0, i1)]"""
    vals = s.values
    if len(vals) < 50:
        return []
    segs, trend = [], None
    ext_i, ext_px, last_i = 0, vals[0], 0
    for i in range(1, len(vals)):
        p = vals[i]
        if trend is None:
            if p > ext_px * (1 + thr):
                trend = "bull"
                segs.append(("bull", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
            elif p < ext_px * (1 - thr):
                trend = "bear"
                segs.append(("bear", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
            elif p > ext_px:
                ext_px, ext_i = p, i
            continue
        if trend == "bull":
            if p > ext_px:
                ext_px, ext_i = p, i
            elif p <= ext_px * (1 - thr):
                segs.append(("bull", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
                trend = "bear"
        else:
            if p < ext_px:
                ext_px, ext_i = p, i
            elif p >= ext_px * (1 + thr):
                segs.append(("bear", last_i, ext_i)); last_i, ext_px, ext_i = ext_i, p, i
                trend = "bull"
    segs.append((trend or "bull", last_i, len(vals) - 1))
    return segs


def load_ml():
    """读 build_ml_model.py 产出的模型结果；没有就返回空 dict。"""
    fp = os.path.join(ROOT, "web", "ml_model.js")
    if not os.path.exists(fp):
        return {}
    try:
        raw = open(fp, encoding="utf-8").read()
        k = raw.find("window.WAW.ml_model=")
        return json.loads(raw[k + len("window.WAW.ml_model="):].rstrip().rstrip(";"))
    except Exception as e:
        print("模型读取失败：%s" % e)
        return {}


def zigzag(v, thr=RALLY):
    """段内 ≥thr 的低→高反弹：[(i_low, i_high, gain)]"""
    out, low_i, high_i = [], 0, 0
    low = high = v[0]
    up = False
    for i in range(1, len(v)):
        p = v[i]
        if not up:
            if p < low:
                low, low_i = p, i
            elif p >= low * (1 + thr):
                up, high, high_i = True, p, i
                out.append((low_i, high_i, high / low - 1))
        else:
            if p > high:
                high, high_i = p, i
            elif p <= high * (1 - thr):
                up, low, low_i = False, p, i
    return out


# ---------------------------------------------------------------- 主流程
def main():
    d = pd.read_csv(DAILY, parse_dates=["date"]).set_index("date").sort_index()
    d = d.replace(0.0, np.nan)
    idxs = [c for c in d.columns if d[c].notna().sum() > 500]

    # ---- 1. 牛熊状态 + 时间/空间分位
    rows = []
    for name in idxs:
        s = d[name].dropna()
        eps = episodes(s)
        cur = eps[-1]
        k0, i0, i1 = cur
        cur_days = i1 - i0
        chg = s.iloc[i1] / s.iloc[i0] - 1
        bears = [e for e in eps[:-1] if e[0] == "bear"]
        dur = np.array([b[2] - b[1] for b in bears if (b[2] - b[1]) > 2])
        dep = np.array([-(s.iloc[b[2]] / s.iloc[b[1]] - 1) for b in bears if (b[2] - b[1]) > 2])
        if k0 == "bear":
            t_pct = float((dur < cur_days).mean() * 100) if len(dur) else None
            s_pct = float((dep < -chg).mean() * 100) if len(dep) else None
        else:
            t_pct = s_pct = None
        rows.append(dict(
            name=name, kind=k0, days=int(cur_days),
            chg=round(chg * 100, 1),
            from_date=s.index[i0].strftime("%Y-%m-%d"),
            time_pct=None if t_pct is None else round(t_pct),
            space_pct=None if s_pct is None else round(s_pct),
            hist_bear_n=len(bears),
            hist_dur_med=int(np.median(dur)) if len(dur) else None,
            hist_dep_med=round(float(np.median(dep)) * 100, 1) if len(dep) else None,
            hist_dur_max=int(dur.max()) if len(dur) else None,
            hist_dep_max=round(float(dep.max()) * 100, 1) if len(dep) else None,
        ))

    bears_now = [r for r in rows if r["kind"] == "bear"]
    bulls_now = [r for r in rows if r["kind"] == "bull"]

    # 综合阶段：以在熊市中的指数为样本，取时间/空间中位
    tp = [r["time_pct"] for r in bears_now if r["time_pct"] is not None]
    sp = [r["space_pct"] for r in bears_now if r["space_pct"] is not None]
    stage_t = float(np.median(tp)) if tp else 0
    stage_s = float(np.median(sp)) if sp else 0
    if stage_t < 40 and stage_s < 40:
        stage, stage_note = "早期", "时间与空间都还没走完"
    elif stage_t > 65 and stage_s > 65:
        stage, stage_note = "后期", "时间与空间都已超过历史上多数熊市"
    elif stage_s > 75 and stage_t <= 65:
        stage, stage_note = "中后期", "跌幅已经很深，但时间还没磨够"
    elif stage_t > 75 and stage_s <= 65:
        stage, stage_note = "中后期", "时间拖得够久了，但跌幅仍不算深"
    else:
        stage, stage_note = "中期", "时间与空间都在历史中位附近"

    # ---- 2. 胜率 / 推荐（读 state_score 的同档分布）
    ss = None
    if os.path.exists(STATE):
        raw = open(STATE, encoding="utf-8").read()
        k = raw.find("window.WAW.state_score=")
        ss = json.loads(raw[k + len("window.WAW.state_score="):].rstrip().rstrip(";"))
        if ss.get("state_score"):
            ss = ss["state_score"]
    picks = []
    if ss:
        by_name = {x["name"]: x for x in ss.get("indices", [])}
        for r in rows:
            x = by_name.get(r["name"])
            r["dd250"] = None if not x else x["cur"].get("dd250")
            r["pb_pct"] = None if not x else x["score"].get("pb_pct")
        for x in ss.get("indices", []):
            d30, d60 = x.get("d30") or {}, x.get("d60") or {}
            if not (d30.get("ok") and d60.get("ok")):
                continue
            if d30.get("seg", 0) < 3 or d60.get("seg", 0) < 3:
                continue
            picks.append(dict(
                name=x["name"], desc=x.get("desc", ""),
                w30=d30["win"], m30=d30["med"], n30=d30["n"], s30=d30["seg"],
                w60=d60["win"], m60=d60["med"], n60=d60["n"], s60=d60["seg"],
                q10=d30.get("q10"), q25=d30.get("q25"), q75=d30.get("q75"), q90=d30.get("q90"),
                dd=x["cur"].get("dd250"),
                pb=x["score"].get("pb_pct"),
            ))
    # 胜率向 50% 收缩：只有 5 段的 70% 和 20 段的 70% 不是一回事
    for p in picks:
        for k in ("30", "60"):
            w = p["w" + k]; sg = p["s" + k]
            p["a" + k] = round(50 + (w - 50) * sg / (sg + 3.0), 1)
        p["score"] = p["a60"] * 0.6 + p["a30"] * 0.4
    picks.sort(key=lambda p: -p["score"])
    best = picks[0] if picks else None

    # 组合口径：同档胜率按独立片段数加权（按天数加权会让同一轮熊市被重复计数）
    if picks:
        st = sum(p["s30"] for p in picks) or 1
        w30 = sum(p["w30"] * p["s30"] for p in picks) / st
        m30 = sum(p["m30"] * p["s30"] for p in picks) / st
        st6 = sum(p["s60"] for p in picks) or 1
        w60 = sum(p["w60"] * p["s60"] for p in picks) / st6
        m60 = sum(p["m60"] * p["s60"] for p in picks) / st6
        lo30, hi30 = min(p["w30"] for p in picks), max(p["w30"] for p in picks)
        lo60, hi60 = min(p["w60"] for p in picks), max(p["w60"] for p in picks)
    else:
        w30 = m30 = w60 = m60 = lo30 = hi30 = lo60 = hi60 = None

    # ---- 2b. 与机器学习模型合成：规则给方向和标的，模型给概率
    mix = None
    if best:
        ml = load_ml()
        p = (ml.get("all_preds") or {}).get(best["name"], {}).get("60") if ml else None
        if p:
            rule_s = round(float(best["a60"]), 1)
            ml_s = round(float(p["pup"]), 1)
            combined = round(0.65 * rule_s + 0.35 * ml_s, 1)
            agree = bool((rule_s >= 50) == (ml_s >= 50))
            if agree and combined >= 65:
                conf = "高"
            elif agree and combined >= 55:
                conf = "中"
            elif not agree and combined >= 60:
                conf = "中"
            else:
                conf = "低"
            mix = dict(rule=rule_s, ml=ml_s, combined=combined, agree=agree,
                       confidence=conf, med=p["p50"], p10=p["p10"], p90=p["p90"],
                       skill=(ml.get("skill") or {}).get("60"),
                       n_ep=ml.get("n_ep"), n_rows=ml.get("n_rows"))

    # 一句话立场：有模型时取合成分，否则退回规则分
    score = mix["combined"] if mix else (best["a60"] if best else None)
    if best and score is not None:
        if score >= 60:
            stance, tone = "可分批买入", "buy"
            do = "分 3–5 批买 %s；跌了加，涨了不追，单日大涨不加仓。" % best["name"]
        elif score >= 52:
            stance, tone = "可小仓位试探", "watch"
            do = "先用三分之一仓位试 %s，连续 5 个交易日不创新低再加。" % best["name"]
        else:
            stance, tone = "等待，暂不加仓", "wait"
            do = "先不动，等同档胜率回到 55% 以上、或国家队净申购连续两周为正。"
    else:
        stance, tone, do = "样本不足，暂不判断", "wait", "等样本补足再看。"

    # ---- 3. 历史熊市：跌幅 vs 反弹（Q4）
    master = [e for e in episodes(d["上证指数"].dropna())
              if e[0] == "bear" and (e[2] - e[1]) >= MIN_BEAR]
    hist = []
    panel_dd, panel_reb = [], []
    hit = 0
    for k0, i0, i1 in master:
        d0, d1 = d.index[i0], d.index[i1]
        w = d.loc[d0:d1]
        recs = {}
        for name in idxs:
            s = w[name].dropna()
            if len(s) < 40:
                continue
            pk = s.idxmax(); trd = s.idxmin()
            if trd <= pk:
                continue
            dd = s.loc[trd] / s.loc[pk] - 1
            after = d[name].loc[trd:].head(61).dropna()
            if len(after) < 6:
                continue
            recs[name] = (dd, after.iloc[-1] / s.loc[trd] - 1)
        if len(recs) < 4:
            continue
        df = pd.DataFrame(recs, index=["dd", "reb"]).T
        deep = df["dd"].idxmin(); bestr = df["reb"].idxmax()
        hit += int(deep == bestr)
        for n, r in df.iterrows():
            panel_dd.append(r["dd"]); panel_reb.append(r["reb"])
        hist.append(dict(
            range="%s → %s" % (d0.strftime("%Y.%m"), d1.strftime("%Y.%m")),
            n=len(df), deep=deep, deep_dd=round(df.loc[deep, "dd"] * 100, 1),
            deep_reb=round(df.loc[deep, "reb"] * 100, 1),
            best=bestr, best_reb=round(df.loc[bestr, "reb"] * 100, 1),
            med_reb=round(df["reb"].median() * 100, 1),
            same=bool(deep == bestr),
        ))
    panel_rho = float(pd.Series(panel_dd).rank().corr(pd.Series(panel_reb).rank())) \
        if len(panel_dd) > 5 else None

    # ---- 4. 熊市反弹的幅度/时间分布（Q5）
    g, dy = [], []
    for name in idxs:
        s = d[name].dropna()
        for k0, i0, i1 in episodes(s):
            if k0 != "bear":
                continue
            seg = s.iloc[i0:i1 + 1]
            for lo, hi, gain in zigzag(seg.values):
                g.append(gain); dy.append(hi - lo)
    g = np.array(g); dy = np.array(dy)

    def share(t):
        return float((g >= t).mean() * 100) if len(g) else None

    rally = dict(
        n=int(len(g)),
        thr=int(RALLY * 100),
        med_gain=round(float(np.median(g)) * 100, 1),
        p75_gain=round(float(np.percentile(g, 75)) * 100, 1),
        p90_gain=round(float(np.percentile(g, 90)) * 100, 1),
        med_days=int(np.median(dy)),
        p75_days=int(np.percentile(dy, 75)),
        p90_days=int(np.percentile(dy, 90)),
        share10=round(share(0.10), 1) if len(g) else None,
        n10=int((g >= 0.10).sum()),
        n20=int((g >= 0.20).sum()),
    )

    # ---- 输出
    payload = dict(
        asof=d.index[-1].strftime("%Y-%m-%d"),
        indices=rows,
        n_total=len(rows), n_bear=len(bears_now), n_bull=len(bulls_now),
        stage=dict(label=stage, note=stage_note,
                   time_pct=round(stage_t), space_pct=round(stage_s)),
        stance=stance, tone=tone, do=do, mix=mix,
        win=dict(w30=round(w30, 1) if w30 is not None else None,
                 m30=round(m30, 1) if m30 is not None else None,
                 w60=round(w60, 1) if w60 is not None else None,
                 m60=round(m60, 1) if m60 is not None else None,
                 lo30=round(lo30) if lo30 is not None else None,
                 hi30=round(hi30) if hi30 is not None else None,
                 lo60=round(lo60) if lo60 is not None else None,
                 hi60=round(hi60) if hi60 is not None else None),
        picks=picks, best=best,
        bear_hist=hist, bear_hit=hit, bear_n=len(hist), bear_rho=round(panel_rho, 2) if panel_rho is not None else None,
        rally=rally,
        meta=dict(thr=THR, min_bear=MIN_BEAR, rally_thr=RALLY),
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_conclusion.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.conclusion=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")

    # ---- 控制台摘要
    print("asof %s → %s" % (payload["asof"], OUT))
    print("状态：熊 %d / 牛 %d | 阶段 %s（时间 %d%% · 空间 %d%%）" %
          (payload["n_bear"], payload["n_total"], stage, stage_t, stage_s))
    for r in rows:
        print("  %-6s %-4s %4d日 %+6.1f%%  时间%s 空间%s" % (
            r["name"], "熊" if r["kind"] == "bear" else "牛", r["days"], r["chg"],
            "—" if r["time_pct"] is None else "%3d%%" % r["time_pct"],
            "—" if r["space_pct"] is None else "%3d%%" % r["space_pct"]))
    if picks:
        print("胜率：30日 %.0f%% 中位 %+.1f%% | 60日 %.0f%% 中位 %+.1f%%" % (w30, m30, w60, m60))
        print("推荐：%s（60日 %.0f%% / 30日 %.0f%%）" % (best["name"], best["w60"], best["w30"]))
    if mix:
        print("合成：规则 %.0f + 模型 %.0f%% → %.0f（%s，置信度 %s）" %
              (mix["rule"], mix["ml"], mix["combined"],
               "同向" if mix["agree"] else "分歧", mix["confidence"]))
    print("熊市跌幅 vs 反弹：跌最深＝反弹最强 %d/%d 轮，面板 Spearman %s" %
          (hit, len(hist), payload["bear_rho"]))
    print("熊市反弹：≥%d%% 共 %d 次，中位 %.1f%% / %d 日；≥10%% 占 %.0f%%" %
          (rally["thr"], rally["n"], rally["med_gain"], rally["med_days"], rally["share10"]))


if __name__ == "__main__":
    main()
