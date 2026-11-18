# -*- coding: utf-8 -*-
"""通过 datahubco API 增量更新市场指标（PE/PB/成交/广度/200MA/新高新低）到最新日期。"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR, PANEL_PARQUET

os.environ['NO_PROXY'] = '*'
import requests

KEY = os.environ.get('DATAHUB_API_KEY', '')  # 环境变量提供，勿硬编码
BASE = 'http://datahubco.com/app-api/openapi/v1/tushare/'
HEAD = {'X-API-Key': KEY}


def fetch_day(endpoint, trade_date, limit=5000):
    rows, offset, fields = [], 0, None
    for _ in range(40):
        d = None
        for attempt in range(6):
            try:
                r = requests.get(BASE + endpoint, headers=HEAD,
                                 params={'trade_date': trade_date, 'limit': limit, 'offset': offset}, timeout=60)
                if r.status_code == 429:
                    wait = 10 + attempt * 8
                    print('  429', endpoint, trade_date, '等待 %ds' % wait, flush=True)
                    time.sleep(wait)
                    continue
                d = r.json()
                break
            except Exception:
                time.sleep(3 * (attempt + 1))
        if d is None:
            print('  ', endpoint, trade_date, '多次重试失败'); break
        if d.get('code') != 0:
            print('  ', endpoint, trade_date, 'code', d.get('code')); break
        data = d['data']; fields = data['fields']; items = data.get('items') or []
        if not items:
            break
        rows.extend(items)
        if not data.get('has_more'):
            break
        offset += limit
        time.sleep(0.5)
    return pd.DataFrame(rows, columns=fields) if rows else None


def fetch_index(start, end):
    rows, offset, fields = [], 0, None
    for _ in range(20):
        r = requests.get(BASE + 'index-daily', headers=HEAD,
                         params={'ts_code': '000001.SH', 'start_date': start, 'end_date': end, 'limit': 5000, 'offset': offset}, timeout=30)
        d = r.json()
        if d.get('code') != 0:
            break
        data = d['data']; fields = data['fields']; items = data.get('items') or []
        rows.extend(items)
        if not data.get('has_more'):
            break
        offset += 5000
    return pd.DataFrame(rows, columns=fields) if rows else None


def main():
    md_path = os.path.join(CACHE_DIR, 'market_daily.parquet')
    md = pd.read_parquet(md_path)
    md['date'] = pd.to_datetime(md['date'])
    last = md['date'].max()
    # 可选：传入 YYYYMMDD 从该日重算（用于修正股票池口径等历史问题）
    if len(sys.argv) > 1:
        last = pd.Timestamp(sys.argv[1]) - pd.Timedelta(days=1)
        print('指定重算起点:', sys.argv[1], '（将重算该日及之后）')
    print('现有 market_daily 最后日期:', last.date())

    start = (last + pd.Timedelta(days=1)).strftime('%Y%m%d')
    end = '20991231'
    idx = fetch_index(start, end)
    if idx is None or len(idx) == 0:
        print('无新交易日'); return
    new_dates = sorted(set(idx['trade_date'].tolist()))
    print('新交易日:', len(new_dates), new_dates[:2], '...', new_dates[-2:])

    panel = pq.read_table(PANEL_PARQUET, columns=['date', 'ticker', 'close', 'close_raw']).to_pandas()
    panel['date'] = pd.to_datetime(panel['date'])
    panel = panel[panel['date'] >= last - pd.Timedelta(days=760)]  # 需 >252 交易日
    panel = panel.sort_values(['ticker', 'date'])
    # 部分日期复权收盘价缺失，但未复权价完整。用最近有效复权因子补齐，
    # 否则 200/252 日 rolling 窗口会被 NaN 截断，广度/新高新低只统计到一半股票。
    panel['close'] = pd.to_numeric(panel['close'], errors='coerce')
    panel['close_raw'] = pd.to_numeric(panel['close_raw'], errors='coerce')
    ratio = panel['close'] / panel['close_raw']
    ratio = ratio.groupby(panel['ticker'], sort=False).ffill()
    ratio = ratio.groupby(panel['ticker'], sort=False).bfill()
    panel['close'] = panel['close'].where(panel['close'].notna(), panel['close_raw'] * ratio)
    # 与历史聚合保持同一股票池（中证全指成分），避免 API 全A（含非成分）造成指标断层
    universe = set(panel.loc[panel['date'] == panel['date'].max(), 'ticker'])
    print('股票池（与面板一致）:', len(universe), '只')

    def fetch_one(dt):
        dly = fetch_day('daily', dt)
        db = fetch_day('daily-basic', dt)
        if dly is None or db is None or len(dly) == 0:
            return None
        db = db[['ts_code', 'pe', 'pb', 'total_mv', 'turnover_rate']]
        m = dly.merge(db, on='ts_code', how='inner')
        m['date'] = pd.to_datetime(m['trade_date'])
        m['ticker'] = m['ts_code']
        m['pct'] = m['pct_chg'].astype(float) / 100.0
        m['amount_y'] = m['amount'].astype(float) * 1000.0
        return m[['date', 'ticker', 'close', 'total_mv', 'turnover_rate', 'pe', 'pb', 'pct', 'amount_y']]

    frames = []
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fetch_one, dt): dt for dt in new_dates}
        for f in as_completed(futs):
            done += 1
            r = f.result()
            dt = futs[f]
            if r is not None:
                frames.append(r)
                print('  [%d/%d] %s: %d 只' % (done, len(new_dates), dt, len(r)), flush=True)
            else:
                print('  [%d/%d] %s: 无数据' % (done, len(new_dates), dt), flush=True)
    if not frames:
        return
    newdf = pd.concat(frames, ignore_index=True)
    _n0 = len(newdf)
    newdf = newdf[newdf['ticker'].isin(universe)].copy()
    print('按面板股票池过滤: %d -> %d 行' % (_n0, len(newdf)))
    newdf['close'] = pd.to_numeric(newdf['close'], errors='coerce')
    for c in ['total_mv', 'turnover_rate', 'pe', 'pb', 'pct', 'amount_y']:
        newdf[c] = pd.to_numeric(newdf[c], errors='coerce')

    # API 返回的是未复权收盘价；历史面板是前复权价。用面板最后一日收盘
    # 作为锚，按每日涨跌幅把尾部价格接到同一复权口径，避免除权日被误判为
    # “跌破 200 日线/创新低”。
    panel_last = panel.sort_values('date').groupby('ticker')['close'].last()
    newdf = newdf.sort_values(['ticker', 'date']).copy()
    newdf['_ret1'] = newdf['pct'].fillna(0.0) + 1.0
    newdf['_cum'] = newdf.groupby('ticker', sort=False)['_ret1'].cumprod()
    newdf['_base'] = newdf['ticker'].map(panel_last)
    newdf['close_adj'] = newdf['_base'] * newdf['_cum']
    newdf['close_adj'] = newdf['close_adj'].where(newdf['close_adj'].notna(), newdf['close'])

    tail = newdf[['date', 'ticker', 'close_adj']].rename(columns={'close_adj': 'close'})
    combined = pd.concat([panel[['date', 'ticker', 'close']], tail], ignore_index=True)
    combined = combined.drop_duplicates(['date', 'ticker']).sort_values(['ticker', 'date'])
    # concat 会保留原索引，panel 与 tail 的索引会重复；rolling 结果按索引对齐时
    # 会发生错位，导致 above200/new_high 只落到极少数股票上。必须先重建唯一索引。
    combined = combined.reset_index(drop=True)
    # 前向填充 close，避免个别 NaN 让 252 日窗口整体失效（新高/新低全 0）
    combined['close'] = combined.groupby('ticker', sort=False)['close'].ffill()
    g = combined.groupby('ticker', sort=False)
    combined['ma200'] = g['close'].rolling(200, min_periods=200).mean().reset_index(level=0, drop=True)
    combined['hi252'] = g['close'].rolling(252, min_periods=252).max().reset_index(level=0, drop=True)
    combined['lo252'] = g['close'].rolling(252, min_periods=252).min().reset_index(level=0, drop=True)
    combined['above200'] = np.where(combined['ma200'].notna(),
                                    (combined['close'] > combined['ma200']).astype(float), np.nan)
    combined['new_high'] = np.where(combined['hi252'].notna(),
                                    (combined['close'] >= combined['hi252']).astype(float), np.nan)
    combined['new_low'] = np.where(combined['lo252'].notna(),
                                   (combined['close'] <= combined['lo252']).astype(float), np.nan)
    ah = combined[['date', 'ticker', 'above200', 'new_high', 'new_low']]
    newdf = newdf.merge(ah, on=['date', 'ticker'], how='left')

    rows = []
    for dt, gp in newdf.groupby('date'):
        pe = gp['pe'].where(gp['pe'] > 0)
        pb = gp['pb'].where(gp['pb'] > 0)
        amt = gp.loc[gp['amount_y'] > 0, 'amount_y'].dropna()
        top = amt.sort_values(ascending=False)
        k = max(1, int(np.ceil(len(top) * 0.05)))
        conc = float(top.iloc[:k].sum() / top.sum()) if top.sum() > 0 else np.nan
        mvpe = np.where(gp['pe'] > 0, gp['total_mv'] / gp['pe'], np.nan)
        rows.append({
            'date': dt, 'count': len(gp), 'total_mv': gp['total_mv'].sum(),
            'pe_median': pe.median(), 'pb_median': pb.median(),
            'turnover_median': gp['turnover_rate'].median(), 'amount': amt.sum(),
            'up_ratio': float((gp['pct'] > 0).sum() / gp['pct'].notna().sum())
            if gp['pct'].notna().any() else np.nan,
            'median_pct': gp['pct'].median(),
            'concentration_top5': conc,
            'above200_ratio': gp['above200'].mean(), 'new_high_n': gp['new_high'].sum(),
            'new_low_n': gp['new_low'].sum(),
            'weighted_pe': gp['total_mv'].sum() / np.nansum(mvpe),
        })
    agg = pd.DataFrame(rows).sort_values('date')
    md2 = pd.concat([md[md['date'] <= last], agg], ignore_index=True).sort_values('date')
    md2.to_parquet(md_path, index=False)
    print('market_daily 更新到', md2['date'].max().date(), '| 新增', len(agg), '天 | 总', len(md2), '行')
    print(agg.tail(2).to_string())


if __name__ == '__main__':
    main()
