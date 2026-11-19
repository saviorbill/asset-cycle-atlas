# -*- coding: utf-8 -*-
"""用 akshare（免费公开接口）增量更新本地数据。

用途：Tushare Pro 网关到期后的日常更新方案。历史数据由 update_tushare.py
在到期前补齐；本脚本只追加「本地最后日期之后」的交易日，写出的分片格式与
Tushare 完全一致，仍由 update_tushare.build_panel() 统一重建前复权面板。

用法：
    python3 src/update_akshare.py panel       # 个股日线 + 估值 -> 分片 -> 重建全A面板
    python3 src/update_akshare.py index       # 八大指数日线收盘价
    python3 src/update_akshare.py basic       # 股票名称（新增/改名）
    python3 src/update_akshare.py margin      # 两融余额
    python3 src/update_akshare.py limit       # 涨跌停家数
    python3 src/update_akshare.py valuation   # 指数估值尾部（按价格推算，可选）
    python3 src/update_akshare.py all         # index -> valuation -> margin -> limit -> basic -> panel
    python3 src/update_akshare.py downstream  # 重建行业/市场/周期/回调/网页数据

数据源映射：
    个股日线           东财 stock_zh_a_hist；不可达时整轮熔断切新浪 stock_zh_a_daily
    复权因子           新浪 stock_zh_a_daily（adjust="qfq-factor"）；不可用则用东财前复权反推
    股本/市值校正      东财 stock_zh_a_spot_em（每日快照，跟随增发/回购）
    个股估值           由最后一条 Tushare 的每股盈利/净资产随价格推算
    指数日线           东财 index_zh_a_hist
    两融               stock_margin_sse / stock_margin_szse（深市单位亿元）
    涨跌停             stock_zt_pool_em / stock_zt_pool_dtgc_em

口径说明：
  - 收盘后（15:30 之后）才认为当日数据可用；未收盘不追加，避免写进半日数据。
  - 前复权：新浪 qfq_factor 是「最新=1」的因子，用最后一条 Tushare adj_factor
    把它缩放到同一量纲（adj = adj_last / qfq_factor），再交给 build_panel 重建，
    这样除权除息后历史价格会自动整体重算，不会在接缝处跳空。
  - PE/PB/市值：按最后一次 Tushare 的每股盈利/净资产随价格推算。Tushare 的
    静态 PE 在两次年报之间只随市值变动，所以逐日推算与官方值一致（实测中位
    误差 0.00%）；PB 的净资产按季更新，季报后会略有偏差。年报季后建议用
    Tushare 或百度估值接口重新拉一次基本面系。
  - 指数估值没有日频公开接口，valuation 模式按「指数涨跌 × 最后官方估值」推算，
    并在 CSV 的 source 列标记为 ak-proj，网页会标注推算起点。不需要可跳过。

环境变量（可选）：
    AK_WORKERS       并发线程数，默认 8
    AK_LIMIT         只处理前 N 只股票（调试用）
    AK_HTTP_TIMEOUT  单次 HTTP 超时秒数，默认 20
    AK_MIN_ROWS      某日少于该只数视为未发布，默认 4000
"""
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd
from requests.adapters import HTTPAdapter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_tushare import (DATA_DIR, PROJ, WORK, PANEL, CONS, STOCK_BASIC,
                            INDEX_CSV, MARGIN_CSV, LIMIT_CSV, VALUATION_CSV,
                            DAILY_COLS, BASIC_COLS, INDEX_CODES,
                            load_universe, build_panel, downstream)

import akshare as ak

WORKERS = int(os.environ.get("AK_WORKERS", "8"))
LIMIT = int(os.environ.get("AK_LIMIT", "0") or 0)
MIN_ROWS = int(os.environ.get("AK_MIN_ROWS", "4000"))   # 少于该只数视为未发布
CLOSE_HHMM = 1530        # 15:30 后才能确认当日已收盘
HTTP_TIMEOUT = int(os.environ.get("AK_HTTP_TIMEOUT", "20"))   # 秒

# akshare 内部大量直接 requests.get(...)，不传 timeout；遇到半死不活的连接
# （SYN_SENT）会永久挂住，整个日常更新就卡死。统一补一个默认超时。
_send = HTTPAdapter.send


def _send_with_timeout(self, request, **kwargs):
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = HTTP_TIMEOUT
    return _send(self, request, **kwargs)


HTTPAdapter.send = _send_with_timeout

