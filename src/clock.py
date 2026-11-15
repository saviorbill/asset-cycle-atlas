# -*- coding: utf-8 -*-
"""投资时钟：用宏观数据给当前经济阶段打标（美林4阶段 + 7阶段扩展）。

输入：GDP当季同比、CPI当月同比、PPI、M2、PMI、LPR1Y。
输出：月度阶段标签序列 + 当前阶段。
阶段(美林4): 复苏 / 过热 / 滞胀 / 衰退
7阶段扩展: 衰退前/衰退后/复苏前/复苏后/过热/滞胀前/滞胀后（股票做多区间=②③④⑤）
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MACRO


def load_monthly_macro():
    """构建月度宏观表。"""
    gdp = pd.read_csv(MACRO["gdp"])
    gdp["month"] = gdp["quarter"].str.replace("Q1", "03").str.replace("Q2", "06") \
        .str.replace("Q3", "09").str.replace("Q4", "12").astype(int)
    gdp = gdp[["month", "gdp_yoy"]].dropna(subset=["gdp_yoy"])

    cpi = pd.read_csv(MACRO["cpi"])
    cpi = cpi[["month", "nt_yoy"]].rename(columns={"nt_yoy": "cpi_yoy"})

    ppi = pd.read_csv(MACRO["ppi"])
    ppi_col = [c for c in ppi.columns if c not in ("month",)]
    ppi["ppi_yoy"] = ppi[ppi_col[0]]
    ppi = ppi[["month", "ppi_yoy"]]

    m2 = pd.read_csv(MACRO["m2"])
    m2 = m2[["month", "m2_yoy"]]

    pmi = pd.read_csv(MACRO["pmi"])
    pmi = pmi[["month", "pmi010000"]].rename(columns={"pmi010000": "pmi"})

    lpr = pd.read_csv(MACRO["lpr"])
    lpr["date"] = pd.to_datetime(lpr["date"].astype(str), format="%Y%m%d")
    lpr["month"] = lpr["date"].dt.year * 100 + lpr["date"].dt.month
    lpr = lpr.groupby("month")["1y"].last().reset_index().rename(columns={"1y": "lpr1y"})

    df = gdp.merge(cpi, on="month", how="outer").merge(ppi, on="month", how="outer") \
        .merge(m2, on="month", how="outer").merge(pmi, on="month", how="outer") \
        .merge(lpr, on="month", how="outer")
    df = df.sort_values("month").reset_index(drop=True)
    # GDP 季度→月度前向填充
    df["gdp_yoy"] = df["gdp_yoy"].ffill()
    df["ym"] = (df["month"] // 100).astype(str) + "-" + (df["month"] % 100).astype(str).str.zfill(2)
    return df


def tag_merrill(df, gdp_win=2, cpi_win=3):
    """美林4阶段：GDP同比趋势 × CPI同比趋势。趋势=当前 vs 前N期移动均值。"""
    d = df.copy()
    d["gdp_ma"] = d["gdp_yoy"].rolling(gdp_win, min_periods=1).mean()
    d["gdp_prev"] = d["gdp_yoy"].shift(gdp_win).rolling(gdp_win, min_periods=1).mean()
    d["cpi_ma"] = d["cpi_yoy"].rolling(cpi_win, min_periods=1).mean()
    d["cpi_prev"] = d["cpi_yoy"].shift(cpi_win).rolling(cpi_win, min_periods=1).mean()

    g_up = d["gdp_ma"] >= d["gdp_prev"]
    c_up = d["cpi_ma"] >= d["cpi_prev"]
    stage = np.select(
        [g_up & ~c_up, g_up & c_up, ~g_up & c_up, ~g_up & ~c_up],
        ["复苏", "过热", "滞胀", "衰退"], default="衰退")
    d["stage4"] = stage
    return d


def tag_7stage(d):
    """在4阶段基础上用名义/实际利率扩展为7阶段。简化：利率下行→偏后期，上行→偏前期。"""
    d = d.copy()
    d["real_rate"] = d["lpr1y"] - d["cpi_yoy"]
    d["rate_trend"] = d["lpr1y"].diff()

    def map7(row):
        s = row["stage4"]
        rt = row["rate_trend"]
        if s == "衰退":
            return "衰退后期" if (rt <= 0) else "衰退前期"
        if s == "复苏":
            return "复苏后期" if (rt <= 0) else "复苏前期"
        if s == "过热":
            return "过热"
        if s == "滞胀":
            return "滞胀后期" if (rt > 0) else "滞胀前期"
        return s
    d["stage7"] = d.apply(map7, axis=1)
    return d


def current_stage():
    d = load_monthly_macro()
    d = tag_merrill(d)
    d = tag_7stage(d)
    last = d.iloc[-1]
    return {
        "asof_month": last["ym"],
        "stage4": last["stage4"],
        "stage7": last["stage7"],
        "gdp_yoy": None if pd.isna(last["gdp_yoy"]) else round(float(last["gdp_yoy"]), 2),
        "cpi_yoy": None if pd.isna(last["cpi_yoy"]) else round(float(last["cpi_yoy"]), 2),
        "ppi_yoy": None if pd.isna(last["ppi_yoy"]) else round(float(last["ppi_yoy"]), 2),
        "m2_yoy": None if pd.isna(last["m2_yoy"]) else round(float(last["m2_yoy"]), 2),
        "pmi": None if pd.isna(last["pmi"]) else round(float(last["pmi"]), 2),
        "lpr1y": None if pd.isna(last["lpr1y"]) else round(float(last["lpr1y"]), 2),
        "real_rate": None if pd.isna(last["real_rate"]) else round(float(last["real_rate"]), 2),
    }


if __name__ == "__main__":
    d = load_monthly_macro()
    d = tag_merrill(d)
    d = tag_7stage(d)
    # 打印近24个月
    print(d[["ym", "gdp_yoy", "cpi_yoy", "pmi", "lpr1y", "stage4", "stage7"]].tail(24).to_string(index=False))
    print("\n当前阶段:", current_stage())
