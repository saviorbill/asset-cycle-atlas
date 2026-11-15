# -*- coding: utf-8 -*-
"""把 stock_basic_all.csv 增量更新到 API 最新股票列表。

保留本地已退市/已合并的旧股票（API 只返回当前上市股票），
避免历史面板的行业映射出现空洞。
"""
import os
import sys
import time

import pandas as pd
import requests

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from config import STOCK_BASIC_CSV  # noqa: E402
from fetch_api_data import BASE, HEAD  # noqa: E402


def fetch_all():
    rows, fields, offset = [], None, 0
    while True:
        d = None
        for attempt in range(6):
            try:
                r = requests.get(BASE + "stock-basic", headers=HEAD,
                                 params={"limit": 5000, "offset": offset}, timeout=60)
                if r.status_code == 429:
                    wait = 10 + attempt * 10
                    print("  429，等待 %ds" % wait, flush=True)
                    time.sleep(wait)
                    continue
                d = r.json()
                break
            except Exception:
                time.sleep(3 * (attempt + 1))
        if d is None:
            raise RuntimeError("stock-basic 重试失败")
        if d.get("code") != 0:
            raise RuntimeError("stock-basic code=%s msg=%s" % (d.get("code"), d.get("msg")))
        data = d.get("data") or {}
        fields = data.get("fields") or fields
        items = data.get("items") or []
        rows.extend(items)
        if not data.get("has_more") or not items:
            break
        offset += 5000
        time.sleep(1)
    return pd.DataFrame(rows, columns=fields)


def main():
    api = fetch_all()
    print("API 股票数:", len(api), "| 最新上市:", api["list_date"].max())
    local = pd.read_csv(STOCK_BASIC_CSV, dtype={"ts_code": str, "list_date": str})
    old_only = local[~local["ts_code"].isin(set(api["ts_code"]))].copy()
    print("本地保留（API 已不再返回，通常为退市/合并）:", len(old_only))

    cols = ["ts_code", "name", "industry", "list_date", "market"]
    out = pd.concat([api[cols], old_only[cols]], ignore_index=True)
    out = out.drop_duplicates("ts_code", keep="first")
    out["list_date"] = pd.to_numeric(out["list_date"], errors="coerce").astype("Int64")
    out = out.sort_values(["list_date", "ts_code"], ascending=[False, True])
    out.to_csv(STOCK_BASIC_CSV, index=False)
    print("已写入:", STOCK_BASIC_CSV, "|", len(out), "只")
    print(out.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