# 新浪复权因子接口偶发不可达；连续失败到阈值后本次运行整体关掉，
# 直接改用东财前复权反推因子，避免每只股票都白等超时。
_sina_fail = {"n": 0}
_sina_lock = threading.Lock()
SINA_MAX_FAIL = int(os.environ.get("AK_SINA_MAX_FAIL", "12"))


def _sina_enabled():
    return _sina_fail["n"] < SINA_MAX_FAIL


def _sina_note_fail(msg=""):
    with _sina_lock:
        _sina_fail["n"] += 1
        n = _sina_fail["n"]
    if n == SINA_MAX_FAIL:
        print("  新浪复权因子连续失败 %d 次（%s），本次改用东财前复权反推因子"
              % (n, msg[:50]), flush=True)


def _sina_note_ok():
    with _sina_lock:
        _sina_fail["n"] = 0


# 统计本次运行各来源命中数，跑完打一行汇总，方便判断哪家挂了。
_src = {"em": 0, "sina": 0}
_src_lock = threading.Lock()

# 东财也会限流/整站不可达；同样用熔断，避免每只股票都等满重试。
_em_fail = {"n": 0}
_em_lock = threading.Lock()
EM_MAX_FAIL = int(os.environ.get("AK_EM_MAX_FAIL", "16"))


def _em_enabled():
    return _em_fail["n"] < EM_MAX_FAIL


def _em_note_fail(msg=""):
    with _em_lock:
        _em_fail["n"] += 1
        n = _em_fail["n"]
    if n == EM_MAX_FAIL:
        print("  东财日线连续失败 %d 次（%s），本次改用新浪行情"
              % (n, msg[:50]), flush=True)


def _em_note_ok():
    with _em_lock:
        _em_fail["n"] = 0


def _probe_sources(start, end):
    """开跑前各戳一次，直接熔断挂掉的那家，省掉几千次无效重试。"""
    t = time.time()
    d = _em_daily("600519", start, end)
    if not len(d):
        with _em_lock:
            _em_fail["n"] = EM_MAX_FAIL
        print("  东财不可达，本次行情全部改用新浪（%.0fs）"
              % (time.time() - t), flush=True)
    t = time.time()
    f = _sina_factor("sh600519", "19900101", end)
    if not len(f):
        with _sina_lock:
            _sina_fail["n"] = SINA_MAX_FAIL
        print("  新浪复权因子不可用，改用东财前复权反推（%.0fs）"
              % (time.time() - t), flush=True)


# ------------------------------------------------------------------
# 交易日
# ------------------------------------------------------------------
def trade_calendar():
    d = ak.tool_trade_date_hist_sina()
    s = pd.to_datetime(d["trade_date"]).dt.normalize()
    return s.drop_duplicates().sort_values().reset_index(drop=True)


def missing_trade_dates(last):
    """本地最后日期之后的已收盘交易日（YYYYMMDD 列表）。"""
    cal = trade_calendar()
    now = datetime.now()
    today = pd.Timestamp(now.date())
    cutoff = today
    if now.hour * 100 + now.minute < CLOSE_HHMM:
        cutoff = today - pd.Timedelta(days=1)
    m = cal[(cal > pd.Timestamp(last)) & (cal <= cutoff)]
    return [x.strftime("%Y%m%d") for x in m]


def published_dates(start, end):
    """以沪深300指数日线为准，判断哪些日期已发布（返回 None 表示查询失败）。"""
    try:
        d = ak.index_zh_a_hist(symbol="000300", period="daily",
                               start_date=start, end_date=end)
        return {pd.Timestamp(x).strftime("%Y%m%d") for x in d["日期"]}
    except Exception:
        return None


# ------------------------------------------------------------------
# 个股：新浪日线 + 复权因子
# ------------------------------------------------------------------
def _sina_symbol(code):
    num, ex = code.split(".")
    return {"SH": "sh", "SZ": "sz", "BJ": "bj"}[ex] + num


def _em_daily(code6, start, end):
    """东财日线（不复权）。比新浪更新更快：新浪个别股票会晚一天才出 11-18。

    返回 date/open/high/low/close/vol_sh(股)/amount(元)/turn(百分数)。
    """
    if not _em_enabled():
        return pd.DataFrame()
    for i in range(3):
        try:
            d = ak.stock_zh_a_hist(symbol=code6, period="daily", start_date=start,
                                   end_date=end, adjust="")
            if d is None or not len(d):
                return pd.DataFrame()
            d = d.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "vol_hand",
                "成交额": "amount", "换手率": "turn",
            })
            d["vol_sh"] = pd.to_numeric(d["vol_hand"], errors="coerce") * 100.0
            _em_note_ok()
            return d[["date", "open", "close", "high", "low", "vol_sh",
                      "amount", "turn"]]
        except Exception as e:
            _em_note_fail(str(e))
            time.sleep(1.0 * (i + 1))
    return pd.DataFrame()


