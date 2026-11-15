# -*- coding: utf-8 -*-
"""资金面/情绪面：融资余额、融资买入占比、热度榜。输出情绪温度（分位）。"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MARGIN_CSV, DC_HOT_CSV, THS_HOT_CSV, CACHE_DIR


def load_margin():
    m = pd.read_csv(MARGIN_CSV, usecols=["trade_date", "exchange_id", "rzye", "rzmre"])
    m["trade_date"] = pd.to_datetime(m["trade_date"].astype(str), format="%Y%m%d")
    d = m.groupby("trade_date").agg(rzye=("rzye", "sum"), rzmre=("rzmre", "sum")).reset_index()
    return d.sort_values("trade_date")


def margin_snapshot():
    """融资余额 + 融资买入占比(需全A成交额)。"""
    m = load_margin()
    mkt = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    mkt["date"] = pd.to_datetime(mkt["date"])
    df = m.merge(mkt[["date", "amount"]], left_on="trade_date", right_on="date", how="inner")
    df["margin_buy_ratio"] = df["rzmre"] / df["amount"]  # 融资买入/全A成交额
    df["margin_balance"] = df["rzye"] / 1e8  # 亿元
    return df


def hot_snapshot():
    """热度榜：每日上榜股票数 + ETF/行业板块热度。"""
    dh = pd.read_csv(DC_HOT_CSV, usecols=["trade_date", "ts_code"])
    dh["trade_date"] = pd.to_datetime(dh["trade_date"].astype(str), format="%Y%m%d")
    dh_n = dh.groupby("trade_date").size().reset_index(name="dc_hot_n")

    th = pd.read_csv(THS_HOT_CSV, usecols=["trade_date", "ts_code", "data_type"])
    th["trade_date"] = pd.to_datetime(th["trade_date"].astype(str), format="%Y%m%d")
    th_etf = th[th["data_type"] == "ETF"].groupby("trade_date").size().reset_index(name="ths_etf_hot_n")
    th_ind = th[th["data_type"] == "行业板块"].groupby("trade_date").size().reset_index(name="ths_ind_hot_n")

    df = dh_n.merge(th_etf, on="trade_date", how="outer").merge(th_ind, on="trade_date", how="outer")
    return df.sort_values("trade_date")


def pct_rank(series, value):
    s = series.dropna()
    if len(s) == 0 or value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float((s <= value).mean())


def snapshot():
    m = margin_snapshot()
    h = hot_snapshot()
    # 近10年分位（融资有2016+，热度仅2023+）
    mcut = m["trade_date"].max() - pd.DateOffset(years=10)
    m10 = m[m["trade_date"] >= mcut]
    out = {}
    last = m.iloc[-1]
    out["margin_balance_yi"] = round(float(last["margin_balance"]), 0)
    out["margin_buy_ratio_pct"] = round(float(last["margin_buy_ratio"]) * 100, 2)
    out["margin_balance_pctile"] = round(pct_rank(m10["margin_balance"], last["margin_balance"]), 3)
    out["margin_buy_ratio_pctile"] = round(pct_rank(m10["margin_buy_ratio"], last["margin_buy_ratio"]), 3)
    if len(h):
        hl = h.iloc[-1]
        for k in ["dc_hot_n", "ths_etf_hot_n", "ths_ind_hot_n"]:
            v = hl.get(k)
            out[k] = None if pd.isna(v) else int(v)
            out[k + "_pctile"] = round(pct_rank(h[k], v), 3) if not pd.isna(v) else None
        out["hot_asof"] = hl["trade_date"].strftime("%Y-%m-%d")
    out["margin_asof"] = m["trade_date"].iloc[-1].strftime("%Y-%m-%d")
    return out


if __name__ == "__main__":
    print(snapshot())
