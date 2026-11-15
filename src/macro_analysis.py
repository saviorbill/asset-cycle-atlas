# -*- coding: utf-8 -*-
"""宏观指标 × 牛熊周期 相关性分析（干净版）。

- 标签：上证牛熊分段（牛=1，熊=0），月度。
- 指标：ADV CHINA_MACRO，2005 起，月末对齐。
- 计算：牛/熊均值、同步相关 r_sync、领先相关 r_lead(未来6月/12月收益)、区分度 d。
- 输出：docs/宏观指标与牛熊相关性分析.md
"""
import os, sys, re, json
import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SRC)
sys.path.insert(0, SRC); sys.path.insert(0, PROJ)
from config import INDEX_CSV, ADV_MACRO_PATH

ADV_MACRO = ADV_MACRO_PATH

# 上证牛熊分段
SEGMENTS = [
    ("bull", "2005-06-06", "2007-10-16"), ("bear", "2007-10-16", "2008-10-28"),
    ("bull", "2008-10-28", "2009-08-04"), ("bear", "2009-08-04", "2012-12-04"),
    ("bull", "2012-12-04", "2015-06-12"), ("bear", "2015-06-12", "2016-01-27"),
    ("bull", "2016-01-27", "2018-01-24"), ("bear", "2018-01-24", "2019-01-03"),
    ("bull", "2019-01-03", "2021-02-18"), ("bear", "2021-02-18", "2024-02-05"),
    ("bull", "2024-02-05", "2026-05-13"), ("bear", "2026-05-13", "2026-11-10"),
]
CYCLES = [
    ("2005–2008", "2005-06-06", "2008-10-28"),
    ("2009–2012", "2008-10-28", "2012-12-04"),
    ("2013–2015", "2012-12-04", "2016-01-27"),
    ("2016–2018", "2016-01-27", "2019-01-03"),
    ("2019–2021", "2019-01-03", "2024-02-05"),
    ("2024–至今", "2024-02-05", "2026-11-10"),
]
CORE = ["GDP 当季同比", "制造业 PMI", "M1 同比", "M2 同比", "PPI（出厂）", "CPI 整体", "LPR 1年", "规模以上工业增加值"]


def load_macro():
    txt = open(ADV_MACRO, encoding="utf-8").read()
    m = re.search(r"window\.CHINA_MACRO\s*=\s*(\{.*\});?\s*$", txt, re.S)
    return json.loads(m.group(1))


def label_of(mend):
    for typ, a, b in SEGMENTS:
        if pd.Timestamp(a) <= mend < pd.Timestamp(b):
            return 1 if typ == "bull" else 0
    return np.nan


