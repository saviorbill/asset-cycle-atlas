# -*- coding: utf-8 -*-
"""综合环境评分卡：整合周期位置 + 投资时钟 + 估值/资金/情绪分位 + 主线叙事。

输出一个 scorecard dict，供仪表盘与报告使用。
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR, INDEX_CSV
import clock as clock_mod
import sentiment as sentiment_mod
import narrative as narrative_mod


def _pct_rank(series, value):
    s = series.dropna()
    if len(s) == 0 or value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float((s <= value).mean())


def cycle_position():
    """当前周期位置（简化：最近一轮牛市起点 + 距高点回撤）。"""
    df = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date")
    # 找2024-02-05以来的牛市
    start = pd.Timestamp("2024-02-05")
    seg = df[df["date"] >= start]
    peak = seg["上证指数"].max()
    peak_date = seg.loc[seg["上证指数"].idxmax(), "date"]
    last = seg.iloc[-1]
    drawdown = (last["上证指数"] / peak - 1) * 100
    return {
        "bull_start": "2024-02-05",
        "peak": round(float(peak), 2),
        "peak_date": peak_date.strftime("%Y-%m-%d"),
        "last": round(float(last["上证指数"]), 2),
        "drawdown_from_peak": round(float(drawdown), 1),
        "since_start": round(float(last["上证指数"] / seg["上证指数"].iloc[0] - 1) * 100, 1),
    }


def scorecard():
    out = {}

    # 1) 周期位置
    out["cycle"] = cycle_position()

    # 2) 投资时钟
    out["clock"] = clock_mod.current_stage()

    # 3) 估值/市场温度（market_daily 分位）
    mkt = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    mkt["date"] = pd.to_datetime(mkt["date"])
    cutoff = mkt["date"].max() - pd.DateOffset(years=10)
    m10 = mkt[mkt["date"] >= cutoff]
    last = mkt.iloc[-1]
    last_pe = mkt["pe_median"].dropna()
    last_pe_v = float(last_pe.iloc[-1]) if len(last_pe) else None
    val = {
        "pe_median": round(last_pe_v, 2) if last_pe_v else None,
        "pb_median": round(float(last["pb_median"]), 2) if pd.notna(last["pb_median"]) else None,
        "pe_pctile": round(_pct_rank(m10["pe_median"], last_pe_v) * 100, 1) if last_pe_v else None,
        "pb_pctile": round(_pct_rank(m10["pb_median"], last["pb_median"]) * 100, 1) if pd.notna(last["pb_median"]) else None,
        "turnover_pctile": round(_pct_rank(m10["turnover_median"], last["turnover_median"]) * 100, 1) if pd.notna(last["turnover_median"]) else None,
        "concentration_pctile": round(_pct_rank(m10["concentration_top5"], last["concentration_top5"]) * 100, 1) if pd.notna(last["concentration_top5"]) else None,
        "up_ratio_pctile": round(_pct_rank(m10["up_ratio"], last["up_ratio"]) * 100, 1) if pd.notna(last["up_ratio"]) else None,
        "asof": mkt["date"].iloc[-1].strftime("%Y-%m-%d"),
    }
    out["valuation"] = val

    # 4) 资金/情绪温度
    out["sentiment"] = sentiment_mod.snapshot()

    # 4.5) 风险溢价 ERP 与 顶部/底部风险评分
    lpr = out["clock"].get("lpr1y")
    pe_med = val["pe_median"]
    if pe_med and lpr:
        earnings_yield = 100.0 / pe_med  # 全A盈利收益率(%, 中位数口径)
        erp = earnings_yield - lpr
    else:
        earnings_yield = erp = None
    out["erp"] = {
        "earnings_yield": round(earnings_yield, 2) if earnings_yield else None,
        "risk_free": lpr,
        "erp": round(erp, 2) if erp is not None else None,
    }
    # 顶部风险评分：估值分位 + 成交集中度 + 情绪热度的均值（0-100，越高越接近顶部）
    top_inputs = [val["pe_pctile"], val["concentration_pctile"],
                  (out["sentiment"].get("ths_etf_hot_n_pctile") or 0) * 100]
    top_risk = float(np.mean([x for x in top_inputs if x is not None]))
    # 底部机会评分：估值低 + 广度低(超跌) + 情绪冰点（反向）
    bottom_inputs = [
        100 - (val["pe_pctile"] if val["pe_pctile"] is not None else 50),
        100 - (out["sentiment"].get("margin_buy_ratio_pctile") or 0) * 100,
    ]
    bottom_score = float(np.mean(bottom_inputs))
    out["top_risk_score"] = round(top_risk, 1)
    out["bottom_score"] = round(bottom_score, 1)

    # 5) 主线叙事
    out["narrative"] = narrative_mod.snapshot()

    # 6) 综合温度（加权合成，统一 0-1 分位尺度）
    def _to01(v):
        if v is None:
            return None
        return v / 100 if v > 1 else v  # 兼容 0-100 与 0-1 两种口径

    comps = {
        "估值": _to01(val["pe_pctile"]),
        "换手": _to01(val["turnover_pctile"]),
        "成交集中度": _to01(val["concentration_pctile"]),
        "融资余额": out["sentiment"].get("margin_balance_pctile"),
        "热度": out["sentiment"].get("ths_etf_hot_n_pctile"),
    }
    weights = {"估值": 0.30, "换手": 0.15, "成交集中度": 0.20, "融资余额": 0.15, "热度": 0.20}
    vals = []
    for k, w in weights.items():
        v = comps.get(k)
        if v is not None:
            vals.append((v, w))
    if vals:
        temp = sum(v * w for v, w in vals) / sum(w for _, w in vals)
    else:
        temp = None
    out["composite_temp"] = round(temp * 100, 1) if temp is not None else None

    # 7) 操作含义（规则化文字）
    out["verdict"] = verdict(out)
    return out


def verdict(sc):
    parts = []
    temp = sc["composite_temp"]
    if temp is not None:
        if temp >= 85:
            parts.append("综合温度" + str(temp) + "：偏过热，警惕顶部/止盈")
        elif temp >= 65:
            parts.append("综合温度" + str(temp) + "：偏热，右侧持有+止盈纪律")
        elif temp >= 40:
            parts.append("综合温度" + str(temp) + "：中性，结构分化，聚焦主线")
        elif temp >= 20:
            parts.append("综合温度" + str(temp) + "：偏冷，可左侧布局")
        else:
            parts.append("综合温度" + str(temp) + "：极冷，底部区域")
    cy = sc["cycle"]
    if cy["drawdown_from_peak"] <= -20:
        parts.append("指数距高点回撤" + str(abs(cy["drawdown_from_peak"])) + "%，已进入技术性熊市区域")
    elif cy["drawdown_from_peak"] <= -8:
        parts.append("指数距高点回撤" + str(abs(cy["drawdown_from_peak"])) + "%，高位回调")
    else:
        parts.append("指数距高点回撤" + str(abs(cy["drawdown_from_peak"])) + "%，仍处高位")
    nar = sc["narrative"]["themes"]
    if nar:
        top = nar[0]
        parts.append("当前主线(250日超额)：'" + top["theme"] + "'，叙事状态：" + top["state"])
    clk = sc["clock"]
    parts.append("宏观阶段：" + clk["stage7"] + "（美林" + clk["stage4"] + "）")
    erp = sc.get("erp", {})
    if erp.get("erp") is not None:
        parts.append("风险溢价ERP=" + str(erp["erp"]) + "%（盈利收益率" + str(erp["earnings_yield"]) + "%−无风险" + str(erp["risk_free"]) + "%）")
    parts.append("顶部风险评分" + str(sc.get("top_risk_score")) + "/100，底部机会评分" + str(sc.get("bottom_score")) + "/100")
    return "；".join(parts)


if __name__ == "__main__":
    import json
    sc = scorecard()
    print(json.dumps(sc, ensure_ascii=False, indent=2, default=str))
