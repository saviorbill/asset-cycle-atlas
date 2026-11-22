# -*- coding: utf-8 -*-
"""用 Tushare Pro（自定义网关）增量更新本地数据。

凭证只从环境变量读取，不写入任何文件：
    export TUSHARE_TOKEN=你的_token

用法：
    python3 src/update_tushare.py panel    # 补 daily/daily_basic/adj_factor 分片，重建全A面板
    python3 src/update_tushare.py index    # 补 应用数据/index_daily.csv 八大指数收盘价
    python3 src/update_tushare.py basic    # 刷新 stock_basic_all.csv（保留本地退市行）
    python3 src/update_tushare.py margin   # 补两融余额 应用数据/cache/margin_full.csv
    python3 src/update_tushare.py limit    # 补涨跌停家数 应用数据/cache/limit_daily.csv
    python3 src/update_tushare.py valuation # 补指数估值/换手 应用数据/cache/index_dailybasic.csv（全历史）
    python3 src/update_tushare.py all      # 依次执行 index → valuation → margin → limit → basic → panel
    python3 src/update_tushare.py downstream  # 重建行业/市场/周期/回调/网页数据

说明：
  - 面板是「前复权、锚定最新 adj_factor」的口径。新增除权除息后，
    历史价格必须整体重算，不能直接把未复权收盘价接到尾部。
  - 分片写入 /Users/kunrongcai/Desktop/A股数据/_fetch_csi_full/。
  - 重建前自动备份 panel_csi_all_full.parquet。
"""
import os
import sys
import time
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

DATA_DIR = os.environ.get("ASHARE_DATA_DIR", "/Users/kunrongcai/Desktop/A股数据")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 允许用环境变量指向测试目录，便于小样本验证重建逻辑
WORK = os.environ.get("ASHARE_SHARD_DIR", os.path.join(DATA_DIR, "_fetch_csi_full"))
PANEL = os.environ.get("ASHARE_PANEL", os.path.join(DATA_DIR, "panel_csi_all_full.parquet"))
CONS = os.path.join(DATA_DIR, "cons_csi_all.csv")
STOCK_BASIC = os.path.join(DATA_DIR, "stock_basic_all.csv")
APP_DATA = os.path.join(DATA_DIR, "应用数据")
INDEX_CSV = os.path.join(APP_DATA, "index_daily.csv")
MARGIN_CSV = os.path.join(APP_DATA, "cache", "margin_full.csv")
LIMIT_CSV = os.path.join(APP_DATA, "cache", "limit_daily.csv")
VALUATION_CSV = os.path.join(APP_DATA, "cache", "index_dailybasic.csv")

API_URL = os.environ.get("TUSHARE_API_URL", "http://data.000666.site/dataapi")
SLEEP = 0.35
RETRY = 5

DAILY_COLS = ["ts_code", "trade_date", "open", "high", "low", "close",
              "pre_close", "change", "pct_chg", "vol", "amount",
              "ah_vol", "ah_amount"]
BASIC_COLS = ["ts_code", "trade_date", "close", "turnover_rate",
              "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb", "ps",
              "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share",
              "free_share", "total_mv", "circ_mv", "limit_status"]
PANEL_COLS = ["date", "ticker", "open", "high", "low", "close", "close_raw",
              "volume", "amount", "vwap", "total_mv", "turnover_rate", "pe",
              "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share",
              "float_share", "free_share"]

INDEX_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "创业板指": "399006.SZ",
    "科创50": "000688.SH",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
    "中证2000": "932000.CSI",
    "沪深300": "000300.SH",
}


def get_pro():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("缺少环境变量 TUSHARE_TOKEN。请先 export TUSHARE_TOKEN=... 再运行。")
        sys.exit(2)
    import tushare as ts
    pro = ts.pro_api(token)
    pro._DataApi__http_url = API_URL
    return pro


def call(pro, name, **params):
    """带重试的单次调用；空结果返回 None。"""
    fn = getattr(pro, name)
    last = None
    for attempt in range(RETRY):
        try:
            df = fn(**params)
            time.sleep(SLEEP)
            if df is None or len(df) == 0:
                return None
            return df
        except Exception as e:  # 网络/限频/token 错误
            last = e
            wait = 3.0 * (attempt + 1)
            print("   %s 失败(%s)，%.0fs 后重试" % (name, str(e)[:80], wait), flush=True)
            time.sleep(wait)
    print("   %s 多次失败: %s" % (name, str(last)[:120]), flush=True)
    return None


