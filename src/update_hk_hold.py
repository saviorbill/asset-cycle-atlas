# -*- coding: utf-8 -*-
"""把 alt_hk_hold_tushare.csv 的港股通（HK）日数据补到最新交易日。

只追加 exchange=HK。SH/SZ（陆股通/北向）2025 年后仅有季度披露，
且与港股持股量纲不同，不应混进同一条日序列。
"""
import os
import sys
import time

import pandas as pd
import requests

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from config import HK_HOLD_CSV, CACHE_DIR  # noqa: E402
from fetch_api_data import BASE, HEAD  # noqa: E402

COLS = ["code", "trade_date", "ts_code", "name", "vol", "ratio", "exchange"]


def fetch_range(a, b):
    rows, fields, offset = [], None, 0
    while True:
        d = None
        for attempt in range(6):
            try:
                r = requests.get(BASE + "hk-hold", headers=HEAD,
                                 params={"start_date": a, "end_date": b,
                                         "exchange": "HK", "limit": 5000,
                                         "offset": offset}, timeout=60)
                if r.status_code == 429:
                    wait = 15 + attempt * 10
                    print("  429，等待 %ds" % wait, flush=True)
                    time.sleep(wait)
                    continue
                d = r.json()
                break
            except Exception:
                time.sleep(3 * (attempt + 1))
        if d is None:
            raise RuntimeError("hk-hold 重试失败")
        if d.get("code") != 0:
            raise RuntimeError("hk-hold code=%s msg=%s" % (d.get("code"), d.get("msg")))
        data = d.get("data") or {}
        fields = data.get("fields") or fields
        items = data.get("items") or []
        rows.extend(items)
        print("  已拉取 %d 条" % len(rows), flush=True)
        if not data.get("has_more") or not items:
            break
        offset += 5000
        time.sleep(1)
    if not rows:
        return None
    return pd.DataFrame(rows, columns=fields)


def main():
    # 只读最后一行日期，避免把 313MB 文件整体读入内存
    last = 0
    with open(HK_HOLD_CSV, "r", encoding="utf-8") as f:
        for line in f:
            p = line.split(",", 2)
            if len(p) >= 2:
                try:
                    last = max(last, int(float(p[1])))
                except ValueError:
                    pass
    print("现有最后日期:", last)

    md = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"),
                         columns=["date"])
    dates = pd.to_datetime(md["date"]).dt.strftime("%Y%m%d").astype(int)
    end = int(max(dates))
    start = int((pd.Timestamp(str(last)) + pd.Timedelta(days=1)).strftime("%Y%m%d"))
    if start > end:
        print("已经是最新")
        return
    print("拉取区间:", start, "~", end)

    df = fetch_range(str(start), str(end))
    if df is None or not len(df):
        print("无新增数据")
        return
    # 防止区间接口把 SH/SZ 也带进来：优先按 exchange 过滤，其次按 .HK 代码
    if "exchange" in df.columns:
        df = df[df["exchange"].astype(str).str.upper() == "HK"]
    elif "ts_code" in df.columns:
        df = df[df["ts_code"].astype(str).str.upper().str.endswith(".HK")]
    df = df.reindex(columns=COLS)
    df["trade_date"] = df["trade_date"].astype(str)
    df["exchange"] = "HK"
    df = df[pd.to_numeric(df["trade_date"], errors="coerce") > last]
    df = df.drop_duplicates(["trade_date", "ts_code"])
    df.to_csv(HK_HOLD_CSV, mode="a", header=False, index=False)
    print("完成：追加", len(df), "条 | 日期", df["trade_date"].min(), "~",
          df["trade_date"].max())


if __name__ == "__main__":
    main()
