# -*- coding: utf-8 -*-
"""把 alt_limit_cpt.csv（涨停概念上榜数据）补到最新交易日。

注意：这是“概念板块上榜数”，同一只股票会出现在多个概念里，
只适合做概念热度，不能当涨停家数使用。真实涨停家数见 build_limit_daily.py。
"""
import os
import sys
import time

import pandas as pd
import requests

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from config import LIMIT_CPT_CSV, CACHE_DIR  # noqa: E402
from fetch_api_data import BASE, HEAD  # noqa: E402


def fetch_day(dt):
    d = None
    for attempt in range(6):
        try:
            r = requests.get(BASE + "limit-cpt-list", headers=HEAD,
                             params={"trade_date": dt, "limit": 50}, timeout=40)
            if r.status_code == 429:
                wait = 10 + attempt * 10
                print("  429 %s，等待 %ds" % (dt, wait), flush=True)
                time.sleep(wait)
                continue
            d = r.json()
            break
        except Exception:
            time.sleep(3 * (attempt + 1))
    if d is None or d.get("code") != 0:
        print("  跳过 %s: %s" % (dt, (d or {}).get("msg")), flush=True)
        return None
    data = d.get("data") or {}
    items = data.get("items") or []
    if not items:
        return None
    return pd.DataFrame(items, columns=data["fields"])


def main():
    old = pd.read_csv(LIMIT_CPT_CSV, dtype={"trade_date": str})
    last = int(old["trade_date"].max())
    print("现有范围:", old["trade_date"].min(), "~", last)

    md = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"),
                         columns=["date"])
    dates = pd.to_datetime(md["date"]).dt.strftime("%Y%m%d").astype(int)
    todo = sorted(d for d in set(dates) if d > last)
    print("待补交易日:", len(todo), todo[:2], "...", todo[-2:])

    frames = []
    for i, dt in enumerate(todo, 1):
        df = fetch_day(str(dt))
        if df is not None and len(df):
            frames.append(df)
            print("[%d/%d] %s: %d 条" % (i, len(todo), dt, len(df)), flush=True)
        else:
            print("[%d/%d] %s: 无数据" % (i, len(todo), dt), flush=True)
        time.sleep(1.2)

    if not frames:
        print("没有新增数据")
        return
    new = pd.concat(frames, ignore_index=True)
    new["trade_date"] = new["trade_date"].astype(str)
    out = pd.concat([old, new], ignore_index=True).drop_duplicates(
        ["trade_date", "ts_code"], keep="last")
    out = out.sort_values(["trade_date", "rank", "ts_code"])
    out.to_csv(LIMIT_CPT_CSV, index=False)
    print("已写入:", LIMIT_CPT_CSV, "|", len(out), "行 | 最新:",
          out["trade_date"].max())


if __name__ == "__main__":
    main()
