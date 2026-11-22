# -*- coding: utf-8 -*-
"""用工作区缓存重算融资余额 / A股总市值，仅更新 data-cur.js 的 indicators.margin。"""
from pathlib import Path
import json
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from margin_quality import complete_margin_dates

CACHE = ROOT / "data" / "cache"
TARGET = ROOT / "web" / "data-cur.js"
PREFIX = "window.WAW=Object.assign(window.WAW||{},"


def weekly_last(df, date_col):
    work = df.sort_values(date_col).copy()
    work["_week"] = work[date_col].dt.to_period("W")
    return work.loc[work.groupby("_week")[date_col].idxmax()].reset_index(drop=True)


def main():
    margin = pd.read_csv(CACHE / "margin_full.csv", dtype={"trade_date": str})
    valid = complete_margin_dates(margin)
    margin["_date"] = pd.to_datetime(margin["trade_date"].astype(str).str.replace("-", "", regex=False).str.slice(0, 8), format="%Y%m%d", errors="coerce")
    incomplete = sorted(set(margin["_date"].dropna()) - valid)
    margin = margin[margin["_date"].isin(valid)].copy()
    margin["rzye"] = pd.to_numeric(margin["rzye"], errors="coerce")
    daily = margin.groupby("_date", as_index=False)["rzye"].sum()

    market = pd.read_parquet(CACHE / "market_daily.parquet", columns=["date", "total_mv"])
    market["date"] = pd.to_datetime(market["date"])
    market["total_mv"] = pd.to_numeric(market["total_mv"], errors="coerce")
    market = market.dropna(subset=["date", "total_mv"]).drop_duplicates("date", keep="last")
    merged = daily.merge(market, left_on="_date", right_on="date", how="inner")
    merged["margin_ratio"] = merged["rzye"] / (merged["total_mv"] * 1e4) * 100
    weekly = weekly_last(merged.dropna(subset=["margin_ratio"]), "_date")

    raw = TARGET.read_text(encoding="utf-8")
    if not raw.startswith(PREFIX):
        raise ValueError("data-cur.js 格式不符合预期")
    payload = json.loads(raw[len(PREFIX):raw.rfind(");")])
    payload.setdefault("indicators", {})["margin"] = {
        "dates": weekly["_date"].dt.strftime("%Y-%m-%d").tolist(),
        "values": [round(float(v), 2) for v in weekly["margin_ratio"]],
    }
    TARGET.write_text(PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ");\n", encoding="utf-8")

    latest = weekly.iloc[-1]
    print("剔除不完整交易日：", "、".join(d.strftime("%Y-%m-%d") for d in incomplete[-8:]) or "无")
    print("融资指标最新有效日期：", latest["_date"].strftime("%Y-%m-%d"), "比率：", round(float(latest["margin_ratio"]), 4))
    print("已更新：", TARGET)


if __name__ == "__main__":
    main()