def _sina_daily(sym, start, end):
    """新浪日线（不复权）。东财被限流/不可达时的备选，字段更全。

    volume 单位股，amount 元，turnover 是小数（0.0024 = 0.24%），
    outstanding_share 是流通股本（股）。
    """
    for i in range(2):
        try:
            d = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end,
                                    adjust="")
            if d is None or not len(d):
                return pd.DataFrame()
            d = d.copy()
            d["vol_sh"] = pd.to_numeric(d["volume"], errors="coerce")
            d["turn"] = pd.to_numeric(d["turnover"], errors="coerce") * 100.0
            d["fshare"] = pd.to_numeric(d["outstanding_share"],
                                        errors="coerce") / 1e4     # 万股
            return d[["date", "open", "close", "high", "low", "vol_sh",
                      "amount", "turn", "fshare"]]
        except Exception:
            time.sleep(1.0 * (i + 1))
    return pd.DataFrame()


def _raw_daily(code, sym, start, end):
    """先东财后新浪；返回 (df, 来源名)。"""
    d = _em_daily(code[:6], start, end)
    if len(d):
        return d, "em"
    d = _sina_daily(sym, start, end)
    if len(d):
        return d, "sina"
    return pd.DataFrame(), "-"


def _sina_factor(sym, start, end):
    if not _sina_enabled():
        return pd.DataFrame(columns=["date", "qfq_factor"])
    for i in range(2):
        try:
            d = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end,
                                    adjust="qfq-factor")
            if d is not None and len(d):
                d = d.copy()
                d["date"] = pd.to_datetime(d["date"])
                _sina_note_ok()
                return (d.drop_duplicates("date").sort_values("date")
                        .reset_index(drop=True))
            return pd.DataFrame(columns=["date", "qfq_factor"])   # 停牌等，正常
        except Exception as e:
            _sina_note_fail(str(e))
            time.sleep(0.5 * (i + 1))
    return pd.DataFrame(columns=["date", "qfq_factor"])


def _em_qfq(sym6, start, end):
    try:
        d = ak.stock_zh_a_hist(symbol=sym6, period="daily", start_date=start,
                               end_date=end, adjust="qfq")
        if d is not None and len(d):
            d = d.rename(columns={"日期": "date", "收盘": "qclose"})
            d["date"] = pd.to_datetime(d["date"])
            return d[["date", "qclose"]]
    except Exception:
        pass
    return None


def _float_from_turnover(vol_sh, turn):
    """换手率(%)反推流通股本（股）。"""
    if np.isfinite(vol_sh) and np.isfinite(turn) and turn > 0:
        return vol_sh / (turn / 100.0)
    return np.nan


def _num(v):
    try:
        f = float(v)
        return f if np.isfinite(f) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _load_prev_state():
    """面板最后一日：每股复权基准、股本、盈利/净资产/营收/分红。"""
    cols = ["ticker", "date", "close_raw", "total_mv", "pe", "pb", "ps",
            "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share",
            "free_share"]
    p = pd.read_parquet(PANEL, columns=cols)
    p = p.sort_values(["ticker", "date"]).groupby("ticker", sort=False).tail(1)
    carry, last_close = {}, {}
    for r in p.itertuples():
        mv, close = _num(r.total_mv), _num(r.close_raw)
        pe, pb = _num(r.pe), _num(r.pb)
        ps = _num(r.ps_ttm) if np.isfinite(_num(r.ps_ttm)) else _num(r.ps)
        dv = _num(r.dv_ratio)
        ts = _num(r.total_share)
        if not np.isfinite(ts) and close > 0:
            ts = mv / close
        fl = _num(r.float_share)
        fs = _num(r.free_share)
        carry[r.ticker] = {
            "total_share": ts,
            "float_share": fl,
            "free_ratio": fs / fl
            if np.isfinite(fs) and np.isfinite(fl) and fl > 0 else 1.0,
            "earnings": mv / pe if pe and pe > 0 else np.nan,
            "book": mv / pb if pb and pb > 0 else np.nan,
            "revenue": mv / ps if ps and ps > 0 else np.nan,
            "dividend": mv * dv / 100.0 if dv and dv > 0 else np.nan,
        }
        last_close[r.ticker] = close
    return carry, last_close