def load_universe():
    cons = pd.read_csv(CONS, encoding="utf-8-sig")
    exch = cons["交易所"].map({"深圳证券交易所": "SZ", "上海证券交易所": "SH",
                               "北京证券交易所": "BJ"})
    codes = cons["成分券代码"].astype(int).astype(str).str.zfill(6)
    return set((codes + "." + exch).tolist())


def _numeric(df):
    for c in df.columns:
        if c not in ("ts_code", "trade_date"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def missing_dates(pro, last):
    """面板最后日期之后的交易日（含今天，若当日数据已发布）。"""
    start = (last + pd.Timedelta(days=1)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    if start > end:
        return []
    cal = call(pro, "trade_cal", exchange="SSE", start_date=start,
               end_date=end, is_open="1")
    if cal is None:
        return []
    return sorted(cal["cal_date"].astype(str).tolist())


def fetch_panel(pro):
    if not os.path.exists(PANEL):
        print("找不到面板:", PANEL)
        sys.exit(1)
    last = pd.read_parquet(PANEL, columns=["date"])["date"].max()
    dates = missing_dates(pro, last)
    print("面板最后日期 %s，待补 %d 个交易日" % (last.date(), len(dates)), flush=True)
    if not dates:
        return []

    universe = load_universe()
    print("股票池 %d 只" % len(universe), flush=True)
    written = []
    for i, dt in enumerate(dates, 1):
        counts = {}
        for ep, cols in (("daily", DAILY_COLS), ("daily_basic", BASIC_COLS),
                         ("adj_factor", ["ts_code", "trade_date", "adj_factor"])):
            fp = os.path.join(WORK, "%s_%s.parquet" % (ep, dt))
            if os.path.exists(fp):
                counts[ep] = "cached"
                continue
            df = call(pro, ep, trade_date=dt)
            if df is None:
                counts[ep] = 0
                continue
            df = df.drop_duplicates(subset=["ts_code"]).copy()
            df = df[df["ts_code"].isin(universe)]
            df = _numeric(df)
            for c in cols:
                if c not in df.columns:
                    df[c] = None
            df = df[cols].sort_values("ts_code", ignore_index=True)
            df.to_parquet(fp, index=False)
            counts[ep] = len(df)
        ok = all(isinstance(v, int) and v >= 4000 for v in counts.values())
        print("  [%d/%d] %s  daily=%s basic=%s adj=%s%s"
              % (i, len(dates), dt, counts.get("daily"), counts.get("daily_basic"),
                 counts.get("adj_factor"), "" if ok else "  <-- 偏少/缺失"),
              flush=True)
        if isinstance(counts.get("daily"), int) and counts["daily"] > 0:
            written.append(dt)
    return written


def build_panel():
    files = sorted(os.listdir(WORK))
    dates = sorted({f.rsplit("_", 1)[-1].split(".")[0]
                    for f in files if f.endswith(".parquet")})
    print("合并 %d 个交易日分片 ..." % len(dates), flush=True)

    dly_parts, bas_parts, adj_parts = [], [], []
    for i, dt in enumerate(dates):
        p = os.path.join(WORK, "daily_%s.parquet" % dt)
        if os.path.exists(p):
            d = pd.read_parquet(p)
            keep = [c for c in ["ts_code", "trade_date", "open", "high", "low",
                                "close", "vol", "amount"] if c in d.columns]
            dly_parts.append(d[keep])
        p = os.path.join(WORK, "daily_basic_%s.parquet" % dt)
        if os.path.exists(p):
            d = pd.read_parquet(p)
            keep = [c for c in BASIC_COLS if c in d.columns]
            bas_parts.append(d[keep])
        p = os.path.join(WORK, "adj_factor_%s.parquet" % dt)
        if os.path.exists(p):
            adj_parts.append(pd.read_parquet(p))
        if (i + 1) % 500 == 0:
            print("  读入 %d/%d" % (i + 1, len(dates)), flush=True)

    dly = pd.concat(dly_parts, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    bas = pd.concat(bas_parts, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    adj = pd.concat(adj_parts, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    print("daily %d 行 | daily_basic %d 行 | adj_factor %d 行"
          % (len(dly), len(bas), len(adj)), flush=True)

    df = dly.merge(bas.drop(columns=["close"], errors="ignore"),
                   on=["ts_code", "trade_date"], how="left")
    df = df.merge(adj, on=["ts_code", "trade_date"], how="left")

    adj_sorted = adj.sort_values("trade_date")
    last_adj = adj_sorted.groupby("ts_code")["adj_factor"].last()
    df["adj_last"] = df["ts_code"].map(last_adj)
    ratio = df["adj_factor"] / df["adj_last"]

    vol = pd.to_numeric(df["vol"], errors="coerce")          # 手
    amt = pd.to_numeric(df["amount"], errors="coerce")       # 千元
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    out["ticker"] = df["ts_code"]
    out["close_raw"] = pd.to_numeric(df["close"], errors="coerce")
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(df[c], errors="coerce") * ratio
    out["volume"] = vol * 100.0
    out["amount"] = amt * 1000.0
    out["vwap"] = np.where(vol > 0, amt * 10.0 / vol, np.nan) * ratio
    for c in ["total_mv", "turnover_rate", "pe", "pb", "ps", "ps_ttm",
              "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share"]:
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    out = out.sort_values(["ticker", "date"], ignore_index=True)[PANEL_COLS]

    stamp = datetime.now().strftime("%Y%m%d%H%M")
    if os.path.exists(PANEL):
        bak = PANEL + ".bak_" + stamp
        shutil.copy2(PANEL, bak)
        print("备份面板 ->", os.path.basename(bak), flush=True)
    tmp = PANEL + ".tmp"
    out.to_parquet(tmp, index=False)
    os.replace(tmp, PANEL)
    print("输出 %s: %d 行, %d 只, %s ~ %s"
          % (PANEL, len(out), out["ticker"].nunique(),
             out["date"].min().date(), out["date"].max().date()), flush=True)
    return out


def update_index(pro):
    idx = pd.read_csv(INDEX_CSV, dtype={"date": str})
    last = idx["date"].max()
    end = datetime.now().strftime("%Y%m%d")
    start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime("%Y%m%d")
    if start > end:
        print("指数已是最新:", last)
        return
    print("指数 %s -> 今天，补 %s 起" % (last, start), flush=True)
    frames = []
    for name, code in INDEX_CODES.items():
        df = call(pro, "index_daily", ts_code=code, start_date=start, end_date=end)
        if df is None:
            print("  %s %s: 无新数据" % (name, code), flush=True)
            continue
        df = df[["trade_date", "close"]].copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.rename(columns={"trade_date": "date", "close": name})
        frames.append(df)
        print("  %s %s: %d 行 %s ~ %s"
              % (name, code, len(df), df["date"].min(), df["date"].max()), flush=True)
    if not frames:
        return
    new = frames[0]
    for f in frames[1:]:
        new = new.merge(f, on="date", how="outer")
    new = new[new["date"] > last].sort_values("date")
    out = pd.concat([idx, new], ignore_index=True).sort_values("date")
    out = out.drop_duplicates("date", keep="last")
    bak = INDEX_CSV + ".bak_" + datetime.now().strftime("%Y%m%d")
    shutil.copy2(INDEX_CSV, bak)
    out.to_csv(INDEX_CSV, index=False)
    print("指数 CSV 更新到 %s（备份 %s）" % (out["date"].max(), os.path.basename(bak)), flush=True)


INDEX_BASIC_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "沪深300": "000300.SH",
    "创业板指": "399006.SZ",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
    "科创50": "000688.SH",
}
VALUATION_COLS = ["name", "ts_code", "trade_date", "pe", "pe_ttm", "pb",
                  "turnover_rate", "turnover_rate_f", "total_mv", "float_mv",
                  "source"]


def update_valuation(pro):
    """指数估值/换手（index_dailybasic），按年分页拉全历史后合并。

    网关单次最多返回 3000 行，不分年切分会把 2014 年以前的历史截掉。
    写入 source 列，便于前端标注哪一段是 Tushare 官方值、哪一段是推算值。
    """
    old = pd.DataFrame(columns=VALUATION_COLS)
    if os.path.exists(VALUATION_CSV):
        old = pd.read_csv(VALUATION_CSV, dtype={"trade_date": str})
        old["trade_date"] = pd.to_datetime(old["trade_date"]).dt.strftime("%Y-%m-%d")
        if "source" not in old.columns:
            old["source"] = "tushare"
    end = datetime.now().strftime("%Y%m%d")
    frames = []
    for name, code in INDEX_BASIC_CODES.items():
        parts = []
        for year in range(2000, int(end[:4]) + 1):
            stop = min("%d1231" % year, end)
            df = call(pro, "index_dailybasic", ts_code=code,
                      start_date="%d0101" % year, end_date=stop)
            if df is not None:
                parts.append(df)
        if not parts:
            print("  %s %s: 无数据" % (name, code), flush=True)
            continue
        df = pd.concat(parts, ignore_index=True).drop_duplicates("trade_date")
        df["name"] = name
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["source"] = "tushare"
        for c in VALUATION_COLS:
            if c not in df.columns:
                df[c] = None
        frames.append(df[VALUATION_COLS])
        print("  %s %s: %d 行 %s ~ %s"
              % (name, code, len(df), df["trade_date"].min(), df["trade_date"].max()),
              flush=True)
    if not frames:
        print("指数估值无数据，跳过")
        return
    out = pd.concat([old] + frames, ignore_index=True)
    out = out.drop_duplicates(["ts_code", "trade_date"], keep="last")
    out = out.sort_values(["ts_code", "trade_date"], ignore_index=True)
    bak = VALUATION_CSV + ".bak_" + datetime.now().strftime("%Y%m%d")
    shutil.copy2(VALUATION_CSV, bak)
    out.to_csv(VALUATION_CSV, index=False)
    print("指数估值写到 %s 条（%d 个指数，最新 %s，备份 %s）"
          % (len(out), out["ts_code"].nunique(), out["trade_date"].max(),
             os.path.basename(bak)), flush=True)


def update_margin(pro):
    """两融余额（交易所口径），只追加沪深北记录完整的交易日。"""
    from margin_quality import filter_complete_margin
    if not os.path.exists(MARGIN_CSV):
        print("找不到", MARGIN_CSV, "，跳过两融")
        return
    old = pd.read_csv(MARGIN_CSV, dtype={"trade_date": str})
    old["trade_date"] = pd.to_datetime(
        old["trade_date"].astype(str).str.replace("-", "", regex=False).str.slice(0, 8),
        format="%Y%m%d", errors="coerce").dt.strftime("%Y%m%d")
    complete_old = filter_complete_margin(old)
    if complete_old.empty:
        print("两融缓存没有完整交易日，跳过更新")
        return
    # 以最后完整日期为增量起点，同时清掉此前误追加的残缺尾部。
    last = complete_old["trade_date"].max()
    old = old[old["trade_date"] <= last].copy()
    start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    if start > end:
        print("两融已是最新完整日期:", last)
        return
    df = call(pro, "margin", start_date=start, end_date=end)
    if df is None:
        print("两融无新数据")
        return
    cols = ["trade_date", "exchange_id", "rzye", "rzmre", "rzche", "rqye",
            "rqmcl", "rzrqye", "rqyl"]
    df = df[cols].copy()
    df["trade_date"] = pd.to_datetime(
        df["trade_date"].astype(str).str.replace("-", "", regex=False).str.slice(0, 8),
        format="%Y%m%d", errors="coerce").dt.strftime("%Y%m%d")
    df = df[df["trade_date"] > last]
    if df.empty:
        print("两融无新数据")
        return
    out = pd.concat([old, df], ignore_index=True)
    out = out.drop_duplicates(["trade_date", "exchange_id"], keep="last")
    out = filter_complete_margin(out)
    out = out.sort_values(["trade_date", "exchange_id"], ignore_index=True)
    bak = MARGIN_CSV + ".bak_" + datetime.now().strftime("%Y%m%d")
    shutil.copy2(MARGIN_CSV, bak)
    out.to_csv(MARGIN_CSV, index=False)
    print("两融更新到最新完整日期 %s（%d 行，备份 %s）"
          % (out["trade_date"].max(), len(out), os.path.basename(bak)), flush=True)


def update_limit(pro):
    """涨跌停家数（limit_list_d），追加到 cache/limit_daily.csv。"""
    if not os.path.exists(LIMIT_CSV):
        print("找不到", LIMIT_CSV, "，跳过涨跌停")
        return
    old = pd.read_csv(LIMIT_CSV, dtype={"trade_date": str})
    last = old["trade_date"].max()
    dates = missing_dates(pro, pd.Timestamp(last))
    if not dates:
        print("涨跌停已是最新:", last)
        return
    rows = []
    for dt in dates:
        df = call(pro, "limit_list_d", trade_date=dt)
        if df is None or "limit" not in df.columns:
            continue
        lim = df["limit"].astype(str).str.upper()
        # dt 来自 missing_dates，是 YYYYMMDD；文件里既有 YYYY-MM-DD 也有 YYYYMMDD，
        # 不统一会让下游 pd.to_datetime 变成 object，必须在这里统一成 YYYY-MM-DD。
        d = pd.to_datetime(str(dt).replace("-", ""), format="%Y%m%d")
        rows.append({"trade_date": d.strftime("%Y-%m-%d"),
                     "limit_up_n": int((lim == "U").sum()),
                     "limit_down_n": int((lim == "D").sum())})
        print("  %s: 涨停 %d / 跌停 %d"
              % (dt, rows[-1]["limit_up_n"], rows[-1]["limit_down_n"]), flush=True)
    if not rows:
        print("涨跌停无新数据")
        return
    out = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    # 兜底：把历史上混进来的 YYYYMMDD 也统一成 YYYY-MM-DD
    out["trade_date"] = pd.to_datetime(
        out["trade_date"].astype(str).str.replace("-", ""),
        format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["trade_date"])
    out = out.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    bak = LIMIT_CSV + ".bak_" + datetime.now().strftime("%Y%m%d")
    shutil.copy2(LIMIT_CSV, bak)
    out.to_csv(LIMIT_CSV, index=False)
    print("涨跌停更新到 %s（备份 %s）"
          % (out["trade_date"].max(), os.path.basename(bak)), flush=True)


def update_basic(pro):
    old = pd.read_csv(STOCK_BASIC, dtype=str)
    frames = []
    for status in ("L", "D", "P"):
        df = call(pro, "stock_basic", list_status=status,
                  fields="ts_code,name,industry,list_date,market")
        if df is not None:
            df["list_status"] = status
            frames.append(df)
            print("  stock_basic %s: %d 行" % (status, len(df)), flush=True)
    if not frames:
        print("stock_basic 无数据，跳过")
        return
    new = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code", keep="last")
    new = new[["ts_code", "name", "industry", "list_date", "market"]]

    old = old.set_index("ts_code")
    new = new.set_index("ts_code")
    # 已有记录的行业为空时保留旧值（退市股常见）
    fill_ind = old["industry"].replace("", np.nan).dropna()
    new["industry"] = new["industry"].where(
        new["industry"].notna() & (new["industry"] != ""),
        new.index.map(fill_ind))
    merged = pd.concat([old, new])
    merged = merged[~merged.index.duplicated(keep="last")].reset_index()
    merged = merged.sort_values("ts_code", ignore_index=True)
    bak = STOCK_BASIC + ".bak_" + datetime.now().strftime("%Y%m%d")
    shutil.copy2(STOCK_BASIC, bak)
    merged.to_csv(STOCK_BASIC, index=False)
    print("stock_basic_all.csv: %d 行（原 %d，备份 %s）"
          % (len(merged), len(old), os.path.basename(bak)), flush=True)


def downstream():
    """面板更新后，按顺序重建行业/市场/周期/回调/网页数据。"""
    import subprocess
    py = sys.executable
    last = str(pd.read_parquet(PANEL, columns=["date"])["date"].max().date())
    steps = [("build_industry.py", {}), ("build_market_agg.py", {})]
    if os.environ.get("TUSHARE_TOKEN") or os.environ.get("DATAHUB_API_KEY"):
        steps.append(("build_cycle_stats.py", {"CYCLE_ASOF": last}))
    else:
        print("未设置 TUSHARE_TOKEN / DATAHUB_API_KEY，跳过 build_cycle_stats.py"
              "（行业/个股阶段统计停留在旧日期；其余照常）", flush=True)
    steps += [("build_cycle_analysis.py", {}),
              ("build_pullback_stats.py", {}),
              ("build_web_data.py", {})]
    for script, extra in steps:
        print("==> %s" % script, flush=True)
        env = dict(os.environ)
        env.update(extra)
        subprocess.run([py, os.path.join(PROJ, "src", script)],
                       check=True, env=env)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in ("panel", "index", "basic", "margin", "limit",
                    "valuation", "downstream", "all"):
        print(__doc__)
        sys.exit(1)
    if mode == "downstream":
        downstream()
        return
    pro = get_pro()
    if mode in ("index", "all"):
        update_index(pro)
    if mode in ("valuation", "all"):
        update_valuation(pro)
    if mode in ("margin", "all"):
        update_margin(pro)
    if mode in ("limit", "all"):
        update_limit(pro)
    if mode in ("basic", "all"):
        update_basic(pro)
    if mode in ("panel", "all"):
        written = fetch_panel(pro)
        if written or mode == "all":
            build_panel()
            print("\n下一步重建下游：python3 src/update_tushare.py downstream",
                  flush=True)


if __name__ == "__main__":
    main()
