# -*- coding: utf-8 -*-
"""重建“真实涨停/跌停家数”日序列。

历史段：用面板未复权收盘价 + 前收盘价 + 板块涨跌幅规则推算涨跌停价。
  - 主板 10%，创业板/科创板 20%，北交所 30%，主板 ST 5%
  - 上市首日/前 5 日无涨跌幅限制的，用“涨幅超过限制+0.5%”排除
近期段：datahubco limit-list-d（按 limit=U/D 统计）覆盖同日推算值。

输出 cache/limit_daily.csv:
  trade_date, limit_up_n, limit_down_n
"""
import os
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from config import PANEL_PARQUET, STOCK_BASIC_CSV, CACHE_DIR  # noqa: E402
from fetch_api_data import BASE, HEAD  # noqa: E402
import requests  # noqa: E402

OUT = os.path.join(CACHE_DIR, "limit_daily.csv")
API_START = "20260806"          # stk_limit 本地文件止于 20260805，之后用全市场接口
API_END = "20261113"


def history_counts():
    df = pq.read_table(PANEL_PARQUET,
                       columns=["date", "ticker", "close", "close_raw", "volume"]).to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["close_raw"] = pd.to_numeric(df["close_raw"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.sort_values(["ticker", "date"])
    g = df.groupby("ticker", sort=False)["close"]
    df["pct"] = g.pct_change(fill_method=None)
    # 停牌日没有有效涨跌幅，不能算平盘
    df.loc[df["volume"].fillna(0) <= 0, "pct"] = np.nan
    df["pct"] = df["pct"].where(df["pct"].abs() < 1.0)

    sb = pd.read_csv(STOCK_BASIC_CSV, dtype={"ts_code": str})[["ts_code", "name"]]
    df = df.merge(sb.rename(columns={"ts_code": "ticker"}), on="ticker", how="left")
    name = df["name"].astype(str)
    tick = df["ticker"].astype(str)
    base = np.where(tick.str.startswith(("300", "301", "302", "688", "689")), 0.20,
                    np.where(tick.str.startswith(("920", "8", "4")), 0.30,
                             np.where(name.str.contains("ST"), 0.05, 0.10)))
    df["base"] = base

    pre = df["close_raw"] / (1.0 + df["pct"])
    up = np.floor(pre * (1.0 + df["base"]) * 100.0 + 0.5) / 100.0
    dn = np.floor(pre * (1.0 - df["base"]) * 100.0 + 0.5) / 100.0
    # 无涨跌幅限制的新股首日涨幅会明显超过板块限制，排除
    within = df["pct"].abs() <= df["base"] + 0.005
    df["limit_up_n"] = (within & (df["close_raw"] >= up - 0.005)).astype(int)
    df["limit_down_n"] = (within & (df["close_raw"] <= dn + 0.005)).astype(int)
    out = df.groupby("date")[["limit_up_n", "limit_down_n"]].sum().reset_index()
    return out


def fetch_limit_list(a, b):
    rows, fields, offset = [], None, 0
    while True:
        params = {"start_date": a, "end_date": b, "limit": 5000, "offset": offset}
        d = None
        for attempt in range(6):
            try:
                r = requests.get(BASE + "limit-list-d", headers=HEAD, params=params, timeout=60)
                if r.status_code == 429:
                    wait = 15 + attempt * 10
                    print("  429 limit-list-d %s~%s，等待 %ds" % (a, b, wait), flush=True)
                    time.sleep(wait)
                    continue
                d = r.json()
                break
            except Exception:
                time.sleep(3 * (attempt + 1))
        if d is None:
            raise RuntimeError("limit-list-d %s~%s 重试失败" % (a, b))
        if d.get("code") != 0:
            raise RuntimeError("limit-list-d %s~%s code=%s msg=%s"
                               % (a, b, d.get("code"), d.get("msg")))
        data = d.get("data") or {}
        fields = data.get("fields") or fields
        items = data.get("items") or []
        rows.extend(items)
        if not data.get("has_more") or not items:
            break
        offset += 5000
        time.sleep(1)
    if not rows:
        return pd.DataFrame(columns=["date", "limit_up_n", "limit_down_n"])
    df = pd.DataFrame(rows, columns=fields)
    df["date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df["limit_up_n"] = (df["limit"].astype(str).str.upper() == "U").astype(int)
    df["limit_down_n"] = (df["limit"].astype(str).str.upper() == "D").astype(int)
    g = df.groupby("date")[["limit_up_n", "limit_down_n"]].sum().reset_index()
    return g


def api_counts():
    ranges = [("20260806", "20260831"), ("20260901", "20260930"),
              ("20261001", "20261031"), ("20261101", API_END)]
    out = []
    for a, b in ranges:
        try:
            g = fetch_limit_list(a, b)
        except Exception as e:
            # 接口限流时保留已拿到的区间，缺失日期继续用推算值兜底
            print("  %s~%s 接口失败: %s" % (a, b, str(e)[:80]), flush=True)
            continue
        print("  %s~%s: %d 天" % (a, b, len(g)), flush=True)
        out.append(g)
        time.sleep(3)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main():
    print("全历史涨跌停家数（面板 + 板块规则）...")
    h = history_counts()
    print("  历史:", h["date"].min().date(), "~", h["date"].max().date(), len(h), "天")
    print("近期涨跌停家数（limit-list-d）...")
    a = api_counts()
    if len(a):
        print("  近期:", a["date"].min().date(), "~", a["date"].max().date(), len(a), "天")
    # 近期用全市场接口覆盖同日推算值；接口缺失的日期保留推算值。
    # 若接口整体失败，保留上一次已写入的近期精确值，避免尾部回滚。
    parts = [h]
    if os.path.exists(OUT):
        old = pd.read_csv(OUT, parse_dates=["trade_date"]).rename(columns={"trade_date": "date"})
        parts.append(old[old["date"] > h["date"].max()])
    parts.append(a)
    allx = pd.concat(parts, ignore_index=True)
    allx = allx.drop_duplicates("date", keep="last").sort_values("date")
    allx = allx.rename(columns={"date": "trade_date"})
    allx.to_csv(OUT, index=False)
    print("已保存:", OUT, "|", len(allx), "天 |",
          allx["trade_date"].min().date(), "~", allx["trade_date"].max().date())
    print(allx.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