def _load_adj_scale():
    """每只股票最后一条 Tushare adj_factor，用于把新浪因子缩放到同一量纲。"""
    files = sorted(f for f in os.listdir(WORK)
                   if f.startswith("adj_factor_") and f.endswith(".parquet"))
    scale = {}
    for f in files[-2:]:
        d = pd.read_parquet(os.path.join(WORK, f))
        for code, v in zip(d["ts_code"], d["adj_factor"]):
            v = _num(v)
            if np.isfinite(v):
                scale[code] = v
    return scale


def _fetch_stock(code, start, end, date_set, carry, scale, last_close):
    """返回 (daily_rows, basic_rows, adj_rows) 三个 list[dict]。"""
    sym = _sina_symbol(code)
    raw, src = _raw_daily(code, sym, start, end)
    if raw.empty:
        return [], [], []
    with _src_lock:
        _src[src] += 1
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    raw = raw.drop_duplicates("date").sort_values("date").reset_index(drop=True)

    fac = _sina_factor(sym, start, end)
    if len(fac):
        m = pd.merge_asof(raw[["date"]], fac, on="date",
                          direction="backward")
        F = m["qfq_factor"].astype(float).fillna(1.0).to_numpy()
    else:
        q = _em_qfq(code[:6], start, end)
        if q is not None and len(q):
            raw = raw.merge(q, on="date", how="left")
            F = np.where(raw["qclose"] > 0,
                         raw["close"] / raw["qclose"], 1.0)
        else:
            F = np.ones(len(raw))
    F = np.where(F > 0, F, 1.0)

    c = carry.get(code, {})
    adj_scale = scale.get(code, 1.0)
    prev = last_close.get(code, np.nan)
    rows_d, rows_b, rows_a = [], [], []
    for i, r in raw.iterrows():
        dt = r["date"].strftime("%Y%m%d")
        close = _num(r["close"])
        o, h, l = _num(r["open"]), _num(r["high"]), _num(r["low"])
        vol_sh = _num(r["vol_sh"])
        amt_y = _num(r["amount"])
        turn = _num(r["turn"])
        if dt in date_set and close > 0:
            pre = prev
            chg = close - pre if np.isfinite(pre) and pre > 0 else np.nan
            pct = chg / pre * 100 if np.isfinite(chg) and pre > 0 else np.nan
            rows_d.append({
                "ts_code": code, "trade_date": dt,
                "open": o, "high": h, "low": l, "close": close,
                "pre_close": pre, "change": chg, "pct_chg": pct,
                "vol": vol_sh / 100.0, "amount": amt_y / 1000.0,
                "ah_vol": np.nan, "ah_amount": np.nan,
            })
            # 新浪直接给流通股本；东财只能由换手率反推
            share = _num(r.get("fshare")) if "fshare" in r.index else np.nan
            if not (np.isfinite(share) and share > 0):
                share = _float_from_turnover(vol_sh, turn) / 1e4     # 万股
            ts = _num(c.get("total_share"))
            if not (np.isfinite(ts) and ts > 0):
                ts = share
            fl = share if np.isfinite(share) else _num(c.get("float_share"))
            mv = close * ts if np.isfinite(ts) else np.nan
            earnings, book = c.get("earnings"), c.get("book")
            earnings_ttm = c.get("earnings_ttm")
            if not (earnings_ttm and earnings_ttm > 0):
                earnings_ttm = earnings
            revenue, dividend = c.get("revenue"), c.get("dividend")
            free_ratio = c.get("free_ratio", 1.0)
            rows_b.append({
                "ts_code": code, "trade_date": dt, "close": close,
                "turnover_rate": turn,
                "turnover_rate_f": turn,
                "volume_ratio": np.nan,
                "pe": mv / earnings if earnings and earnings > 0 else np.nan,
                "pe_ttm": mv / earnings_ttm
                if earnings_ttm and earnings_ttm > 0 else np.nan,
                "pb": mv / book if book and book > 0 else np.nan,
                "ps": mv / revenue if revenue and revenue > 0 else np.nan,
                "ps_ttm": mv / revenue if revenue and revenue > 0 else np.nan,
                "dv_ratio": dividend / mv * 100
                if dividend and dividend > 0 and mv > 0 else np.nan,
                "dv_ttm": dividend / mv * 100
                if dividend and dividend > 0 and mv > 0 else np.nan,
                "total_share": ts, "float_share": fl,
                "free_share": fl * free_ratio if np.isfinite(fl) else np.nan,
                "total_mv": mv,
                "circ_mv": close * fl if np.isfinite(fl) else np.nan,
                "limit_status": np.nan,
            })
            rows_a.append({"ts_code": code, "trade_date": dt,
                           "adj_factor": adj_scale / float(F[i])})
        prev = close
    return rows_d, rows_b, rows_a




