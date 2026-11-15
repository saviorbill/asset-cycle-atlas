# -*- coding: utf-8 -*-
"""补齐 panel 源分片 daily_YYYYMMDD.parquet 的覆盖缺口。

背景：有 30 个交易日的 daily 分片只有约 55% 的股票（daily_basic 是完整的），
导致面板聚合的总市值/成交额/广度等指标在这些日期失真。

做法：用 datahubco 的 daily 接口按日重新拉取，过滤到中证全指成份股，
覆盖对应分片；原分片先备份到 _fetch_csi_full/_backup_gapfix_YYYYMMDD/。

用法：python3 src/repair_daily_gaps.py
"""
import os
import shutil
import sys
import time

import pandas as pd
import requests

SRC = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SRC)
sys.path.insert(0, SRC)
from fetch_api_data import BASE, HEAD  # noqa: E402

DATA = "/Users/kunrongcai/Desktop/A股数据"
WORK = os.path.join(DATA, "_fetch_csi_full")
BACKUP = os.path.join(WORK, "_backup_gapfix_20261114")
STAMP = "20261114"

BAD_DATES = [
    "20250926", "20250929", "20250930", "20251009", "20251013",
    "20251014", "20251015", "20251016", "20251017", "20251020",
    "20251021", "20251022", "20251023", "20251024", "20251027",
    "20251028", "20251029", "20251030", "20251031", "20260210",
    "20260211", "20260212", "20260213", "20260224", "20260225",
    "20260226", "20260227", "20260326", "20260327", "20260331",
]


def universe():
    cons = pd.read_csv(os.path.join(DATA, "cons_csi_all.csv"))
    exch = cons["交易所"].map({"深圳证券交易所": "SZ", "上海证券交易所": "SH",
                               "北京证券交易所": "BJ"})
    codes = cons["成分券代码"].astype(int).astype(str).str.zfill(6)
    return set((codes + "." + exch).tolist())


def fetch_day(dt, codes):
    rows, fields, offset = [], None, 0
    while True:
        params = {"trade_date": dt, "limit": 5000, "offset": offset}
        for attempt in range(6):
            try:
                r = requests.get(BASE + "daily", headers=HEAD, params=params, timeout=60)
                if r.status_code == 429:
                    wait = 15 + attempt * 10
                    print("  429，等待 %ds 重试..." % wait, flush=True)
                    time.sleep(wait)
                    continue
                j = r.json()
                if j.get("code") != 0:
                    raise RuntimeError("code=%s msg=%s" % (j.get("code"), j.get("msg")))
                break
            except Exception as e:
                if attempt == 5:
                    raise
                print("  重试 %s: %r" % (dt, e), flush=True)
                time.sleep(5 * (attempt + 1))
        data = j.get("data") or {}
        fields = data.get("fields") or fields
        items = data.get("items") or []
        rows.extend(items)
        if not data.get("has_more") or not items:
            break
        offset += 5000
        time.sleep(1.0)
    if not rows:
        raise RuntimeError("%s 返回空" % dt)
    df = pd.DataFrame(rows, columns=fields)
    df = df[df["ts_code"].isin(codes)].copy()
    return df


def main():
    os.makedirs(BACKUP, exist_ok=True)
    codes = universe()
    print("成份股:", len(codes), flush=True)
    for i, dt in enumerate(BAD_DATES, 1):
        path = os.path.join(WORK, "daily_%s.parquet" % dt)
        old = pd.read_parquet(path)
        basic_n = len(pd.read_parquet(os.path.join(WORK, "daily_basic_%s.parquet" % dt),
                                      columns=["ts_code"]))
        new = fetch_day(dt, codes)
        # 保持原分片列顺序/字段
        new = new.reindex(columns=list(old.columns))
        ratio = len(new) / basic_n if basic_n else 0
        print("[%02d/%d] %s old=%d new=%d daily_basic=%d ratio=%.3f"
              % (i, len(BAD_DATES), dt, len(old), len(new), basic_n, ratio), flush=True)
        if ratio < 0.95 or ratio > 1.05:
            raise RuntimeError("%s 覆盖仍异常: %d / %d" % (dt, len(new), basic_n))
        bak = os.path.join(BACKUP, "daily_%s.parquet" % dt)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        new.to_parquet(path, index=False)
        time.sleep(3.0)
    print("完成：%d 个分片已补齐" % len(BAD_DATES), flush=True)


if __name__ == "__main__":
    main()
