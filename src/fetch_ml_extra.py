# -*- coding: utf-8 -*-
"""补齐 Tushare 网关里尚未落地的「机器学习用」数据。

凭证只从环境变量读取，不写入任何文件：
    export TUSHARE_TOKEN=你的_token

用法：
    python3 src/fetch_ml_extra.py check      # 看各数据集已落盘情况
    python3 src/fetch_ml_extra.py options    # 指数期权日线（SSE/SZSE/CFFEX，2015-02 起）
    python3 src/fetch_ml_extra.py futures    # 期货日线（含主力连续与期限结构）+ 合约表（2010-04 起）
    python3 src/fetch_ml_extra.py weights    # 指数成分权重（逐月，2008 起）
    python3 src/fetch_ml_extra.py industry   # 申万行业指数日线 + 分类（2008 起）
    python3 src/fetch_ml_extra.py margin     # 个股两融明细（2010-04 起）
    python3 src/fetch_ml_extra.py macro      # 汇率 / 美债 / 全球指数（日频外部驱动）
    python3 src/fetch_ml_extra.py flows      # ETF 份额（2016 起）
    python3 src/fetch_ml_extra.py corporate  # 停复牌 / 改名 / 解禁 / 质押 / 回购 / 增减持
    python3 src/fetch_ml_extra.py all        # 按价值顺序全部补齐

落盘位置：/Users/kunrongcai/Desktop/A股数据/ml_data/<数据集>/<数据集>_<年份>.parquet
断点续传：已存在的年份文件直接跳过；删掉对应文件即可重抓该年。

口径提示：
  - 期货、期权都是「交易所原始口径」，未复权、未对齐。
  - index_weight 是月末快照，用它在任意日期重建当时的成分股与权重，
    才能做无生存偏差的广度/集中度特征。
  - 事件类（解禁/质押/回购/增减持/改名）一律用公告日 ann_date 对齐，
    否则会前视。
"""
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

os.environ.setdefault("NO_PROXY", "*")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_tushare import DATA_DIR, SLEEP, RETRY, get_pro, call   # noqa: E402

OUT = os.path.join(DATA_DIR, "ml_data")
END = os.environ.get("ML_END") or datetime.now().strftime("%Y%m%d")

OPT_EXCH = ["SSE", "SZSE", "CFFEX"]
OPT_START = "20150209"
FUT_START = "20100416"
WEIGHT_START = "20080101"
WEIGHT_INDEX = ["000300.SH", "000905.SH", "000852.SH", "000001.SH",
                "399006.SZ", "000688.SH", "932000.CSI"]
MARGIN_START = "20100401"
SW_START = "20080101"
FLOW_START = "20160101"
CORP_START = "20080101"
MACRO_START = "20090101"

FX_CODES = ["USDCNH.FXCM", "USDCNY.FXCM", "EURUSD.FXCM", "USDJPY.FXCM"]


def ddir(name):
    p = os.path.join(OUT, name)
    os.makedirs(p, exist_ok=True)
    return p


def fpath(name, key):
    return os.path.join(ddir(name), "%s_%s.parquet" % (name, key))


def note(name, msg):
    print("  [%s] %s" % (name, msg), flush=True)


# ------------------------------------------------------------------
# 交易日历（按年缓存）
# ------------------------------------------------------------------
_CAL = {}


def cal_year(pro, year):
    if year in _CAL:
        return _CAL[year]
    p = fpath("trade_cal", year)
    if os.path.exists(p):
        d = pd.read_parquet(p)
    else:
        d = call(pro, "trade_cal", exchange="SSE", start_date="%d0101" % year,
                 end_date="%d1231" % year, is_open="1")
        if d is None:
            d = pd.DataFrame(columns=["cal_date"])
        d = d.assign(cal_date=d["cal_date"].astype(str))
        d[["cal_date"]].to_parquet(p, index=False)
        time.sleep(SLEEP)
    days = sorted(d["cal_date"].tolist())
    _CAL[year] = days
    return days


def years_between(start, end):
    return list(range(int(start[:4]), int(end[:4]) + 1))


def clamp_days(days, start, end):
    return [d for d in days if start <= d <= end]