def _spot_caps(rows_b, last_dt):
    """用东财快照校正最后一日的总市值/流通市值与股本。

    只动「市值锚」，不动 PE/PB 口径：盈利/净资产沿用上一日推算值，
    市值换成快照值后再按比例换算 PE/PB。这样增发、回购等股本变化
    能逐日跟上，而估值口径与历史 Tushare 序列保持一致。
    """
    try:
        s = ak.stock_zh_a_spot_em()
    except Exception as e:
        print("  东财快照失败，跳过市值校正：%s" % str(e)[:60], flush=True)
        return 0
    s = s.rename(columns={"代码": "code", "总市值": "mv", "流通市值": "cmv"})
    s["code"] = s["code"].astype(str).str.zfill(6)
    s = s.drop_duplicates("code").set_index("code")
    n = 0
    for row in rows_b:
        if row["trade_date"] != last_dt:
            continue
        hit = s.loc[s.index == row["ts_code"][:6]]
        if hit.empty:
            continue
        mv = _num(hit.iloc[0]["mv"]) / 1e4          # 万元
        cmv = _num(hit.iloc[0]["cmv"]) / 1e4
        close = row["close"]
        old_mv, old_pe, old_pb = row["total_mv"], row["pe"], row["pb"]
        if not (np.isfinite(mv) and mv > 0 and close > 0):
            continue
        if np.isfinite(old_mv) and old_mv > 0:
            if np.isfinite(old_pe) and old_pe > 0:
                row["pe"] = mv / (old_mv / old_pe)
            if np.isfinite(old_pb) and old_pb > 0:
                row["pb"] = mv / (old_mv / old_pb)
        row["total_mv"] = mv
        row["total_share"] = mv / close
        if np.isfinite(cmv) and cmv > 0:
            ratio = (row["free_share"] / row["float_share"]
                     if row["float_share"] and row["float_share"] > 0 else 1.0)
            row["circ_mv"] = cmv
            row["float_share"] = cmv / close
            row["free_share"] = row["float_share"] * ratio
        n += 1
    return n


def _write_shards(rows_d, rows_b, rows_a):
    by_day_d, by_day_b, by_day_a = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in rows_d:
        by_day_d[r["trade_date"]].append(r)
    for r in rows_b:
        by_day_b[r["trade_date"]].append(r)
    for r in rows_a:
        by_day_a[r["trade_date"]].append(r)
    written = []
    for dt in sorted(by_day_d):
        if len(by_day_d[dt]) < MIN_ROWS:
            print("  %s 仅 %d 只，疑似未发布，跳过"
                  % (dt, len(by_day_d[dt])), flush=True)
            continue
        d = pd.DataFrame(by_day_d[dt]).reindex(columns=DAILY_COLS)
        d.to_parquet(os.path.join(WORK, "daily_%s.parquet" % dt), index=False)
        b = pd.DataFrame(by_day_b[dt]).reindex(columns=BASIC_COLS)
        b.to_parquet(os.path.join(WORK, "daily_basic_%s.parquet" % dt), index=False)
        a = pd.DataFrame(by_day_a[dt]).reindex(
            columns=["ts_code", "trade_date", "adj_factor"])
        a.to_parquet(os.path.join(WORK, "adj_factor_%s.parquet" % dt), index=False)
        written.append(dt)
        print("  %s 写入分片：%d 只" % (dt, len(d)), flush=True)
    return written


