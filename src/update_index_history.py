# -*- coding: utf-8 -*-
"""抓取主要指数估值与换手（index-dailybasic），补足各指数上市以来的长周期参照。

全A中位数、广度、集中度、融资等指标依赖 2016 年起的全A面板；
指数估值/换手是唯一能低成本回溯的长周期连续口径，因此单独缓存，
在网页中明确标注为“指数口径”，不与全A中位数混用。
"""
import os, sys, time
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR
from update_indicators import BASE, HEAD

OUT = os.path.join(CACHE_DIR, "index_dailybasic.csv")
CODES = {
    "000001.SH": "上证指数",
    "000300.SH": "沪深300",
    "399006.SZ": "创业板指",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.CSI": "中证2000",
    "000688.SH": "科创50",
}


def fetch(code):
    for attempt in range(3):
        rows, offset = [], 0
        fields = None
        for _ in range(10):
            try:
                r = requests.get(BASE + "index-dailybasic", headers=HEAD,
                                 params={"ts_code": code, "start_date": "20000101",
                                         "end_date": "20991231", "limit": 5000, "offset": offset},
                                 timeout=60)
                data = r.json().get("data") or {}
            except Exception as e:
                print("  请求失败", code, type(e).__name__)
                time.sleep(1.5)
                break
            fields = data.get("fields") or fields
            items = data.get("items") or []
            if not items:
                break
            rows.extend(items)
            if not data.get("has_more"):
                break
            offset += len(items)  # 代理单页上限 3000，按实际条数翻页，避免跳行
            time.sleep(0.5)
        if rows:
            df = pd.DataFrame(rows, columns=fields)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df.sort_values("trade_date")
        time.sleep(1.5)  # 空返回多为限流，重试
    return None


def main():
    frames = []
    for code, name in CODES.items():
        df = fetch(code)
        if df is None:
            print("无数据:", name)
            continue
        df["name"] = name
        frames.append(df)
        print(name, len(df), df["trade_date"].min().date(), "→", df["trade_date"].max().date())
    if not frames:
        return
    out = pd.concat(frames, ignore_index=True)
    keep = ["name", "ts_code", "trade_date", "pe", "pe_ttm", "pb",
            "turnover_rate", "turnover_rate_f", "total_mv", "float_mv"]
    out = out[[c for c in keep if c in out.columns]]
    out.to_csv(OUT, index=False)
    print("已保存:", OUT, "|", len(out), "行")


if __name__ == "__main__":
    main()
