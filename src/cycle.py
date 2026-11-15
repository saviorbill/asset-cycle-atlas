# -*- coding: utf-8 -*-
"""牛熊周期识别：ZigZag 峰谷分段 + 最小持续期/幅度过滤。

输出：[(phase, start_idx, end_idx, start_val, end_val, ret_pct, days)]
phase: bull=谷底→峰顶, bear=峰顶→谷底
"""
import pandas as pd
import numpy as np
from config import INDEX_CSV, BB_THRESHOLD, BB_MIN_DAYS


def load_index() -> pd.DataFrame:
    df = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    return df


def zigzag_pivots(series, threshold=BB_THRESHOLD):
    """返回已确认的转折点 [(idx, value, 'peak'|'trough')]。"""
    n = len(series)
    if n < 3:
        return []
    s = series.reset_index(drop=True)
    pivots = [(0, float(s.iloc[0]), "peak" if s.iloc[1] <= s.iloc[0] else "trough")]
    direction = 1 if s.iloc[1] > s.iloc[0] else -1   # 1=向上找顶, -1=向下找底
    ext_idx, ext_val = 0, float(s.iloc[0])
    for i in range(1, n):
        v = float(s.iloc[i])
        if direction == 1:
            if v > ext_val:
                ext_idx, ext_val = i, v
            elif ext_val > 0 and (ext_val - v) / ext_val >= threshold:
                pivots.append((ext_idx, ext_val, "peak"))
                direction = -1
                ext_idx, ext_val = i, v
        else:
            if v < ext_val:
                ext_idx, ext_val = i, v
            elif ext_val > 0 and (v - ext_val) / ext_val >= threshold:
                pivots.append((ext_idx, ext_val, "trough"))
                direction = 1
                ext_idx, ext_val = i, v
    return pivots


def detect_cycles(df=None, idx_col="上证指数", threshold=BB_THRESHOLD, min_days=BB_MIN_DAYS,
                  min_ret_pct=15.0):
    """把转折点两两配对为 bull(bear) 段，过滤短段。"""
    if df is None:
        df = load_index()
    piv = zigzag_pivots(df[idx_col], threshold)
    rows = []
    for k in range(len(piv) - 1):
        i, v0, t0 = piv[k]
        j, v1, t1 = piv[k + 1]
        if j - i < min_days:
            continue
        ret = (v1 / v0 - 1) * 100
        # t0=trough→t1=peak 为 bull；t0=peak→t1=trough 为 bear
        if t0 == "trough" and t1 == "peak":
            phase = "bull"
            if ret < min_ret_pct:
                continue
        elif t0 == "peak" and t1 == "trough":
            phase = "bear"
            if abs(ret) < min_ret_pct:
                continue
        else:
            continue
        rows.append({
            "phase": phase,
            "start": df["date"].iloc[i],
            "end": df["date"].iloc[j],
            "start_val": round(v0, 2),
            "end_val": round(v1, 2),
            "ret_pct": round(ret, 2),
            "days": j - i,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = load_index()
    cyc = detect_cycles(df)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 100)
    print(cyc.to_string(index=False))
    print("\n最新:", df["date"].iloc[-1].date(), "上证:", round(df["上证指数"].iloc[-1], 2))