def update_panel():
    last = pd.read_parquet(PANEL, columns=["date"])["date"].max()
    dates = missing_trade_dates(last)
    if not dates:
        print("面板已是最新：%s" % last.date())
        return []
    print("面板最后 %s，待补 %d 个交易日：%s ~ %s"
          % (last.date(), len(dates), dates[0], dates[-1]), flush=True)
    pub = published_dates(dates[0], dates[-1])
    if pub is not None:
        dates = [d for d in dates if d in pub]
        print("已发布日期 %d 个" % len(dates), flush=True)
    if not dates:
        print("当日数据尚未发布")
        return []
    date_set = set(dates)

    universe = sorted(load_universe())
    if LIMIT:
        universe = universe[:LIMIT]
    print("股票池 %d 只" % len(universe), flush=True)
    carry, last_close = _load_prev_state()
    scale = _load_adj_scale()

    rows_d, rows_b, rows_a = [], [], []
    start, end = dates[0], dates[-1]
    _probe_sources(start, end)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_fetch_stock, code, start, end, date_set,
                          carry, scale, last_close): code
                for code in universe}
        for i, f in enumerate(as_completed(futs), 1):
            code = futs[f]
            try:
                d, b, a = f.result()
                rows_d += d
                rows_b += b
                rows_a += a
            except Exception as e:
                print("  %s 失败：%s" % (code, str(e)[:60]), flush=True)
            if i % 500 == 0:
                print("  进度 %d/%d（%.0fs，成功行 %d）"
                      % (i, len(universe), time.time() - t0, len(rows_d)),
                      flush=True)
    print("抓取完成：%d 行，用时 %.0fs（东财 %d 只 / 新浪 %d 只）"
          % (len(rows_d), time.time() - t0, _src["em"], _src["sina"]), flush=True)

    if rows_b:
        n = _spot_caps(rows_b, dates[-1])
        print("  东财快照校正股本/市值 %d 只（%s）" % (n, dates[-1]), flush=True)
    written = _write_shards(rows_d, rows_b, rows_a)
    if written:
        build_panel()
        print("\n下一步重建下游：python3 src/update_akshare.py downstream", flush=True)
    return written


# ------------------------------------------------------------------
# 指数
# ------------------------------------------------------------------
def update_index():
    idx = pd.read_csv(INDEX_CSV, dtype={"date": str})
    last = idx["date"].max()
    dates = missing_trade_dates(last)
    if not dates:
        print("指数已是最新：%s" % last)
        return
    start, end = dates[0], dates[-1]
    print("指数 %s -> %s" % (last, end), flush=True)
    frames = []
    for name, code in INDEX_CODES.items():
        try:
            d = ak.index_zh_a_hist(symbol=code[:6], period="daily",
                                   start_date=start, end_date=end)
        except Exception as e:
            print("  %s %s 失败：%s" % (name, code, str(e)[:60]), flush=True)
            continue
        if d is None or not len(d):
            continue
        d = d.rename(columns={"日期": "date", "收盘": name})[["date", name]]
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        frames.append(d)
        print("  %s %s：%d 行" % (name, code, len(d)), flush=True)
    if not frames:
        print("指数无新数据")
        return
    new = frames[0]
    for f in frames[1:]:
        new = new.merge(f, on="date", how="outer")
    new = new[new["date"] > last].sort_values("date")
    if new.empty:
        print("指数无新数据")
        return
    out = pd.concat([idx, new], ignore_index=True).sort_values("date")
    out = out.drop_duplicates("date", keep="last")
    bak = INDEX_CSV + ".bak_" + datetime.now().strftime("%Y%m%d%H%M")
    import shutil
    shutil.copy2(INDEX_CSV, bak)
    out.to_csv(INDEX_CSV, index=False)
    print("指数更新到 %s（备份 %s）" % (out["date"].max(), os.path.basename(bak)),
          flush=True)


