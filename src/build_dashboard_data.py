# -*- coding: utf-8 -*-
"""生成仪表盘数据 data.js（v2）：整合评分卡 + 主线叙事 + 指数/市场/周期。"""
import os, sys, json
import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SRC)
sys.path.insert(0, SRC)
sys.path.insert(0, PROJ)
from config import INDEX_CSV, CACHE_DIR, DASHBOARD_DIR, CANONICAL_CYCLES, INDEX_COLS
from adv_chart import make_chart_url
import scoring as scoring_mod
import narrative as narrative_mod
import clock as clock_mod
import etf_narrative as etf_mod


def pct_rank(series, value):
    s = series.dropna()
    if len(s) == 0 or value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float((s <= value).mean())


def theme_rank_data():
    """主线榜单：20 主题 250日/120日/60日超额收益 + 状态。"""
    snap = narrative_mod.snapshot()
    return snap


def theme_evolution(top_n=6, days=250):
    """主线演进：top 主题的累计超额收益序列（周频降采样）。"""
    df = narrative_mod.compute_excess()
    # 每主题累计超额（相对各自起点，观察近 days 日）
    df = df.sort_values(["theme", "date"])
    last = df["date"].max()
    win = df[df["date"] >= last - pd.DateOffset(days=int(days * 1.6))].copy()
    # 累计超额
    win["cum"] = win.groupby("theme")["excess"].cumsum()
    # 选 top 主题（按最新累计）
    latest = win.groupby("theme")["cum"].last().sort_values(ascending=False)
    top = latest.index[:top_n].tolist()
    pivot = win[win["theme"].isin(top)].pivot(index="date", columns="theme", values="cum")
    # 周频
    pivot = pivot.resample("W").last()
    return {"dates": pivot.index.strftime("%Y-%m-%d").tolist(),
            "series": {t: [round(float(v) * 100, 1) if pd.notna(v) else None for v in pivot[t]] for t in top},
            "themes": top}


def main():
    df = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    mkt = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    mkt["date"] = pd.to_datetime(mkt["date"])

    # 指数月频
    df_m = df.copy()
    df_m["ym"] = df_m["date"].dt.to_period("M").astype(str)
    idx_m = df_m.groupby("ym")[INDEX_COLS].last()

    # 市场周频
    mkt["w"] = mkt["date"].dt.to_period("W").astype(str)
    mkt_w = mkt.groupby("w").agg({
        "pe_median": "last", "pb_median": "last", "turnover_median": "last",
        "amount": "last", "up_ratio": "last", "concentration_top5": "last",
        "total_mv": "last",
    }).reset_index()

    # 综合评分卡
    score = scoring_mod.scorecard()

    # 主线榜单 + 演进
    theme_rank = theme_rank_data()
    theme_evo = theme_evolution()

    # ETF 起涨信号
    etf_snap = etf_mod.snapshot()

    # 投资时钟历史（近5年）
    clk = clock_mod.load_monthly_macro()
    clk = clock_mod.tag_merrill(clk)
    clk = clock_mod.tag_7stage(clk)
    clk = clk[clk["month"] >= (clk["month"].max() - 500)].tail(60)

    # ADV 链接
    df["year"] = df["date"].dt.year
    yearly = df.groupby("year")["上证指数"].last()
    adv1 = make_chart_url("area", "上证指数年度收盘（1990–2026）· 长期牛熊弧线",
        [str(y) for y in yearly.index], [{"name": "上证指数", "values": [round(v, 1) for v in yearly.values]}], palette="consult")
    # 主线榜单横向排名
    adv2 = make_chart_url("rank", "主题板块 250日超额收益排行（主线识别）",
        [r["theme"] for r in theme_rank["themes"]],
        [{"name": "250日超额%", "values": [r["excess_250d"] if r["excess_250d"] is not None else 0 for r in theme_rank["themes"]]}],
        palette="burgundy", unit="%")
    # ETF 主题 60日 vs 250日超额（起涨识别）
    adv3 = make_chart_url("bar", "ETF主题 60日超额收益（起涨信号）",
        [r["theme"] for r in etf_snap["themes"]],
        [{"name": "60日超额%", "values": [r["excess_60d"] for r in etf_snap["themes"]]}],
        palette="forest", unit="%")

    payload = {
        "asof_index": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "asof_market": mkt["date"].iloc[-1].strftime("%Y-%m-%d"),
        "cycles": CANONICAL_CYCLES,
        "index": {"dates": idx_m.index.tolist(),
                  "series": {c: [round(float(v), 2) if pd.notna(v) else None for v in idx_m[c].values] for c in INDEX_COLS}},
        "market": {
            "dates": mkt_w["w"].tolist(),
            "pe_median": [round(float(v), 2) if pd.notna(v) else None for v in mkt_w["pe_median"]],
            "pb_median": [round(float(v), 2) if pd.notna(v) else None for v in mkt_w["pb_median"]],
            "turnover": [round(float(v), 2) if pd.notna(v) else None for v in mkt_w["turnover_median"]],
            "amount": [round(float(v) / 1e8, 0) if pd.notna(v) else None for v in mkt_w["amount"]],
            "up_ratio": [round(float(v) * 100, 1) if pd.notna(v) else None for v in mkt_w["up_ratio"]],
            "concentration": [round(float(v) * 100, 1) if pd.notna(v) else None for v in mkt_w["concentration_top5"]],
        },
        "score": score,
        "theme_rank": theme_rank,
        "theme_evo": theme_evo,
        "etf": etf_snap,
        "clock": {
            "ym": clk["ym"].tolist(),
            "gdp_yoy": [None if pd.isna(v) else round(float(v), 2) for v in clk["gdp_yoy"]],
            "cpi_yoy": [None if pd.isna(v) else round(float(v), 2) for v in clk["cpi_yoy"]],
            "stage4": clk["stage4"].tolist(),
        },
        "adv_links": {"long_history": adv1, "theme_rank": adv2, "etf_rising": adv3},
    }

    out = os.path.join(DASHBOARD_DIR, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.DASH = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    print("已生成:", out)
    print("综合温度:", score.get("composite_temp"), "| 主线:", theme_rank["themes"][0]["theme"] if theme_rank["themes"] else None)
    print("verdict:", score.get("verdict"))


if __name__ == "__main__":
    main()
