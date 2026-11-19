# -*- coding: utf-8 -*-
"""把个股财务聚合成「指数 / 申万一级行业」的季度基本面序列。

输出：应用数据/cache/fund_panel.parquet
    asset_type  ('index' / 'sector')
    code        指数代码或申万一级代码
    name
    end_date    报告期
    roe         加权/等权平均 ROE
    or_yoy      营收同比
    op_yoy      营业利润同比
    n           参与的个股数

口径与已知偏差：
  - 个股财务取「同一报告期最新公告」的那一条，避免旧报表。
  - 行业用 index_member 的现行成分等权平均；指数用 index_weight 最新一期的权重重加权。
  - 用现行成分回溯历史会有幸存者偏差，对「当前值处在自身历史什么位置」影响有限，
    但不能拿这条序列去做严格回测。
"""
import os
import sys
import glob

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import DATA_DIR, CACHE_DIR  # noqa: E402

OUT = os.path.join(CACHE_DIR, "fund_panel.parquet")
FIN = os.path.join(DATA_DIR, "fundamental_factors_monthly.csv")
PANEL = os.path.join(DATA_DIR, "panel_csi_all_full.parquet")
MEMBER = os.path.join(DATA_DIR, "ml_data", "index_member", "index_member_all.parquet")
WEIGHT_DIR = os.path.join(DATA_DIR, "ml_data", "index_weight")

COLS = ["roe", "or_yoy", "op_yoy", "grossprofit_margin", "debt_to_assets", "ocfps"]

IDX_CODE = {
    "上证指数": "000001.SH", "沪深300": "000300.SH", "中证500": "000905.SH",
    "中证1000": "000852.SH", "中证2000": "932000.CSI",
    "创业板指": "399006.SZ", "科创50": "000688.SH",
}


def load_fin():
    """月频基本面（2018-10 起，3,800 只）。比季报口径更密，滞后也更小。"""
    d = pd.read_csv(FIN, usecols=["month", "ts_code", "roe", "or_yoy", "op_yoy",
                                  "grossprofit_margin", "debt_to_assets", "ocfps"])
    d["end_date"] = pd.to_datetime(d["month"].astype(str), errors="coerce")
    d = d.dropna(subset=["end_date"])
    d = d.drop(columns=["month"]).drop_duplicates(["ts_code", "end_date"], keep="last")
    return d


def sector_members():
    m = pd.read_parquet(MEMBER)
    m = m[m["l1_code"].notna()]
    out = {}
    for code, g in m.groupby("l1_code"):
        out[code] = set(g["ts_code"])
    names = m.groupby("l1_code")["l1_name"].last().to_dict()
    return out, names


def index_weights():
    fs = sorted(glob.glob(os.path.join(WEIGHT_DIR, "*.parquet")))
    if not fs:
        return {}
    d = pd.concat([pd.read_parquet(f, columns=["index_code", "con_code", "trade_date", "weight"])
                   for f in fs], ignore_index=True)
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str), errors="coerce")
    out = {}
    for code, g in d.groupby("index_code"):
        last = g["trade_date"].max()
        w = g[g["trade_date"] == last].dropna(subset=["weight"])
        out[code] = dict(zip(w["con_code"], w["weight"]))
    return out


def agg(fin_by_date, members, weights=None):
    """按报告期聚合：members 是 ts_code 集合（等权），或 weights 是 {code: 权重}。"""
    rows = []
    for end_date, g in fin_by_date:
        if weights:
            sub = g[g["ts_code"].isin(weights)]
            if len(sub) < 3:
                continue
            w = sub["ts_code"].map(weights).astype(float)
            rec = {"end_date": end_date, "n": int(len(sub))}
            for col in COLS:
                v = sub[col].astype(float)
                m = v.notna()
                if not m.any():
                    rec[col] = np.nan
                    continue
                vv = v[m].clip(*np.percentile(v[m], [1, 99]))   # 去极值
                rec[col] = float(np.average(vv, weights=w[m]))
        else:
            sub = g[g["ts_code"].isin(members)]
            if len(sub) < 5:
                continue
            rec = {"end_date": end_date, "n": int(len(sub))}
            for col in COLS:
                v = sub[col].astype(float).dropna()
                rec[col] = float(v.clip(*np.percentile(v, [1, 99])).mean()) if len(v) else np.nan
        rows.append(rec)
    return rows


def build_dv(secs, wts):
    """股息率：面板 dv_ttm 的月末快照，按成分权重/行业成员聚合。"""
    if not os.path.exists(PANEL):
        return None
    d = pd.read_parquet(PANEL, columns=["date", "ticker", "dv_ttm"])
    d["date"] = pd.to_datetime(d["date"])
    d["m"] = d["date"].dt.to_period("M")
    last = d.groupby("m")["date"].transform("max")
    d = d[d["date"] == last]
    rows = []
    for m, g in d.groupby("m"):
        v = pd.to_numeric(g["dv_ttm"], errors="coerce")
        g = g.assign(dv=v).dropna(subset=["dv"])
        if not len(g):
            continue
        idx_map = dict(zip(g["ticker"], g["dv"]))
        for code, mem in secs.items():
            vals = [idx_map[t] for t in mem if t in idx_map]
            if len(vals) >= 5:
                rows.append(dict(asset_type="sector", code=code,
                                 end_date=m.to_timestamp(), dv=float(np.median(vals))))
        for name, code in IDX_CODE.items():
            if code not in wts:
                continue
            ws = [wts[code][t] for t in idx_map if t in wts[code]]
            if len(ws) >= 20:
                vs = [idx_map[t] for t in idx_map if t in wts[code]]
                rows.append(dict(asset_type="index", code=code,
                                 end_date=m.to_timestamp(), dv=float(np.average(vs, weights=ws))))
    return pd.DataFrame(rows)


def main():
    fin = load_fin()
    by_date = list(fin.groupby("end_date"))
    print("财务 %d 行，%d 个报告期" % (len(fin), len(by_date)))

    rows = []
    secs, sec_names = sector_members()
    for code, mem in secs.items():
        for r in agg(by_date, mem):
            r.update(asset_type="sector", code=code, name=sec_names.get(code, code))
            rows.append(r)

    wts = index_weights()
    for name, code in IDX_CODE.items():
        if code not in wts:
            continue
        for r in agg(by_date, None, weights=wts[code]):
            r.update(asset_type="index", code=code, name=name)
            rows.append(r)

    out = pd.DataFrame(rows)
    wts2 = index_weights()
    dv = build_dv(secs, wts2)
    if dv is not None and len(dv):
        out = out.merge(dv, on=["asset_type", "code", "end_date"], how="outer")
        # 补齐 name
        nm = out.dropna(subset=["name"]).groupby("code")["name"].last().to_dict()
        out["name"] = out["name"].fillna(out["code"].map(nm))
        print("股息率 %d 行" % len(dv))
    out = out[out["end_date"] >= "2010-01-01"].sort_values(["asset_type", "code", "end_date"])
    os.makedirs(CACHE_DIR, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print("落盘 %d 行 → %s" % (len(out), OUT))
    last = out[out["end_date"] == out["end_date"].max()]
    print(last[["asset_type", "name", "roe", "or_yoy", "op_yoy", "n"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