# ------------------------------------------------------------------
# 指数估值（无日频公开源，按价格推算）
# ------------------------------------------------------------------
def update_valuation():
    if not os.path.exists(VALUATION_CSV):
        print("找不到", VALUATION_CSV, "，跳过")
        return
    old = pd.read_csv(VALUATION_CSV, dtype={"trade_date": str})
    if "source" not in old.columns:
        old["source"] = "tushare"
    rows = []
    for name, code in INDEX_CODES.items():
        sub = old[old["ts_code"] == code]
        if sub.empty:
            continue
        sub = sub.sort_values("trade_date")
        base = sub.iloc[-1]
        last = str(base["trade_date"])
        dates = missing_trade_dates(last)
        if not dates:
            print("  %s 已是最新 %s" % (name, last), flush=True)
            continue
        try:
            d = ak.index_zh_a_hist(symbol=code[:6], period="daily",
                                   start_date=dates[0], end_date=dates[-1])
        except Exception as e:
            print("  %s 指数行情失败：%s" % (name, str(e)[:60]), flush=True)
            continue
        if d is None or not len(d):
            continue
        d = d.rename(columns={"日期": "date", "收盘": "close",
                              "成交额": "amount"})
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        d = d.sort_values("date")
        # 基准日行情（用于换手率按成交额比例外推）
        try:
            b = ak.index_zh_a_hist(symbol=code[:6], period="daily",
                                   start_date=last.replace("-", ""),
                                   end_date=last.replace("-", ""))
            b = b.rename(columns={"日期": "date", "收盘": "close",
                                  "成交额": "amount"}).iloc[0]
            base_close, base_amt = float(b["close"]), float(b["amount"])
        except Exception:
            base_close, base_amt = np.nan, np.nan
        for _, r in d.iterrows():
            dt = r["date"]
            if dt <= last:
                continue
            close, amt = _num(r["close"]), _num(r["amount"])
            ratio = close / base_close if base_close > 0 else np.nan
            row = {
                "name": name, "ts_code": code, "trade_date": dt,
                "pe": _num(base["pe"]) * ratio if np.isfinite(ratio) else np.nan,
                "pe_ttm": _num(base["pe_ttm"]) * ratio if np.isfinite(ratio) else np.nan,
                "pb": _num(base["pb"]) * ratio if np.isfinite(ratio) else np.nan,
                "turnover_rate": _num(base["turnover_rate"]) * amt / base_amt
                if base_amt > 0 and np.isfinite(amt) else np.nan,
                "turnover_rate_f": np.nan,
                "total_mv": np.nan, "float_mv": np.nan,
                "source": "ak-proj",
            }
            rows.append(row)
    if not rows:
        print("指数估值无新数据")
        return
    new = pd.DataFrame(rows)
    out = pd.concat([old, new], ignore_index=True)
    out = out.drop_duplicates(["ts_code", "trade_date"], keep="last")
    out = out.sort_values(["ts_code", "trade_date"], ignore_index=True)
    import shutil
    bak = VALUATION_CSV + ".bak_" + datetime.now().strftime("%Y%m%d%H%M")
    shutil.copy2(VALUATION_CSV, bak)
    out.to_csv(VALUATION_CSV, index=False)
    print("指数估值推算 %d 条，写到 %s（备份 %s）"
          % (len(new), out["trade_date"].max(), os.path.basename(bak)), flush=True)


# ------------------------------------------------------------------
# 两融 / 涨跌停 / 股票列表
# ------------------------------------------------------------------
def update_margin():
    if not os.path.exists(MARGIN_CSV):
        print("找不到", MARGIN_CSV, "，跳过")
        return
    old = pd.read_csv(MARGIN_CSV, dtype={"trade_date": str})
    last = old["trade_date"].max()
    dates = missing_trade_dates(last)
    if not dates:
        print("两融已是最新：%s" % last)
        return
    rows = []
    for dt in dates:
        # 深交所接口不返回日期，可能给的是上一交易日。用上交所的日期做发布确认，
        # 两家同日发布，确认后再写深交所，避免把旧数据标成新日期。
        published = False
        try:
            s = ak.stock_margin_sse(start_date=dt, end_date=dt)
            if s is not None and len(s):
                r = s.iloc[-1]
                if str(r["信用交易日期"]) == dt:
                    published = True
                    rows.append({
                        "trade_date": dt, "exchange_id": "SSE",
                        "rzye": _num(r["融资余额"]),
                        "rzmre": _num(r["融资买入额"]),
                        "rzche": np.nan,
                        "rqye": _num(r["融券余量金额"]),
                        "rqmcl": _num(r["融券卖出量"]),
                        "rzrqye": _num(r["融资融券余额"]),
                        "rqyl": _num(r["融券余量"]),
                    })
        except Exception:
            pass
        if not published:
            print("  %s 两融尚未发布" % dt, flush=True)
            continue
        try:
            z = ak.stock_margin_szse(date=dt)
            if z is not None and len(z):
                r = z.iloc[0]
                rows.append({
                    "trade_date": dt, "exchange_id": "SZSE",
                    "rzye": _num(r["融资余额"]) * 1e8,
                    "rzmre": _num(r["融资买入额"]) * 1e8,
                    "rzche": np.nan,
                    "rqye": _num(r["融券余额"]) * 1e8,
                    "rqmcl": _num(r["融券卖出量"]) * 1e8,
                    "rzrqye": _num(r["融资融券余额"]) * 1e8,
                    "rqyl": _num(r["融券余量"]) * 1e8,
                })
        except Exception:
            pass
        print("  %s 两融：%d 家交易所" % (dt, sum(1 for x in rows if x["trade_date"] == dt)),
              flush=True)
    if not rows:
        print("两融无新数据")
        return
    out = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    out = out.drop_duplicates(["trade_date", "exchange_id"], keep="last")
    out = out.sort_values(["trade_date", "exchange_id"], ignore_index=True)
    import shutil
    bak = MARGIN_CSV + ".bak_" + datetime.now().strftime("%Y%m%d%H%M")
    shutil.copy2(MARGIN_CSV, bak)
    out.to_csv(MARGIN_CSV, index=False)
    print("两融更新到 %s（备份 %s）" % (out["trade_date"].max(), os.path.basename(bak)),
          flush=True)


