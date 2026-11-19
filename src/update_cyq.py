# -*- coding: utf-8 -*-
"""筹码分布（cyq_perf）增量更新 —— 获利比例是"套牢 / 绝望"维度的核心指标。

背景：alt_cyq_perf_tushare.csv 曾在 2026-08-04 停更 3.5 个月，
      而状态打分直接读它，导致"全市场获利比例"显示 61%（88 分位），
      真实值其实是 9%（2 分位）—— 方向完全相反。所以这个必须能增量更新。

用法：
    python3 src/update_cyq.py            # 增量更新到最近交易日
    python3 src/update_cyq.py 20261118   # 指定截止日
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NO_PROXY", "*")
from config import CYQ_CSV  # noqa: E402
from update_tushare import get_pro, call  # noqa: E402

SUSPECT_CAPS = {3000, 4000, 5000, 8000, 10000, 15000}


def main():
    end = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.today().strftime("%Y%m%d")
    if not os.path.exists(CYQ_CSV):
        print("找不到", CYQ_CSV)
        sys.exit(1)

    old = pd.read_csv(CYQ_CSV, usecols=["trade_date"], dtype={"trade_date": str})
    last = pd.to_datetime(old["trade_date"].str.replace("-", ""), format="%Y%m%d").max()
    print("现有截止 %s，共 %d 行" % (last.date(), len(old)))
    del old

    pro = get_pro()
    cal = call(pro, "trade_cal", exchange="SSE",
               start_date=(last + pd.Timedelta(days=1)).strftime("%Y%m%d"),
               end_date=end)
    if cal is None or not len(cal):
        print("无新交易日")
        return
    days = sorted(cal[cal.is_open == 1]["cal_date"].astype(str).tolist())
    print("待抓 %d 个交易日" % len(days))

    parts, cols = [], None
    for i, d in enumerate(days):
        df = None
        for att in range(4):
            try:
                df = call(pro, "cyq_perf", trade_date=d)
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(3 * (att + 1))
        if df is None or not len(df):
            print("  %s 无数据" % d)
            continue
        if len(df) in SUSPECT_CAPS:
            print("  ⚠ %s 返回 %d 行，疑似撞上网关上限" % (d, len(df)))
        cols = cols or list(df.columns)
        parts.append(df)
        if (i + 1) % 20 == 0:
            print("  %d/%d" % (i + 1, len(days)))
        time.sleep(0.35)

    if not parts:
        print("无增量")
        return

    new = pd.concat(parts, ignore_index=True)
    new = new[cols]
    new.to_csv(CYQ_CSV, mode="a", header=False, index=False)
    print("追加 %d 行 → %s（截止 %s）"
          % (len(new), os.path.basename(CYQ_CSV), new["trade_date"].max()))


if __name__ == "__main__":
    main()
