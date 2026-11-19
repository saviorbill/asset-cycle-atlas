# -*- coding: utf-8 -*-
"""机器学习机制 → web/ml_model.js

做什么：把「熊市走到哪一步」映射到「未来 10–60 个交易日收益的分布」。
怎么学：只用熊市段内的日子当样本，特征全部是当日可观察的量，
        标签是未来收益的分位数，按「整段熊市」分组做样本外验证。

样本来自哪里（这是全部诚实性的前提）：
  海外 4 个指数 83 段熊市（标普 25 / 道指 30 / 纳指 13 / 恒生 15）
  A 股上证 7 段熊市
  → 90 段，约 1.6 万个熊市日。
  A 股只有 7 段，模型学到的「形状」主要来自海外，A 股数据的角色是校准。
  页面上必须把这句话原样写出来。

用法：python3 src/build_ml_model.py
"""
import os
import sys
import glob
import json

import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import INDEX_CSV, OVERSEAS_DIR, DATA_DIR, CACHE_DIR  # noqa: E402

OUT = os.path.join(ROOT, "web", "ml_model.js")

OVERSEAS_CODES = ["SPX", "DJIA", "IXIC", "HSI"]  # 生产默认；--overseas all 用全部

THR = 0.20            # 牛熊反转阈值
MIN_BEAR = 60         # 至少 60 个交易日才算一段熊市
HORIZONS = [10, 20, 30, 40, 50, 60]
QS = [0.10, 0.25, 0.50, 0.75, 0.90]
PRIOR_DUR = 220       # 结构先验：一段熊市约 220 个交易日（固定常数，不随样本变）
PRIOR_DEP = 0.32      # 结构先验：一段熊市的中位跌幅 32%
MIN_TRAIN = 2000      # 少于这么多行就不出结论

BASE_FEATS = ["t_pct", "s_pct", "dd", "mom20", "vol20", "log_days", "is_overseas"]


def build_external():
    """标普 VIX + A股本地的 30 天隐含波动率（50ETF/300ETF 期权反解）。"""
    frames = []
    fp = os.path.join(OVERSEAS_DIR, "K线导出_VIX_日线数据.xlsx")
    if os.path.exists(fp):
        d = pd.read_excel(fp)
        d["date"] = pd.to_datetime(d["交易时间"], errors="coerce")
        d["v"] = pd.to_numeric(d["收盘价"], errors="coerce")
        d = d.dropna(subset=["date", "v"]).sort_values("date").set_index("date")
        v = d["v"]
        f = pd.DataFrame(index=v.index)
        f["vix_log"] = np.log(v)
        f["vix_ret5"] = v / v.shift(5) - 1
        f["vix_pct"] = v.rolling(1250, min_periods=250).rank(pct=True)
        frames.append(f.reset_index())
    fp = os.path.join(CACHE_DIR, "iv_index.parquet")
    if os.path.exists(fp):
        iv = pd.read_parquet(fp)
        iv["date"] = pd.to_datetime(iv["date"])
        iv = iv.sort_values("date")
        x = pd.DataFrame({"date": iv["date"].values})
        av = pd.Series(iv["iv_avg"].values)
        x["iv_chg5"] = av / av.shift(5) - 1
        x["iv_pct"] = av.rolling(750, min_periods=250).rank(pct=True)
        frames.append(x)
    if not frames:
        return None
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="date", how="outer")
    return out.sort_values("date")


EXT = build_external()
EXT_COLS = [c for c in EXT.columns if c != "date"] if EXT is not None else []
FEATS = BASE_FEATS + EXT_COLS


# ---------------------------------------------------------------- 分段
def episodes(v, thr=THR):
    """实时 20% 反转分段，返回 [(kind, i0, i1)]。"""
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