def update_limit():
    if not os.path.exists(LIMIT_CSV):
        print("找不到", LIMIT_CSV, "，跳过")
        return
    old = pd.read_csv(LIMIT_CSV, dtype={"trade_date": str})
    last = old["trade_date"].max()
    dates = missing_trade_dates(last)
    if not dates:
        print("涨跌停已是最新：%s" % last)
        return
    rows = []
    for dt in dates:
        try:
            up = len(ak.stock_zt_pool_em(date=dt))
        except Exception:
            up = None
        try:
            dn = len(ak.stock_zt_pool_dtgc_em(date=dt))
        except Exception:
            dn = None
        if up is None and dn is None:
            continue
        rows.append({"trade_date": dt,
                     "limit_up_n": up if up is not None else np.nan,
                     "limit_down_n": dn if dn is not None else np.nan})
        print("  %s 涨停 %s / 跌停 %s" % (dt, up, dn), flush=True)
    if not rows:
        print("涨跌停无新数据")
        return
    out = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    out = out.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    import shutil
    bak = LIMIT_CSV + ".bak_" + datetime.now().strftime("%Y%m%d%H%M")
    shutil.copy2(LIMIT_CSV, bak)
    out.to_csv(LIMIT_CSV, index=False)
    print("涨跌停更新到 %s（备份 %s）" % (out["trade_date"].max(), os.path.basename(bak)),
          flush=True)


def _exchange_of(code6):
    if code6.startswith(("60", "68", "90")):
        return "SH"
    if code6.startswith(("00", "30", "20")):
        return "SZ"
    return "BJ"


def update_basic():
    old = pd.read_csv(STOCK_BASIC, dtype=str).fillna("")
    try:
        d = ak.stock_info_a_code_name()
    except Exception as e:
        print("股票列表获取失败：%s" % str(e)[:80], flush=True)
        return
    d = d.rename(columns={"code": "代码", "name": "名称"})
    d["代码"] = d["代码"].astype(str).str.zfill(6)
    d["ts_code"] = d["代码"] + "." + d["代码"].map(_exchange_of)
    old = old.set_index("ts_code")
    add, rename = [], 0
    for r in d.itertuples():
        code, name = r.ts_code, str(r.名称).strip()
        if code in old.index:
            if old.at[code, "name"] != name:
                old.at[code, "name"] = name
                rename += 1
        else:
            add.append({"ts_code": code, "name": name, "industry": "",
                        "list_date": "", "market": ""})
    out = pd.concat([old.reset_index(), pd.DataFrame(add)], ignore_index=True)
    out = out.sort_values("ts_code", ignore_index=True)
    import shutil
    bak = STOCK_BASIC + ".bak_" + datetime.now().strftime("%Y%m%d%H%M")
    shutil.copy2(STOCK_BASIC, bak)
    out.to_csv(STOCK_BASIC, index=False)
    print("股票列表：新增 %d 只，改名 %d 只，合计 %d 只（备份 %s）"
          % (len(add), rename, len(out), os.path.basename(bak)), flush=True)


# ------------------------------------------------------------------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    modes = ("panel", "index", "basic", "margin", "limit", "valuation",
             "downstream", "all")
    if mode not in modes:
        print(__doc__)
        sys.exit(1)
    if mode == "downstream":
        downstream()
        return
    if mode in ("index", "all"):
        update_index()
    if mode in ("valuation", "all"):
        update_valuation()
    if mode in ("margin", "all"):
        update_margin()
    if mode in ("limit", "all"):
        update_limit()
    if mode in ("basic", "all"):
        update_basic()
    if mode in ("panel", "all"):
        update_panel()


if __name__ == "__main__":
    main()