# ------------------------------------------------------------------
# 1. 指数期权
# ------------------------------------------------------------------
def fetch_options(pro):
    note("options", "起点 %s → %s，每交易日 SSE/SZSE/CFFEX 三次调用" % (OPT_START, END))
    t0 = time.time()
    n_days = 0
    for y in years_between(OPT_START, END):
        p = fpath("opt_daily", y)
        if os.path.exists(p):
            note("options", "%d 已存在，跳过" % y)
            continue
        days = clamp_days(cal_year(pro, y), OPT_START, END)
        rows = []
        for i, d in enumerate(days, 1):
            for ex in OPT_EXCH:
                df = call(pro, "opt_daily", trade_date=d, exchange=ex)
                if df is not None and len(df):
                    rows.append(df)
            if i % 50 == 0:
                note("options", "%d %d/%d 天，累计 %d 行，%.0fs"
                     % (y, i, len(days), sum(len(x) for x in rows), time.time() - t0))
        if rows:
            out = pd.concat(rows, ignore_index=True)
            out.drop_duplicates(["ts_code", "trade_date"], inplace=True)
            out.to_parquet(p, index=False)
            note("options", "%d 落盘 %d 行" % (y, len(out)))
        n_days += len(days)
    # 合约表
    p = fpath("opt_basic", "all")
    if not os.path.exists(p):
        parts = []
        for ex in OPT_EXCH:
            d = call(pro, "opt_basic", exchange=ex)
            if d is not None:
                parts.append(d)
        if parts:
            pd.concat(parts, ignore_index=True).to_parquet(p, index=False)
            note("opt_basic", "落盘 %d 行" % sum(len(x) for x in parts))
    note("options", "完成 %d 个交易日，%.0f 分钟" % (n_days, (time.time() - t0) / 60))