# ---------------------------------------------------------------- 数据
def load_series(codes=None):
    """返回 {名称: (是否海外, Series)}，索引为交易日。codes 限定用哪些海外指数。"""
    out = {}
    d = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    for c in ("上证指数", "沪深300", "创业板指", "中证500", "中证1000", "中证2000", "科创50", "深证成指"):
        if c in d.columns:
            s = d[c].replace(0.0, np.nan).dropna()
            if len(s) > 500:
                out[c] = (False, s)

    names = {
        "SPX": "标普500", "DJIA": "道琼斯", "IXIC": "纳斯达克", "HSI": "恒生",
        "FTSE": "富时100", "FCHI": "法国CAC40", "TWII": "台湾加权",
        "KS11": "韩国综合", "SENSEX": "印度SENSEX", "STI": "新加坡STI",
    }
    # VIX 是波动率指数，不参与牛熊分段（可作特征，暂未用）
    for code, cn in names.items():
        if codes is not None and code not in codes:
            continue
        fp = os.path.join(OVERSEAS_DIR, "K线导出_%s_日线数据.xlsx" % code)
        if not os.path.exists(fp):
            continue
        df = pd.read_excel(fp)
        px = pd.to_numeric(df["收盘价"], errors="coerce")
        dt = pd.to_datetime(df["交易时间"], errors="coerce")
        g = pd.DataFrame({"d": dt, "p": px}).dropna().sort_values("d")
        if len(g) > 500:
            out[cn] = (True, g.set_index("d")["p"])
    return out


def load_sectors():
    """申万一级行业日线（ml_data/sw_daily，按行业×年分片）。"""
    fs = sorted(glob.glob(os.path.join(DATA_DIR, "ml_data", "sw_daily", "*.parquet")))
    if not fs:
        return {}
    frames = []
    for f in fs:
        try:
            frames.append(pd.read_parquet(f, columns=["ts_code", "trade_date", "name", "close"]))
        except Exception:
            continue
    if not frames:
        return {}
    d = pd.concat(frames, ignore_index=True)
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str))
    d = d.drop_duplicates(["ts_code", "trade_date"]).sort_values(["ts_code", "trade_date"])
    out = {}
    for code, g in d.groupby("ts_code"):
        v = pd.to_numeric(g["close"], errors="coerce")
        v.index = g["trade_date"].values
        v = v.dropna()
        if len(v) > 500:
            out[g["name"].iloc[-1]] = (code, v)
    return out


def feature_rows(name, overseas, s):
    """把一段段熊市展开成训练行 + 当前点。"""
    v = s.values
    dt = s.index
    eps = episodes(v)
    have = [e for e in eps if e[0] == "bear"]
    # 已完成的熊市段（不含最后一段，因为最后一段可能还在走）
    done = [e for e in have[:-1] if (e[2] - e[1]) >= MIN_BEAR]
    rows, cur = [], None
    # 扩张窗口的中位形态：只用「这段开始之前已经走完的」熊市
    for k, (kind, i0, i1) in enumerate(have):
        if kind != "bear" or (i1 - i0) < MIN_BEAR:
            continue
        past = [e for e in done if e[2] < i0]
        durs = np.array([e[2] - e[1] for e in past])
        deps = np.array([-(v[e[2]] / v[e[1]] - 1) for e in past])
        base_dur = float(np.median(durs)) if len(durs) >= 2 else PRIOR_DUR
        base_dep = float(np.median(deps)) if len(deps) >= 2 else PRIOR_DEP
        peak = v[i0]
        is_last = (k == len(have) - 1) and eps[-1][0] == "bear"
        for i in range(i0, i1 + 1):
            if i - i0 < 2:
                continue
            dd = v[i] / peak - 1
            p20 = v[i - 20] if i >= 20 else v[max(0, i - 5)]
            mom20 = v[i] / p20 - 1
            win = v[max(0, i - 20):i + 1]
            vol20 = float(np.std(np.diff(np.log(win)))) * np.sqrt(244) if len(win) > 5 else np.nan
            rec = dict(
                market=name, ep="%s#%d" % (name, k), is_overseas=int(overseas),
                date=dt[i],
                t_pct=(i - i0) / base_dur,
                s_pct=(-dd) / base_dep,
                dd=dd, mom20=mom20, vol20=vol20,
                log_days=np.log1p(i - i0),
            )
            for h in HORIZONS:
                rec["y%d" % h] = (v[i + h] / v[i] - 1) if i + h < len(v) else np.nan
            rows.append(rec)
        # 记录当前（最后一段）
        if is_last:
            cur = rows[-1].copy()
            cur["ep_days"] = i1 - i0
            cur["ep_chg"] = v[i1] / v[i0] - 1
    return rows, cur


def pinball(y, q, a):
    d = y - q
    return float(np.mean(np.where(d >= 0, a * d, (a - 1) * d)))


