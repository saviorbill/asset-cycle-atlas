# -*- coding: utf-8 -*-
"""通过 datahubco API 增量抓取 IPO / 股东增减持数据，按月聚合。

输出:
  cache/ipo_monthly.parquet     (month, ipo_count, ipo_funds_yi)
  cache/holder_monthly.parquet  (month, net_reduce_yi)  # 净减持金额(亿元)
"""
import os, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR

os.environ['NO_PROXY'] = '*'
import requests

KEY = os.environ.get('DATAHUB_API_KEY', '')  # 环境变量提供，勿硬编码
BASE = 'http://datahubco.com/app-api/openapi/v1/tushare/'
HEAD = {'X-API-Key': KEY}


def fetch_all(endpoint, extra=None, limit=5000, max_pages=60, sleep=0.3):
    """分页拉取全量。"""
    rows = []
    offset = 0
    fields = None
    for page in range(max_pages):
        params = {'limit': limit, 'offset': offset}
        if extra:
            params.update(extra)
        for attempt in range(3):
            try:
                r = requests.get(BASE + endpoint, headers=HEAD, params=params, timeout=40)
                d = r.json()
                break
            except Exception as e:
                print(f'  重试 {endpoint} offset={offset}: {e}')
                time.sleep(2)
        else:
            break
        if d.get('code') != 0:
            print(f'  {endpoint} code={d.get("code")} msg={d.get("msg")}')
            break
        data = d['data']
        fields = data.get('fields')
        items = data.get('items') or []
        if not items:
            break
        rows.extend(items)
        print(f'  {endpoint} offset={offset} 拉取 {len(items)} 条 (累计 {len(rows)})')
        if not data.get('has_more'):
            break
        offset += limit
        time.sleep(sleep)
    if not rows or not fields:
        return None
    return pd.DataFrame(rows, columns=fields)


def month_from_str(s):
    s = str(s)
    if len(s) >= 6:
        return s[:4] + '-' + s[4:6]
    return None


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    print('=== 拉取 IPO (new-share) ===')
    ipo = fetch_all('new-share', limit=5000)
    if ipo is not None and len(ipo):
        ipo['ipo_date'] = ipo['ipo_date'].astype(str)
        ipo['month'] = ipo['ipo_date'].map(month_from_str)
        ipo = ipo.dropna(subset=['month'])
        ipo['funds_yi'] = pd.to_numeric(ipo['funds'], errors='coerce') / 1e8  # funds单位不确定, 先存
        g = ipo.groupby('month').agg(ipo_count=('ts_code', 'count'), ipo_funds_yi=('funds_yi', 'sum')).reset_index()
        g.to_parquet(os.path.join(CACHE_DIR, 'ipo_monthly.parquet'), index=False)
        print('IPO 月度:', len(g), '行 | 范围:', g['month'].min(), '~', g['month'].max())
        print(g.tail(3).to_string())

    print('\n=== 拉取 股东增减持 (stk-holdertrade) ===')
    ht = fetch_all('stk-holdertrade', limit=5000)
    if ht is not None and len(ht):
        ht['ann_date'] = ht['ann_date'].astype(str)
        ht['month'] = ht['ann_date'].map(month_from_str)
        ht = ht.dropna(subset=['month'])
        for c in ['change_vol', 'avg_price', 'change_ratio']:
            ht[c] = pd.to_numeric(ht[c], errors='coerce')
        ht['amount_yi'] = ht['change_vol'] * ht['avg_price'] / 1e8
        # DE=减持(正), IN=增持(负)
        ht['signed'] = np.where(ht['in_de'] == 'DE', ht['amount_yi'], -ht['amount_yi'])
        g = ht.groupby('month').agg(net_reduce_yi=('signed', 'sum')).reset_index()
        g.to_parquet(os.path.join(CACHE_DIR, 'holder_monthly.parquet'), index=False)
        print('减持 月度:', len(g), '行 | 范围:', g['month'].min(), '~', g['month'].max())
        print(g.tail(3).to_string())


if __name__ == '__main__':
    main()