# ------------------------------------------------------------------
# 2. 期货（股指期货为主，顺带全市场 CFFEX 合约）
# ------------------------------------------------------------------
def fetch_futures(pro):
    note("futures", "起点 %s → %s" % (FUT_START, END))
    t0 = time.time()
    for y in years_between(FUT_START, END):
        p = fpath("fut_daily", y)
        if os.path.exists(p):
            note("futures", "%d 已存在，跳过" % y)
            continue
        days = clamp_days(cal_year(pro, y), FUT_START, END)
        rows = []
        for i, d in enumerate(days, 1):
            df = call(pro, "fut_daily", trade_date=d)
            if df is not None and len(df):
                rows.append(df[df["ts_code"].str.endswith(".CFX")])
            if i % 100 == 0:
                note("futures", "%d %d/%d 天，%.0fs" % (y, i, len(days), time.time() - t0))
        if rows:
            out = pd.concat(rows, ignore_index=True)
            out.drop_duplicates(["ts_code", "trade_date"], inplace=True)
            out.to_parquet(p, index=False)
            note("futures", "%d 落盘 %d 行" % (y, len(out)))
    # fut_daily 已含 IF.CFX 主力连续 + IFL/IFL1/IFL2/IFL3 期限结构，
    # 不必再抓 fut_mapping（该接口单次上限 5,000 行，会悄悄截断）。
    p = fpath("fut_basic", "all")
    if not os.path.exists(p):
        d = call(pro, "fut_basic", exchange="CFFEX")
        if d is not None and len(d):
            d.to_parquet(p, index=False)
            note("fut_basic", "落盘 %d 行" % len(d))
    note("futures", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 3. 指数成分权重（月末快照）
# ------------------------------------------------------------------
def fetch_weights(pro):
    note("weights", "%s → %s，逐月" % (WEIGHT_START, END))
    t0 = time.time()
    for code in WEIGHT_INDEX:
        for y in years_between(WEIGHT_START, END):
            p = fpath("index_weight", "%s_%s" % (code.replace(".", "_"), y))
            if os.path.exists(p):
                continue
            parts = []
            for m in range(1, 13):
                s = "%d%02d01" % (y, m)
                e = "%d%02d31" % (y, m) if m in (1, 3, 5, 7, 8, 10, 12) else "%d%02d30" % (y, m)
                if m == 2:
                    e = "%d0228" % y
                if s > END:
                    break
                d = call(pro, "index_weight", index_code=code,
                         start_date=s, end_date=min(e, END))
                if d is not None and len(d):
                    parts.append(d)
            if parts:
                out = pd.concat(parts, ignore_index=True)
                out.drop_duplicates(["index_code", "con_code", "trade_date"],
                                    inplace=True)
                out.to_parquet(p, index=False)
                note("index_weight", "%s %d 共 %d 行" % (code, y, len(out)))
    note("weights", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 4. 申万行业
# ------------------------------------------------------------------
def fetch_industry(pro):
    t0 = time.time()
    p = fpath("index_classify", "all")
    cls = None
    if os.path.exists(p):
        cls = pd.read_parquet(p)
    else:
        frames = []
        for lvl in ("L1", "L2", "L3"):
            d = call(pro, "index_classify", level=lvl)
            if d is not None and len(d):
                d["level"] = lvl
                frames.append(d)
        if frames:
            cls = pd.concat(frames, ignore_index=True)
            cls.to_parquet(p, index=False)
            note("index_classify", "落盘 %d 行" % len(cls))
    p = fpath("index_member", "all")
    if not os.path.exists(p):
        d = call(pro, "index_member_all")
        if d is not None and len(d):
            d.to_parquet(p, index=False)
            note("index_member", "落盘 %d 行" % len(d))
    codes = []
    if cls is not None:
        l1 = cls[cls["level"] == "L1"]
        codes = sorted(l1["index_code"].unique())
        if not codes:
            codes = sorted(cls["index_code"].unique())[:40]
    else:
        codes = ["801010.SI"]
    note("industry", "行业指数 %d 个，%s → %s" % (len(codes), SW_START, END))
    for i, code in enumerate(codes, 1):
        for y in years_between(SW_START, END):
            p = fpath("sw_daily", "%s_%s" % (code.replace(".", "_"), y))
            if os.path.exists(p):
                continue
            d = call(pro, "sw_daily", ts_code=code, start_date="%d0101" % y,
                     end_date=min("%d1231" % y, END))
            if d is not None and len(d):
                d.to_parquet(p, index=False)
        if i % 5 == 0:
            note("industry", "%d/%d 个行业，%.0fs" % (i, len(codes), time.time() - t0))
    note("industry", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 5. 个股两融明细
# ------------------------------------------------------------------
def fetch_margin(pro):
    note("margin_detail", "%s → %s，逐日" % (MARGIN_START, END))
    t0 = time.time()
    for y in years_between(MARGIN_START, END):
        p = fpath("margin_detail", y)
        if os.path.exists(p):
            note("margin_detail", "%d 已存在，跳过" % y)
            continue
        days = clamp_days(cal_year(pro, y), MARGIN_START, END)
        rows = []
        for i, d in enumerate(days, 1):
            df = call(pro, "margin_detail", trade_date=d)
            if df is not None and len(df):
                rows.append(df)
            if i % 100 == 0:
                note("margin_detail", "%d %d/%d 天，累计 %d 行，%.0fs"
                     % (y, i, len(days), sum(len(x) for x in rows), time.time() - t0))
        if rows:
            out = pd.concat(rows, ignore_index=True)
            out.drop_duplicates(["trade_date", "ts_code"], inplace=True)
            out.to_parquet(p, index=False)
            note("margin_detail", "%d 落盘 %d 行" % (y, len(out)))
    note("margin_detail", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 6. 宏观日频（汇率 / 美债 / 全球指数）
# ------------------------------------------------------------------
def fetch_macro(pro):
    t0 = time.time()
    for code in FX_CODES:
        p = fpath("fx_daily", code.replace(".", "_"))
        if os.path.exists(p):
            continue
        parts = []
        for y in years_between(MACRO_START, END):
            d = call(pro, "fx_daily", ts_code=code, start_date="%d0101" % y,
                     end_date=min("%d1231" % y, END))
            if d is not None and len(d):
                parts.append(d)
        if parts:
            out = pd.concat(parts, ignore_index=True)
            out.to_parquet(p, index=False)
            note("fx_daily", "%s 落盘 %d 行" % (code, len(out)))
    p = fpath("us_tycr", "all")
    if not os.path.exists(p):
        parts = []
        for y in years_between(MACRO_START, END):
            d = call(pro, "us_tycr", start_date="%d0101" % y,
                     end_date=min("%d1231" % y, END))
            if d is not None and len(d):
                parts.append(d)
        if parts:
            out = pd.concat(parts, ignore_index=True)
            out.to_parquet(p, index=False)
            note("us_tycr", "落盘 %d 行" % len(out))
    p = fpath("index_global", "all")
    if not os.path.exists(p):
        # 20 只指数 × 每年 250 天 ≈ 5,000 行，超过网关 4,000 行上限会被静默截断，
        # 必须按月抓（每月约 430 行）。
        parts = []
        for per in pd.period_range(MACRO_START[:4] + "-01", END[:4] + "-" + END[4:6],
                                   freq="M"):
            a = per.start_time.strftime("%Y%m%d")
            b = min(per.end_time.strftime("%Y%m%d"), END)
            if a > END:
                break
            d = call(pro, "index_global", start_date=a, end_date=b)
            if d is not None and len(d):
                parts.append(d)
        if parts:
            out = pd.concat(parts, ignore_index=True)
            out.drop_duplicates(["ts_code", "trade_date"], inplace=True)
            out.to_parquet(p, index=False)
            note("index_global", "落盘 %d 行，%d 个交易日" %
                 (len(out), out["trade_date"].nunique()))
    note("macro", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 7. ETF 份额
# ------------------------------------------------------------------
def fetch_flows(pro):
    note("fund_share", "%s → %s，逐日" % (FLOW_START, END))
    t0 = time.time()
    for y in years_between(FLOW_START, END):
        p = fpath("fund_share", y)
        if os.path.exists(p):
            note("fund_share", "%d 已存在，跳过" % y)
            continue
        days = clamp_days(cal_year(pro, y), FLOW_START, END)
        rows = []
        for i, d in enumerate(days, 1):
            df = call(pro, "fund_share", trade_date=d)
            if df is not None and len(df):
                rows.append(df)
            if i % 100 == 0:
                note("fund_share", "%d %d/%d 天，%.0fs" % (y, i, len(days), time.time() - t0))
        if rows:
            out = pd.concat(rows, ignore_index=True)
            out.drop_duplicates(["ts_code", "trade_date"], inplace=True)
            out.to_parquet(p, index=False)
            note("fund_share", "%d 落盘 %d 行" % (y, len(out)))
    note("fund_share", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
# 8. 事件类
# ------------------------------------------------------------------
SUSPECT_CAPS = {3000, 4000, 5000, 8000, 10000, 15000}


def _by_year(pro, name, fn, start, end):
    """按季度切分抓取 —— 网关单次返回有隐藏上限（3k~15k 不等），按年抓会静默截断。"""
    p = fpath(name, "all")
    if os.path.exists(p):
        note(name, "已存在，跳过")
        return
    parts = []
    for per in pd.period_range(start[:4] + "-01", end[:4] + "-" + end[4:6], freq="Q"):
        a = per.start_time.strftime("%Y%m%d")
        b = min(per.end_time.strftime("%Y%m%d"), END)
        if a > END:
            break
        d = fn(a, b)
        if d is not None and len(d):
            parts.append(d)
            if len(d) in SUSPECT_CAPS:
                note(name, "⚠ %s~%s 返回 %d 行，疑似撞上上限" % (a, b, len(d)))
    if parts:
        out = pd.concat(parts, ignore_index=True)
        out.drop_duplicates(inplace=True)
        out.to_parquet(p, index=False)
        note(name, "落盘 %d 行" % len(out))


def fetch_corporate(pro):
    t0 = time.time()
    _by_year(pro, "suspend_d", lambda s, e: call(pro, "suspend_d", start_date=s, end_date=e),
             CORP_START, END)
    _by_year(pro, "namechange", lambda s, e: call(pro, "namechange", start_date=s, end_date=e),
             CORP_START, END)
    _by_year(pro, "share_float", lambda s, e: call(pro, "share_float", start_date=s, end_date=e),
             CORP_START, END)
    _by_year(pro, "repurchase", lambda s, e: call(pro, "repurchase", start_date=s, end_date=e),
             CORP_START, END)
    _by_year(pro, "stk_holdertrade",
             lambda s, e: call(pro, "stk_holdertrade", start_date=s, end_date=e),
             CORP_START, END)
    _by_year(pro, "dividend", lambda s, e: call(pro, "dividend", start_date=s, end_date=e),
             "20100101", END)
    # pledge_stat 不吃 start_date/end_date 区间，只吃单个 end_date（报告期快照）。
    # 之前按区间调用返回空表且不报错，静默落了 0 个文件。改为逐报告期抓。
    # 网关实测只放行部分报告期（2014/2015/2020/2021/2025 年末 + 2024 中 + 2026Q3），
    # 缺口在缺失的报告期上是网关侧限制，不是代码问题。
    p = fpath("pledge_stat", "all")
    if not os.path.exists(p):
        periods = ["%d1231" % y for y in range(2014, 2026)] + \
                  ["%d0331" % y for y in range(2016, 2027)] + \
                  ["%d0630" % y for y in range(2016, 2027)]
        got, parts = [], []
        for d in periods:
            if d > END:
                continue
            df = None
            try:
                df = call(pro, "pledge_stat", end_date=d)
            except Exception:                                       # noqa: BLE001
                pass
            if df is None or not len(df):
                continue
            parts.append(df)
            got.append(d)
            time.sleep(0.4)
        if parts:
            out = pd.concat(parts, ignore_index=True)
            out = out.drop_duplicates(["ts_code", "end_date"])
            out.to_parquet(p, index=False)
            note("pledge_stat", "落盘 %d 行，%d/%d 个报告期"
                 % (len(out), len(got), len(periods)))
            miss = [d for d in periods if d <= END and d not in got]
            if miss:
                note("pledge_stat", "⚠ 网关未返回 %d 个报告期：%s…"
                     % (len(miss), ",".join(miss[:6])))
        else:
            note("pledge_stat", "⚠ 所有报告期均返回空，该数据源不可用")
    note("corporate", "完成，%.0f 分钟" % ((time.time() - t0) / 60))


# ------------------------------------------------------------------
def check():
    if not os.path.isdir(OUT):
        print("尚无 %s" % OUT)
        return
    tot = 0
    for name in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, name)
        if not os.path.isdir(p):
            continue
        files = [f for f in os.listdir(p) if f.endswith(".parquet")]
        size = sum(os.path.getsize(os.path.join(p, f)) for f in files)
        rows = 0
        for f in files:
            try:
                rows += pd.read_parquet(os.path.join(p, f)).shape[0]
            except Exception:
                pass
        tot += rows
        print("%-16s %4d 个文件  %10d 行  %7.1f MB" % (name, len(files), rows, size / 1e6))
    print("%-16s %14d 行" % ("合计", tot))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "check":
        check()
        return
    pro = get_pro()
    os.makedirs(OUT, exist_ok=True)
    print("输出目录 %s\n截止日期 %s\n" % (OUT, END), flush=True)
    steps = {
        "options": fetch_options,
        "futures": fetch_futures,
        "weights": fetch_weights,
        "industry": fetch_industry,
        "margin": fetch_margin,
        "macro": fetch_macro,
        "flows": fetch_flows,
        "corporate": fetch_corporate,
    }
    if mode == "all":
        order = ["options", "futures", "weights", "industry",
                 "margin", "macro", "flows", "corporate"]
    elif mode in steps:
        order = [mode]
    else:
        print(__doc__)
        sys.exit(1)
    for step in order:
        print("=" * 56, flush=True)
        print("开始 %s" % step, flush=True)
        try:
            steps[step](pro)
        except KeyboardInterrupt:
            print("中断，已完成的年份不会重抓", flush=True)
            raise
        except Exception as e:
            print("  %s 失败：%s" % (step, str(e)[:200]), flush=True)
    print("=" * 56)
    check()


if __name__ == "__main__":
    main()