def main():
    series = load_series(OVERSEAS_CODES)
    if "上证指数" not in series:
        print("缺上证指数，退出")
        return

    rows, current = [], {}
    for name, (overseas, s) in series.items():
        rs, cur = feature_rows(name, overseas, s)
        rows.extend(rs)
        if cur:
            current[name] = cur

    df = pd.DataFrame(rows)
    if EXT is not None:
        df = pd.merge_asof(df.sort_values("date"), EXT, on="date",
                           direction="backward", allow_exact_matches=False)
    ykey = "y%d" % max(HORIZONS)
    df = df[df[ykey].notna()].copy()      # 只用有完整最长前瞻的行
    if len(df) < MIN_TRAIN:
        print("样本不足：%d 行，退出" % len(df))
        return

    eps_all = df["ep"].unique()
    n_overseas_ep = df[df["is_overseas"] == 1]["ep"].nunique()
    n_a_master = int(df[df["market"] == "上证指数"]["ep"].nunique())
    n_a_ep = df[df["is_overseas"] == 0]["ep"].nunique()

    # ---------------- 样本外预测（按整段熊市分组）
    from sklearn.model_selection import GroupKFold
    gkf = GroupKFold(n_splits=min(5, len(eps_all)))
    oof = {h: {a: np.full(len(df), np.nan) for a in QS} for h in HORIZONS}

    X = df[FEATS]
    groups = df["ep"].values
    for tr, te in gkf.split(X, groups=groups):
        for h in HORIZONS:
            y = df["y%d" % h].values
            m_tr = tr[~np.isnan(y[tr])]
            if len(m_tr) < 200:
                continue
            for a in QS:
                m = lgb.LGBMRegressor(
                    objective="quantile", alpha=a, n_estimators=300,
                    learning_rate=0.05, num_leaves=4, max_depth=2,
                    min_child_samples=300, subsample=0.8, subsample_freq=1,
                    colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=4)
                m.fit(X.iloc[m_tr], y[m_tr])
                oof[h][a][te] = m.predict(X.iloc[te])

    # ---------------- 样本外评分
    skill, cover, detail = {}, {}, {}
    for h in HORIZONS:
        y = df["y%d" % h].values
        ok = ~np.isnan(y)
        for a in QS:
            ok &= ~np.isnan(oof[h][a])
        if ok.sum() < 500:
            continue
        yy = y[ok]
        model_loss = np.mean([pinball(yy, oof[h][a][ok], a) for a in QS])
        # 基线：训练折的无条件分位数（用全体分位数近似，乐观地偏向基线）
        base_loss = np.mean([pinball(yy, np.full(len(yy), np.quantile(yy, a)), a) for a in QS])
        skill[h] = round((1 - model_loss / base_loss) * 100, 1)
        cover[h] = round(float(((yy >= oof[h][0.10][ok]) & (yy <= oof[h][0.90][ok])).mean()) * 100, 1)
        # 分市场
        ov = ok & (df["is_overseas"].values == 1)
        an = ok & (df["is_overseas"].values == 0)
        if ov.sum() > 300:
            m_loss = np.mean([pinball(y[ov], oof[h][a][ov], a) for a in QS])
            b_loss = np.mean([pinball(y[ov], np.full(ov.sum(), np.quantile(y[ov], a)), a) for a in QS])
            detail.setdefault("overseas", {})[h] = round(float(1 - m_loss / b_loss) * 100, 1)
        if an.sum() > 300:
            m_loss = np.mean([pinball(y[an], oof[h][a][an], a) for a in QS])
            b_loss = np.mean([pinball(y[an], np.full(an.sum(), np.quantile(y[an], a)), a) for a in QS])
            detail.setdefault("a_share", {})[h] = round(float(1 - m_loss / b_loss) * 100, 1)

    # ---------------- CQR：给 10–90% 区间加覆盖保证
    # 用折外的 conformity score 定一个统一扩张量，再折外验证覆盖率。
    calib = {}
    for h in HORIZONS:
        y = df["y%d" % h].values
        lo, hi = oof[h][0.10], oof[h][0.90]
        ok = ~np.isnan(y) & ~np.isnan(lo) & ~np.isnan(hi)
        if ok.sum() < 500:
            continue
        delta_oof = np.full(len(y), np.nan)
        for tr, te in gkf.split(X, groups=groups):
            mtr = tr[ok[tr]]
            if len(mtr) < 200:
                continue
            e = np.maximum(lo[mtr] - y[mtr], y[mtr] - hi[mtr])
            delta_oof[te] = float(np.quantile(e, 0.8))
        cov_before = float(((y >= lo) & (y <= hi))[ok].mean() * 100)
        m = ok & ~np.isnan(delta_oof)
        cov_after = float(((y >= lo - delta_oof) & (y <= hi + delta_oof))[m].mean() * 100)
        delta_full = float(np.quantile(np.maximum(lo[ok] - y[ok], y[ok] - hi[ok]), 0.8))
        calib[h] = dict(delta=round(delta_full * 100, 2),
                        cov_before=round(cov_before, 1),
                        cov_after=round(cov_after, 1),
                        n=int(ok.sum()))

    # ---------------- 全样本重训，用于对当前点做预测
    models = {}
    for h in HORIZONS:
        y = df["y%d" % h].values
        ok = ~np.isnan(y)
        models[h] = {}
        for a in QS:
            m = lgb.LGBMRegressor(
                objective="quantile", alpha=a, n_estimators=300,
                learning_rate=0.05, num_leaves=4, max_depth=2,
                min_child_samples=300, subsample=0.8, subsample_freq=1,
                colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=4)
            m.fit(X[ok], y[ok])
            models[h][a] = m

    # 特征重要性（中位数模型）
    main_h = max(HORIZONS)
    imp = dict(zip(FEATS, [round(float(x), 1) for x in models[main_h][0.5].feature_importances_]))
    imp = dict(sorted(imp.items(), key=lambda kv: -kv[1]))

    if EXT is not None and current:
        cdf = pd.DataFrame(list(current.values()))
        cdf = pd.merge_asof(cdf.sort_values("date"), EXT, on="date",
                            direction="backward", allow_exact_matches=False)
        current = {r["market"]: r for _, r in cdf.iterrows()}

    def predict(row):
        x = pd.DataFrame([[row[f] for f in FEATS]], columns=FEATS)
        out = {}
        for h in HORIZONS:
            q = np.array([float(models[h][a].predict(x)[0]) for a in QS])
            q = np.sort(q)                       # 分位数回归可能交叉，强制单调
            # 由分位曲线反推 P(未来 h 日收益 > 0)
            p_up = 1.0 - float(np.interp(0.0, q, QS))
            d = (calib.get(h) or {}).get("delta", 0) / 100.0
            out[str(h)] = dict(
                p10=round((q[0] - d) * 100, 2), p25=round(q[1] * 100, 2),
                p50=round(q[2] * 100, 2), p75=round(q[3] * 100, 2),
                p90=round((q[4] + d) * 100, 2), pup=round(p_up * 100, 1))
        return out

    preds = {name: predict(r) for name, r in current.items() if name in series}

    # 推荐的指数（与结论卡一致：创业板指优先，否则取 60 日预测中位最高）
    focus = "创业板指" if "创业板指" in preds else None
    if focus is None and preds:
        focus = max(preds, key=lambda k: preds[k]["60"]["p50"])

    # 扇形图数据：0 天固定 0%，之后取各 horizon 的分位
    fan = [dict(d=0, p10=0, p25=0, p50=0, p75=0, p90=0)]
    if focus:
        for h in HORIZONS:
            q = preds[focus][str(h)]
            fan.append(dict(d=h, p10=q["p10"], p25=q["p25"], p50=q["p50"],
                            p75=q["p75"], p90=q["p90"]))

    # ---------------- 板块（申万一级）：迁移应用 + 样本外检验
    # 模型训练时完全没见过板块数据，这里是真正的样本外迁移。
    sec_h = 60 if 60 in HORIZONS else max(HORIZONS)
    sectors, sec_eval, sector_rho = [], None, None
    try:
        secs = load_sectors()
    except Exception as e:
        print("板块加载失败：%s" % e)
        secs = {}
    if secs:
        sec_rows, cur_secs = [], {}
        for nm, (code, sv) in secs.items():
            rs, cur = feature_rows(nm, False, sv)
            for r in rs:
                if not np.isnan(r.get("y60", np.nan)):
                    sec_rows.append(r)
            if cur:
                cur_secs[nm] = (code, cur)
        if sec_rows:
            ds = pd.DataFrame(sec_rows)
            ds = ds[ds["y60"].notna()]
            if EXT is not None and len(ds):
                ds = pd.merge_asof(ds.sort_values("date"), EXT, on="date",
                                   direction="backward", allow_exact_matches=False)
            if len(ds) > 500:
                q60 = {a: models[sec_h][a].predict(ds[FEATS]) for a in QS}
                yy = ds["y60"].values
                mloss = np.mean([pinball(yy, q60[a], a) for a in QS])
                bloss = np.mean([pinball(yy, np.full(len(yy), np.quantile(yy, a)), a) for a in QS])
                cov = float(((yy >= q60[0.10]) & (yy <= q60[0.90])).mean()) * 100
                sec_eval = dict(n_rows=int(len(ds)), n_ep=int(ds["ep"].nunique()),
                                skill=round(float(1 - mloss / bloss) * 100, 1),
                                coverage=round(cov, 1))
        if cur_secs:
            cdf = pd.DataFrame([dict(r, _name=nm) for nm, (_, r) in cur_secs.items()])
            if EXT is not None:
                cdf = pd.merge_asof(cdf.sort_values("date"), EXT, on="date",
                                    direction="backward", allow_exact_matches=False)
            for _, row in cdf.iterrows():
                nm = row["_name"]
                q = predict(row)[str(sec_h)]
                sectors.append(dict(
                    name=nm, code=cur_secs[nm][0],
                    days=int(row["ep_days"]), chg=round(float(row["ep_chg"]) * 100, 1),
                    dd=round(float(row["dd"]) * 100, 1),
                    t_pct=round(float(row["t_pct"]) * 100),
                    s_pct=round(float(row["s_pct"]) * 100), **q))
        sectors.sort(key=lambda x: -x["pup"])
        # 板块内部关系：回撤 vs 上行概率、时间/空间进度 vs 上行概率
        if len(sectors) >= 8:
            sdf = pd.DataFrame(sectors)

            def _rho(col):
                return round(float(sdf[col].rank().corr(sdf["pup"].rank())), 2)

            sector_rho = dict(n=len(sdf), dd=_rho("dd"), t=_rho("t_pct"), space=_rho("s_pct"))

    # 与规则同档分布对比：60 日
    payload = dict(
        asof=max(s.index[-1] for _, s in series.values()).strftime("%Y-%m-%d"),
        focus=focus,
        fan=fan,
        pred=preds.get(focus) if focus else None,
        all_preds=preds,
        sectors=sectors,
        sector_eval=sec_eval,
        sector_rho=sector_rho,
        n_rows=int(len(df)),
        n_ep=int(len(eps_all)),
        n_overseas_ep=int(n_overseas_ep),
        n_a_ep=int(n_a_ep),
        n_a_master=int(n_a_master),
        horizons=HORIZONS,
        quantiles=QS,
        skill=skill,
        coverage=cover,
        calib=calib,
        skill_by_market=detail,
        importances=imp,
        meta=dict(thr=THR, min_bear=MIN_BEAR, prior_dur=PRIOR_DUR,
                  prior_dep=PRIOR_DEP, n_splits=int(gkf.n_splits)),
    )

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("/* generated by src/build_ml_model.py — do not edit */\n")
        f.write("window.WAW=window.WAW||{};window.WAW.ml_model=")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")

    print("样本 %d 行 / %d 段熊市（海外 %d 段，A股 %d 段）→ %s" %
          (len(df), len(eps_all), n_overseas_ep, n_a_ep, OUT))
    print("焦点指数：%s" % focus)
    for h in HORIZONS:
        if h in skill:
            print("  %2d 日：分位损失改善 %+5.1f%%  80%%区间覆盖率 %.1f%%" % (h, skill[h], cover[h]))
    if detail:
        for k, v in detail.items():
            print("  %-8s %s" % (k, v))
    print("特征重要性：%s" % imp)
    if focus:
        q = preds[focus]["60"]
        print("60 日预测：p10 %+.1f%% / 中位 %+.1f%% / p90 %+.1f%%  上行概率 %.0f%%" %
              (q["p10"], q["p50"], q["p90"], q["pup"]))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="10,20,30,40,50,60")
    ap.add_argument("--out", default=None)
    ap.add_argument("--overseas", default="")
    a = ap.parse_args()
    HORIZONS = [int(x) for x in a.horizons.split(",")]
    if a.overseas == "all":
        OVERSEAS_CODES = None
    elif a.overseas:
        OVERSEAS_CODES = [x.strip() for x in a.overseas.split(",") if x.strip()]
    if a.out:
        OUT = a.out
    main()
