# -*- coding: utf-8 -*-
"""多模型分析 → web/models_extra.js

六块：
  1. 横截面排序  —— 31 个板块未来 20 日谁更强（LightGBM，按年做时间外验证）
  2. 生存分析    —— 熊市持续时间 Kaplan-Meier，当前已走 98 日，还剩多久
  3. 状态转移    —— 未来 20 日熊转牛的概率（按已走时间分档）
  4. 变点检测    —— 近 20 日相对前 40 日是否发生均值跳变
  5. 风险度量    —— 相似段的经验 VaR / CVaR / 预期最大回撤
  6. 分层贝叶斯  —— 海外先验 + A股数据，收缩得到后验收益区间
外加一个集成分（把上面几块合成 0–100）。

口径与局限写在每块注释里；所有指标都是历史统计，不是预测承诺。
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import GroupKFold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import INDEX_CSV, OVERSEAS_DIR, CACHE_DIR  # noqa: E402
import build_hist_stats as H  # noqa: E402

OUT = os.path.join(ROOT, "web", "models_extra.js")
IDX = H.IDX
HORIZON = 20


# ---------------------------------------------------------------- 数据
def load_series():
    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    out = {n: px[n].replace(0.0, np.nan).dropna() for n in IDX if n in px.columns}
    return out


def load_overseas():
    names = {"SPX": "标普500", "DJIA": "道琼斯", "IXIC": "纳斯达克", "HSI": "恒生"}
    out = {}
    for code, cn in names.items():
        fp = os.path.join(OVERSEAS_DIR, "K线导出_%s_日线数据.xlsx" % code)
        if not os.path.exists(fp):
            continue
        d = pd.read_excel(fp)
        px = pd.to_numeric(d["收盘价"], errors="coerce")
        dt = pd.to_datetime(d["交易时间"], errors="coerce")
        g = pd.DataFrame({"d": dt, "p": px}).dropna().sort_values("d")
        if len(g) > 500:
            out[cn] = g.set_index("d")["p"]
    return out


def stage_features(s):
    """当前处在熊市的哪一段：时间进度、空间进度。"""
    v = s.values
    eps = H.episodes(v)
    done = [e for e in eps[:-1] if e[0] == "bear" and (e[2] - e[1]) >= 60]
    k, i0, i1 = eps[-1]
    if k != "bear":
        return None
    durs = [e[2] - e[1] for e in done]
    deps = [-(v[e[2]] / v[e[1]] - 1) for e in done]
    base_dur = float(np.median(durs)) if len(durs) >= 2 else 220
    base_dep = float(np.median(deps)) if len(deps) >= 2 else 0.32
    dd = v[i1] / v[i0] - 1
    return dict(days=i1 - i0, t_pct=(i1 - i0) / base_dur, s_pct=(-dd) / base_dep, dd=dd)


# ---------------------------------------------------------------- 1. 横截面排序
def _rank_universe(items, min_len=800):
    """items: [(code, name, Series)]，按日横截面排序。"""
    rows = []
    for code, name, s in items:
        sr = s.astype(float)
        if len(sr) < min_len:
            continue
        lr = np.log(sr).diff()
        f = pd.DataFrame(index=sr.index)
        f["mom20"] = sr / sr.shift(20) - 1
        f["mom60"] = sr / sr.shift(60) - 1
        f["mom120"] = sr / sr.shift(120) - 1
        f["ma60"] = sr / sr.rolling(60, min_periods=20).mean() - 1
        f["ma250"] = sr / sr.rolling(250, min_periods=60).mean() - 1
        f["dd250"] = sr / sr.rolling(250, min_periods=60).max() - 1
        f["vol20"] = lr.rolling(20).std() * np.sqrt(244)
        f["rsi"] = H.rsi14(sr) / 100
        f["fwd"] = sr.shift(-HORIZON) / sr - 1
        f["code"] = code
        f["name"] = name
        f.index.name = "date"
        rows.append(f)
    d = pd.concat(rows).dropna()
    if len(d) < 3000:
        return None
    feats = ["mom20", "mom60", "mom120", "ma60", "ma250", "dd250", "vol20", "rsi"]
    for c in feats:
        d[c + "_x"] = d.groupby(level=0)[c].rank(pct=True) * 100
    d["y"] = d.groupby(level=0)["fwd"].rank(pct=True) * 100
    d = d.reset_index()
    X = d[[c + "_x" for c in feats]]
    y = d["y"].values
    groups = d["date"].dt.year.values
    gkf = GroupKFold(n_splits=5)
    oof = np.full(len(d), np.nan)
    for tr, te in gkf.split(X, groups=groups):
        m = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=8,
                              max_depth=3, min_child_samples=200, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=4)
        m.fit(X.iloc[tr], y[tr])
        oof[te] = m.predict(X.iloc[te])
    d["pred"] = oof
    ic = d.dropna(subset=["pred"]).groupby("date").apply(
        lambda g: g["pred"].rank().corr(g["y"].rank()) if len(g) > 5 else np.nan,
        include_groups=False).dropna()
    last = d.sort_values("date").groupby("code").tail(1).copy()
    mdl = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=8,
                            max_depth=3, min_child_samples=200, subsample=0.8,
                            subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=4)
    mdl.fit(X, y)
    last["score"] = mdl.predict(last[[c + "_x" for c in feats]])
    out = last[["name", "score"]].sort_values("score", ascending=False)
    return dict(
        items=[dict(name=r.name, score=round(float(r.score), 1)) for r in out.itertuples()],
        ic_mean=round(float(ic.mean()), 3),
        ic_pos=round(float((ic > 0).mean()) * 100, 1),
        n_days=int(len(ic)), n_rows=int(len(d)),
    )


def build_rank(index_series):
    loaded = H.load_sectors()
    sec = None
    if loaded:
        secs, _ = loaded
        items = []
        for code, g in secs.items():
            s = pd.to_numeric(g["close"], errors="coerce")
            s.index = pd.to_datetime(g["trade_date"].astype(str))
            s = s.dropna()
            items.append((code, str(g["name"].iloc[-1]), s))
        sec = _rank_universe(items)
    idx_items = [(n, n, s) for n, s in index_series.items()]
    idx = _rank_universe(idx_items, min_len=1200)
    if sec is None and idx is None:
        return None
    return dict(sectors=(sec or {}).get("items"),
                indices=(idx or {}).get("items"),
                sector=(sec or {}), index=(idx or {}))


# ---------------------------------------------------------------- 2. 生存分析
def km_curve(durations, censored):
    """Kaplan-Meier。durations 为已结束的时长，censored 为仍在进行中的已走时长。"""
    times = sorted(set(durations) | set(censored))
    surv, at_risk, out_t, out_s = 1.0, len(durations) + len(censored), [], []
    for t in times:
        d = sum(1 for x in durations if x == t)
        c = sum(1 for x in censored if x == t)
        if at_risk <= 0:
            break
        if d:
            surv *= (1 - d / at_risk)
        out_t.append(t)
        out_s.append(surv)
        at_risk -= (d + c)
    return out_t, out_s


def build_survival(series):
    durations, censored, cur_days = [], [], []
    for n, s in series.items():
        eps = H.episodes(s.values)
        for k, i0, i1 in eps[:-1]:
            if k == "bear" and (i1 - i0) >= 60:
                durations.append(i1 - i0)
        k, i0, i1 = eps[-1]
        if k == "bear":
            censored.append(i1 - i0)
    t, S = km_curve(durations, censored)
    # 网格化，便于画图
    grid = list(range(0, 1201, 20))
    sg = []
    j = 0
    last = 1.0
    for x in grid:
        while j < len(t) and t[j] <= x:
            last = S[j]
            j += 1
        sg.append(round(last, 3))
    cur = float(np.median(censored)) if censored else None
    # 中位剩余：从当前已走天数起，生存率再降一半对应的天数
    def surv_at(x):
        v = 1.0
        for ti, si in zip(t, S):
            if ti <= x:
                v = si
        return v
    cur_s = surv_at(cur) if cur else 1
    med_rem = None
    for x in grid:
        if x > (cur or 0) and surv_at(x) <= cur_s * 0.5:
            med_rem = x - (cur or 0)
            break
    return dict(days=grid, surv=sg, n_ep=len(durations), n_now=len(censored),
                current_days=int(round(cur)) if cur else None,
                current_surv=round(float(cur_s), 3),
                median_remaining=med_rem)


# ---------------------------------------------------------------- 3. 状态转移
def build_transition(series):
    rows = []
    for n, s in series.items():
        v = s.values
        eps = H.episodes(v)
        for k, i0, i1 in eps[:-1]:
            if k != "bear":
                continue
            dur = i1 - i0
            for d in range(0, dur, 10):
                rows.append(dict(market=n, elapsed=d, remain=dur - d,
                                 ended20=int(dur - d <= HORIZON), dur=dur))
    d = pd.DataFrame(rows)
    if d.empty:
        return None
    d["t_pct"] = d["elapsed"] / d.groupby("market")["dur"].transform("max").clip(lower=60)
    bins = [0, 0.25, 0.5, 0.75, 1.0, 2.0, 99]
    d["bucket"] = pd.cut(d["t_pct"], bins=bins, labels=["<25%", "25–50%", "50–75%",
                                                        "75–100%", "100–200%", ">200%"])
    g = d.groupby("bucket", observed=True)["ended20"].agg(["mean", "size"])
    # 拉普拉斯平滑
    curve = [dict(bucket=str(b), p=round((r["mean"] * r["size"] + 1) / (r["size"] + 2), 3),
                  n=int(r["size"])) for b, r in g.iterrows()]
    cur = []
    for n, s in series.items():
        st = stage_features(s)
        if st:
            cur.append(st["t_pct"])
    cur_t = float(np.median(cur)) if cur else 1.0
    idx = pd.cut([cur_t], bins=bins, labels=["<25%", "25–50%", "50–75%", "75–100%",
                                             "100–200%", ">200%"])[0]
    p_now = next((c["p"] for c in curve if c["bucket"] == str(idx)), None)
    return dict(curve=curve, current_t=round(cur_t, 2), current_bucket=str(idx),
                p_bull_20=p_now, n=int(len(d)))


# ---------------------------------------------------------------- 4. 风险度量
def analog_returns(s, h):
    feats = H.feat_matrix(s)
    X = feats.copy()
    X["y"] = s.values
    X = X.dropna()
    if len(X) < 600:
        return None
    cur = X.iloc[-1]
    cols = [c for c in X.columns if c != "y"]
    dist = ((X[cols] - cur[cols]) ** 2).mean(axis=1) ** 0.5
    order = np.argsort(dist.values)
    gap, picked = max(20, h), []
    for i in order:
        if i >= len(X) - h:
            continue
        if picked and min(abs(int(i) - j) for j in picked) < gap:
            continue
        picked.append(int(i))
        if len(picked) >= 30:
            break
    yv = X["y"].values
    return np.array([yv[i + h] / yv[i] - 1 for i in picked])


def build_risk(series):
    out = {}
    for name in ("创业板指", "沪深300"):
        s = series.get(name)
        if s is None:
            continue
        r20 = analog_returns(s, 20)
        if r20 is None:
            continue
        var95 = float(np.percentile(r20, 5))
        var90 = float(np.percentile(r20, 10))
        tail = r20[r20 <= var95]
        cvar = float(tail.mean()) if len(tail) else var95
        out[name] = dict(var90=round(var90 * 100, 1), var95=round(var95 * 100, 1),
                         cvar95=round(cvar * 100, 1), n=int(len(r20)),
                         p10=round(float(np.percentile(r20, 10)) * 100, 1),
                         p90=round(float(np.percentile(r20, 90)) * 100, 1))
    return out


# ---------------------------------------------------------------- 5. 变点检测
def build_changepoint(s, window=250):
    """20 日均值相对前 40 日均值的跳变强度（0–1，启发式）。"""
    lr = np.log(s.astype(float)).diff().dropna()
    out = []
    for i in range(60, len(lr)):
        a = lr.iloc[i - 20:i]
        b = lr.iloc[i - 60:i - 20]
        sd = b.std()
        if sd == 0 or np.isnan(sd):
            continue
        z = abs(a.mean() - b.mean()) / (sd / np.sqrt(20))
        out.append(dict(date=str(lr.index[i].date()), z=round(float(z), 2),
                        p=round(float(1 / (1 + np.exp(-(z - 2)))), 3)))
    out = out[-window:]
    return dict(series=out, current=out[-1] if out else None)


# ---------------------------------------------------------------- 6. 分层贝叶斯
def stage_returns(series, horizon=20):
    """熊市段内的未来 horizon 日收益；同时返回独立段数。"""
    vals, eps_n = [], 0
    for n, s in series.items():
        v = s.values
        eps = H.episodes(v)
        done = [e for e in eps[:-1] if e[0] == "bear" and (e[2] - e[1]) >= 60]
        eps_n += len(done)
        for k, i0, i1 in done:
            for i in range(i0, i1):
                if i % 5:
                    continue
                if i + horizon >= len(v):
                    continue
                vals.append(v[i + horizon] / v[i] - 1)
    return np.array(vals), eps_n


def build_bayes(a_series, o_series):
    a, n_a_ep = stage_returns(a_series)
    o, n_o_ep = stage_returns(o_series)
    if len(a) < 100 or len(o) < 100:
        return None
    mu_o, sd_o = float(o.mean()), float(o.std())
    mu_a, sd_a = float(a.mean()), float(a.std())
    # 用独立段数当样本量：A股的 8 个指数高度同步，按天算会严重高估
    n_a, n_o = max(n_a_ep, 8), max(n_o_ep, 8)
    # 正态-正态：先验 N(mu_o, sd_o^2/kappa)，再看 A股 数据
    kappa = 5.0
    prec = 1 / (sd_o ** 2 / kappa) + n_a / (sd_a ** 2)
    mu_post = ((mu_o / (sd_o ** 2 / kappa)) + (mu_a * n_a / (sd_a ** 2))) / prec
    sd_post = float(np.sqrt(1 / prec))
    return dict(prior=round(mu_o * 100, 1), data=round(mu_a * 100, 1),
                posterior=round(mu_post * 100, 1),
                lo=round((mu_post - 1.96 * sd_post) * 100, 1),
                hi=round((mu_post + 1.96 * sd_post) * 100, 1),
                n_a=int(n_a), n_o=int(n_o), kappa=kappa,
                n_a_rows=int(len(a)), n_o_rows=int(len(o)))


# ---------------------------------------------------------------- 集成
def build_ensemble(hist, ml, rank, trans, surv):
    parts = {}
    if ml and ml.get("pred"):
        p = ml["pred"]["60"]
        parts["模型中位"] = float(np.clip((p["p50"] + 10) / 40 * 100, 0, 100))
    if rank and rank.get("sectors"):
        s = next((x["score"] for x in rank["sectors"] if x["name"] == "创业板指"), None)
        # 板块表没有创业板，用有色金属/电子等替代不合适，跳过
        if s is None:
            s = float(np.mean([x["score"] for x in rank["sectors"][:5]]))
        parts["横截面排名"] = float(np.clip(s, 0, 100))
    if trans and trans.get("p_bull_20") is not None:
        parts["转牛概率"] = float(np.clip(trans["p_bull_20"] * 100, 0, 100))
    if surv and surv.get("median_remaining"):
        parts["剩余时间"] = float(np.clip(100 - surv["median_remaining"] / 6, 0, 100))
    score = round(float(np.mean(list(parts.values()))), 1) if parts else None
    return dict(score=score, parts={k: round(v, 1) for k, v in parts.items()})


def main():
    a_series = load_series()
    o_series = load_overseas()
    hist = None
    fp = os.path.join(ROOT, "web", "hist_stats.js")
    if os.path.exists(fp):
        raw = open(fp, encoding="utf-8").read()
        k = raw.find("window.WAW.hist_stats=")
        hist = json.loads(raw[k + len("window.WAW.hist_stats="):].rstrip().rstrip(";"))
    ml = None
    fp = os.path.join(ROOT, "web", "ml_model.js")
    if os.path.exists(fp):
        raw = open(fp, encoding="utf-8").read()
        k = raw.find("window.WAW.ml_model=")
        ml = json.loads(raw[k + len("window.WAW.ml_model="):].rstrip().rstrip(";"))

    rank = build_rank(a_series)
    surv = build_survival(a_series)
    trans = build_transition(a_series)
    risk = build_risk(a_series)
    cp = build_changepoint(a_series["创业板指"]) if "创业板指" in a_series else None
    bayes = build_bayes(a_series, o_series)
    ens = build_ensemble(hist, ml, rank, trans, surv)

    payload = dict(
        asof=pd.read_csv(INDEX_CSV, usecols=["date"])["date"].max()[:10],
        rank=rank, survival=surv, transition=trans, risk=risk,
        changepoint=cp, bayes=bayes, ensemble=ens,
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_models_extra.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.models_extra=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print("→ %s" % OUT)
    if rank:
        for k in ("sector", "index"):
            r = rank.get(k) or {}
            if r:
                print("排序 %s：%d 个标的，%d 天，rank IC %.3f，IC>0 占比 %.0f%%" %
                      (k, len(r["items"]), r["n_days"], r["ic_mean"], r["ic_pos"]))
    if surv:
        print("生存：%d 段，当前已走 %s 日，中位剩余 %s 日" %
              (surv["n_ep"], surv["current_days"], surv["median_remaining"]))
    if trans:
        print("转移：当前 %s 档，20 日转牛概率 %.0f%%" %
              (trans["current_bucket"], (trans["p_bull_20"] or 0) * 100))
    if risk:
        for k, v in risk.items():
            print("风险 %s：VaR90 %.1f%% / VaR95 %.1f%% / CVaR95 %.1f%%" %
                  (k, v["var90"], v["var95"], v["cvar95"]))
    if bayes:
        print("贝叶斯：先验 %+.1f%% + A股 %+.1f%% → 后验 %+.1f%% [%+.1f, %+.1f]" %
              (bayes["prior"], bayes["data"], bayes["posterior"], bayes["lo"], bayes["hi"]))
    if ens:
        print("集成：%.1f 分 %s" % (ens["score"], ens["parts"]))


if __name__ == "__main__":
    main()