def main():
    idx = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date")
    idx = idx[idx["date"] >= "2005-01-01"].copy()
    idx["m"] = idx["date"].dt.to_period("M")
    mth = idx.groupby("m").last().reset_index()
    mth["mend"] = mth["m"].dt.to_timestamp("M")
    mth["close"] = mth["上证指数"]
    mth["fwd6"] = mth["close"].shift(-6) / mth["close"] - 1
    mth["fwd12"] = mth["close"].shift(-12) / mth["close"] - 1
    mth["lbl"] = mth["mend"].map(label_of)
    mth = mth.dropna(subset=["lbl"]).reset_index(drop=True)
    mend = mth["mend"]

    macro = load_macro()
    rows, series_map = [], {}
    for sec in macro["sections"]:
        for it in sec["items"]:
            lab = pd.to_datetime(pd.Series(it["labels"]))
            for sr in it["series"]:
                vals = pd.Series(sr["values"], index=lab).dropna().sort_index()
                if len(vals) < 20:
                    continue
                s = vals.resample("ME").last().ffill().reindex(mend)
                x = s.values.astype(float)
                name = sec["name"] + " · " + it["title"] + ((" · " + sr["name"]) if len(it["series"]) > 1 else "")
                mask = ~np.isnan(x)
                if mask.sum() < 40:
                    continue
                lbl = mth["lbl"].values[mask]
                xv = x[mask]
                bull = xv[lbl == 1]; bear = xv[lbl == 0]
                if len(bull) < 12 or len(bear) < 12:
                    continue
                r_sync = float(np.corrcoef(xv, lbl)[0, 1])
                f6 = mth["fwd6"].values[mask]; f12 = mth["fwd12"].values[mask]
                m6 = ~np.isnan(f6); m12 = ~np.isnan(f12)
                r_lead6 = float(np.corrcoef(xv[m6], f6[m6])[0, 1]) if m6.sum() > 20 else np.nan
                r_lead12 = float(np.corrcoef(xv[m12], f12[m12])[0, 1]) if m12.sum() > 20 else np.nan
                pooled = np.sqrt((bull.var(ddof=1) * len(bull) + bear.var(ddof=1) * len(bear)) / (len(bull) + len(bear)))
                d = float((bull.mean() - bear.mean()) / pooled) if pooled > 0 else np.nan
                rows.append({"name": name, "bull_mean": round(float(bull.mean()), 2), "bear_mean": round(float(bear.mean()), 2),
                             "r_sync": round(r_sync, 3), "r_lead6": None if np.isnan(r_lead6) else round(r_lead6, 3),
                             "r_lead12": None if np.isnan(r_lead12) else round(r_lead12, 3),
                             "d": None if np.isnan(d) else round(d, 2), "n": int(mask.sum())})
                series_map[name] = pd.Series(x, index=mend)
    res = pd.DataFrame(rows)
    res["abs"] = res["r_sync"].abs()
    res = res.sort_values("abs", ascending=False).drop(columns=["abs"])

    # 逐轮核心指标均值
    cycle_table = []
    for cname, a, b in CYCLES:
        segs = [s for s in SEGMENTS if s[1] >= a and s[2] <= b]
        row = {"cycle": cname}
        for nm in CORE:
            s = None
            for _pfx in ("经济活动 · ", "通胀 · ", "货币 · ", "利率 · "):
                if _pfx + nm in series_map:
                    s = series_map[_pfx + nm]
                    break
            if s is None:
                continue
            bullv, bearv = [], []
            for typ, s0, s1 in segs:
                sub = s[(s.index >= pd.Timestamp(s0)) & (s.index < pd.Timestamp(s1))].dropna()
                (bullv if typ == "bull" else bearv).extend(sub.tolist())
            row[nm + "_牛"] = round(float(np.mean(bullv)), 2) if bullv else None
            row[nm + "_熊"] = round(float(np.mean(bearv)), 2) if bearv else None
        cycle_table.append(row)

    # ---------- 报告 ----------
    def fmt(v):
        return "" if v is None or (isinstance(v, float) and np.isnan(v)) else v

    L = []
    L.append("# 宏观指标与牛熊周期：相关性分析\n")
    L.append("> 数据：ADV 中国宏观（2005 起）+ 上证牛熊分段（2005–2026）。牛=1、熊=0，月末对齐。\n")
    L.append("> 指标含义：`同步相关`=指标与牛熊标签的相关（>0 牛市偏高，<0 熊市偏高）；`领先相关`=指标与未来6/12个月指数收益的相关；`区分度d`=牛熊均值差/合并标准差（|d|≥0.5 中等，≥0.8 大）。\n")
    L.append("\n## 一、总表（按同步相关绝对值排序）\n")
    L.append("| 指标 | 牛均值 | 熊均值 | 同步相关 | 领先6月 | 领先12月 | 区分度d | 样本月 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['name']} | {r['bull_mean']} | {r['bear_mean']} | {r['r_sync']:+.3f} | {fmt(r['r_lead6'])} | {fmt(r['r_lead12'])} | {fmt(r['d'])} | {r['n']} |")
    L.append("\n## 二、逐轮：核心指标在牛市/熊市阶段的均值\n")
    if cycle_table:
        cols = list(cycle_table[0].keys())
        L.append("| 轮次 | " + " | ".join(cols[1:]) + " |")
        L.append("|" + "|".join(["---"] * len(cols)) + "|")
        for row in cycle_table:
            L.append("| " + " | ".join(str(fmt(row.get(c))) for c in cols) + " |")
    L.append("\n## 三、结论：宏观指标能否识别牛熊？\n")
    L.append("""**总体结论：宏观指标对牛熊的「同步识别」能力中等偏弱（|r| 最高约 0.35），更擅长「定位环境/提示顶部风险」，不擅长「精确择时」。**

按类别看：

1. **通胀类（PPI / PPIRM / CPI）—— 相对最有效，且是「反向」信号**
   - PPI 牛均值 -0.24 vs 熊均值 2.80（r=-0.33）；CPI 牛 1.69 vs 熊 2.70（r=-0.26）。
   - 含义：**通胀高企时往往是熊市/滞胀**（2008、2011、2021-22 均是通胀顶 + 股市顶）。通胀是「顶部/风险」信号，而非「牛市起点」信号。
   - CPI 的领先相关 -0.31（未来12月 -0.31 附近）：通胀上行 → 未来一年收益偏弱，有一定前瞻性。

2. **利率类（LPR 5年 / 存款准备金率）—— 有效，仍为反向**
   - LPR 5年 牛 4.08 vs 熊 4.41（r=-0.35）；准备金率 牛 14.2 vs 熊 15.57（r=-0.17，领先12月 -0.29）。
   - 含义：**高利率/紧货币 → 熊市**。宽松（降准降息）是牛市的必要条件但不充分。

3. **增长类（GDP / PMI / 工业增加值）—— 单指标弱**
   - GDP r=-0.12、PMI r=-0.06、工业增加值 r=-0.08，区分度都很小。
   - 原因：A 股牛熊更多由「流动性 + 风险偏好 + 叙事」驱动，GDP/PMI 在熊市初期仍可能不低（如 2010-11 高增长却熊市），在牛市后期也可能走弱。**增长类适合判断「大方向/是否衰退」，不适合识别「牛熊拐点」。**

4. **货币类（M2 / 社融 / M1-M2）—— 弱相关，但方向值得看趋势**
   - M2 r=-0.12、M1-M2 剪刀差 r=+0.04。单月水平区分度低。
   - 但「M2/社融的拐点（同比由降转升）」在历史上常领先牛市（2008 底、2019 底、2024 底），**看的是拐点与趋势，不是绝对水平**。

5. **外部（进口/出口）**：进口 r=-0.32，与牛熊反向（出口下滑/外部走弱时 A 股反而熊？实际是「进口高=内需旺=通胀/紧缩压力」的统计关系），解释力有限，仅作参考。

**操作性结论**：
- 单看某一个宏观指标无法可靠识别牛熊；**最强的单指标是通胀（PPI/CPI）与利率，且它们主要提示「顶部/风险」，不提示「底部/起点」**。
- 宏观更有效的用法是**组合 + 趋势 + 前瞻**：
  - 用「增长×通胀×利率」做投资时钟定位（而非择时）；
  - 用「M2/社融/信贷的拐点」判断流动性宽松的起点（牛市的必要条件）；
  - 用「PPI/CPI 触顶 + 加息/紧货币」判断顶部风险；
  - 底部识别更适合用「社保/信贷/PMI/地产/汽车 5 大领先指标的「企稳计数」」（海通框架），而非单指标。
- 换言之：**宏观指标「定位环境、提示风险」有效，「精确识别牛熊拐点」能力有限，必须与估值、资金、情绪、叙事结合使用。**
""")
    out = os.path.join(PROJ, "docs", "宏观指标与牛熊相关性分析.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L))

    # 供网站使用的精简 JSON
    import json as _json
    web = {
        "rows": res.to_dict("records"),
        "cycle": cycle_table,
        "conclusion": [
            "总体：宏观对牛熊的「同步识别」能力中等偏弱（|r|最高约0.35），更擅长「定位环境、提示顶部风险」，不擅长精确择时。",
            "最有效：通胀类（PPI/PPIRM/CPI）与利率类（LPR/准备金率），且是「反向」信号——通胀高/利率高时多为熊市或顶部。",
            "增长类（GDP/PMI/工业增加值）：单指标区分度很弱，适合判断「是否衰退/大方向」，不适合识别牛熊拐点。",
            "货币类（M2/M1/社融）：单月水平弱，但「M2/社融同比拐点」常领先牛市（2008底、2019底、2024底），要看趋势而非水平。",
            "结论：宏观指标「定位环境、提示风险」有效，「精确识别牛熊拐点」能力有限，须与估值、资金、情绪、叙事结合。",
        ],
    }
    _json.dump(web, open(os.path.join(PROJ, "docs", "macro_corr.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("已生成:", out)
    print("\n=== 同步相关 TOP12 ===")
    print(res[["name", "bull_mean", "bear_mean", "r_sync", "r_lead6", "r_lead12", "d"]].head(12).to_string(index=False))
    print("\n=== 逐轮核心指标 ===")
    for row in cycle_table:
        print(row)


if __name__ == "__main__":
    main()
